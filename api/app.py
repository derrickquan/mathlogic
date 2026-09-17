"""HTTP.

A thin layer: authenticate, parse, call the service, serialise. Anything that
looks like a decision belongs in `progression/`, and anything that looks like SQL
belongs in `db.py`. If a rule starts creeping into a route handler, it is in the
wrong file.

Every route says who may call it, and the identity always comes from the token
rather than the body. A `staff_id` in a JSON payload is a `staff_id` anyone can
type.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from progression import Location, from_templates

from . import db
from .auth import Principal, SessionKind, bearer
from .recognition import DeclaredValueRecogniser, NullRecogniser, Recogniser
from .service import Conflict, Forbidden, NotFound, Service, Unauthenticated

DEFAULT_DSN = os.environ.get("MATHLOGIC_DSN", "postgresql:///mathlogic")


def build_service(dsn: str | None = None, recogniser: Recogniser | None = None) -> Service:
    return Service(
        database=db.Database(dsn or DEFAULT_DSN),
        catalogue=from_templates(),
        recogniser=recogniser or _default_recogniser(),
    )


def _default_recogniser() -> Recogniser:
    """No engine is chosen yet, so the default reads nothing.

    That is the honest state: every answer goes to a facilitator rather than
    being silently marked by a stand-in nobody remembered was a stand-in. Set
    MATHLOGIC_RECOGNISER=declared to let the client say what it wrote, which is
    for tests and the prototype only.
    """
    if os.environ.get("MATHLOGIC_RECOGNISER") == "declared":
        return DeclaredValueRecogniser()
    return NullRecogniser()


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


class Login(BaseModel):
    email: str
    password: str


class CheckIn(BaseModel):
    badge_code: str
    tablet_id: str | None = None


class Unlock(BaseModel):
    student_id: str


class Calibration(BaseModel):
    samples: dict[str, Any] = Field(
        description="One entry per digit, '0' through '10', each holding that digit's strokes."
    )


class StartAttempt(BaseModel):
    student_id: str
    location: Location = Location.CENTRE


class SubmitAnswer(BaseModel):
    problem_id: str
    ink: list[dict[str, Any]] = Field(
        description="Stroke data, not a bitmap. Kept permanently and never discarded after grading."
    )
    active_seconds: int = 0


class Override(BaseModel):
    value: str


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def create_app(service: Service | None = None) -> FastAPI:
    built = service

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = built or build_service()
        yield
        if built is None:
            app.state.service.database.close()

    app = FastAPI(title="MathLogic", version="0.1.0", lifespan=lifespan)

    # -- plumbing ----------------------------------------------------------

    def service_of(request: Request) -> Service:
        return request.app.state.service

    def guard(fn: Callable, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Unauthenticated as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Forbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Conflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def principal(request: Request) -> Principal:
        current = service_of(request)
        return guard(current.principal_for, bearer(request.headers.get("authorization")))

    def of_kind(kind: SessionKind):
        def dependency(who: Principal = Depends(principal)) -> Principal:
            if who.kind is not kind:
                raise HTTPException(
                    status_code=403,
                    detail=f"this needs a {kind.value} session, not a {who.kind.value} one",
                )
            return who
        return dependency

    parent_only = of_kind(SessionKind.PARENT)
    staff_only = of_kind(SessionKind.STAFF)

    def about(who: Principal, student_id: str, request: Request) -> Principal:
        """Allow a caller to act on one student.

        The student themself, the parent who holds their account, or a
        facilitator. Anybody else gets a 403 — including a parent reaching for
        somebody else's child, which is the check that actually matters.
        """
        if who.kind is SessionKind.STUDENT:
            if who.student_id != student_id:
                raise HTTPException(status_code=403, detail="that is not your work")
            return who
        if who.kind is SessionKind.STAFF:
            return who
        with service_of(request).database.connection() as conn:
            if db.parent_owns(conn, who.subject_id, student_id):
                return who
        raise HTTPException(status_code=403, detail="that is not your child")

    def student_of(attempt_id: str, who: Principal, request: Request) -> str:
        with service_of(request).database.connection() as conn:
            owner = db.student_of_attempt(conn, attempt_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="no such attempt")
        if who.kind is SessionKind.STUDENT and who.student_id != owner:
            raise HTTPException(status_code=403, detail="that is not your work")
        if who.kind is SessionKind.PARENT:
            raise HTTPException(status_code=403, detail="a parent does not do the work")
        return owner

    # -- routes ------------------------------------------------------------

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/parent/login")
    def parent_login(body: Login, request: Request) -> dict[str, Any]:
        return guard(service_of(request).log_in_parent, body.email, body.password)

    @app.post("/auth/staff/login")
    def staff_login(body: Login, request: Request) -> dict[str, Any]:
        return guard(service_of(request).log_in_staff, body.email, body.password)

    @app.post("/auth/logout")
    def logout(request: Request, who: Principal = Depends(principal)) -> dict[str, Any]:
        return guard(service_of(request).log_out, who)

    @app.post("/auth/student/unlock")
    def unlock(body: Unlock, request: Request,
               who: Principal = Depends(parent_only)) -> dict[str, Any]:
        """A parent hands the tablet over. Once per sitting, not per packet."""
        return guard(service_of(request).unlock_student, who, body.student_id)

    @app.post("/check-in")
    def check_in(body: CheckIn, request: Request) -> dict[str, Any]:
        """The badge is the credential. Open by design: nothing to type, nothing
        to remember, and what it returns can only ever open the work."""
        return guard(service_of(request).check_in, body.badge_code, body.tablet_id)

    @app.post("/students/{student_id}/calibration")
    def calibrate(student_id: str, body: Calibration, request: Request,
                  who: Principal = Depends(principal)) -> dict[str, Any]:
        about(who, student_id, request)
        return guard(service_of(request).calibrate, student_id, body.samples)

    @app.get("/students/{student_id}/assignment")
    def assignment(student_id: str, request: Request, location: Location = Location.CENTRE,
                   who: Principal = Depends(principal)) -> dict[str, Any]:
        about(who, student_id, request)
        return guard(service_of(request).assignment, student_id, location)

    @app.post("/attempts")
    def start_attempt(body: StartAttempt, request: Request,
                      who: Principal = Depends(principal)) -> dict[str, Any]:
        if who.kind is not SessionKind.STUDENT or who.student_id != body.student_id:
            raise HTTPException(status_code=403, detail="only a student works their own packet")
        return guard(service_of(request).start_attempt, body.student_id, body.location)

    @app.post("/attempts/{attempt_id}/answers")
    def submit_answer(attempt_id: str, body: SubmitAnswer, request: Request,
                      who: Principal = Depends(principal)) -> dict[str, Any]:
        student_of(attempt_id, who, request)
        return guard(
            service_of(request).submit_answer,
            attempt_id,
            body.problem_id,
            body.ink,
            active_seconds=body.active_seconds,
        )

    @app.post("/attempts/{attempt_id}/submit")
    def submit_attempt(attempt_id: str, request: Request,
                       who: Principal = Depends(principal)) -> dict[str, Any]:
        student_of(attempt_id, who, request)
        return guard(service_of(request).submit_attempt, attempt_id)

    @app.get("/students/{student_id}/corrections")
    def corrections(student_id: str, request: Request,
                    who: Principal = Depends(principal)) -> list[dict[str, Any]]:
        about(who, student_id, request)
        return guard(service_of(request).corrections, student_id)

    @app.post("/corrections/{correction_id}/resolve")
    def resolve(correction_id: str, request: Request,
                who: Principal = Depends(principal)) -> dict[str, Any]:
        with service_of(request).database.connection() as conn:
            owner = db.student_of_correction(conn, correction_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="no such correction")
        about(who, owner, request)
        return guard(service_of(request).resolve_correction, correction_id)

    @app.post("/students/{student_id}/close-homework")
    def close_homework(student_id: str, request: Request,
                       who: Principal = Depends(principal)) -> dict[str, Any]:
        about(who, student_id, request)
        return guard(service_of(request).close_homework, student_id)

    @app.post("/students/{student_id}/corrections/cancel")
    def cancel_backlog(student_id: str, request: Request,
                       who: Principal = Depends(staff_only)) -> dict[str, Any]:
        """Clearing a backlog drops the student a packet, so it is a facilitator's
        to do and their name goes on it — from their session, not from a body
        field anyone could type."""
        return guard(service_of(request).cancel_backlog, student_id, who.subject_id)

    @app.post("/answers/{answer_id}/override")
    def override(answer_id: str, body: Override, request: Request,
                 who: Principal = Depends(staff_only)) -> dict[str, Any]:
        return guard(service_of(request).override, answer_id, body.value, who.subject_id)

    @app.get("/console/room")
    def room(request: Request,
             who: Principal = Depends(staff_only)) -> list[dict[str, Any]]:
        return guard(service_of(request).room)

    return app


app = create_app
