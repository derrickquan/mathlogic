"""HTTP.

A thin layer: parse, call the service, serialise. Anything that looks like a
decision belongs in `progression/`, and anything that looks like SQL belongs in
`db.py`. If a rule starts creeping into a route handler, it is in the wrong file.

Authentication is not here yet. The parent holds the account and the student
checks in with a badge; wiring the sessions and the parent unlock is its own
piece of work and is deliberately not faked in the meantime.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from progression import Location, from_templates

from . import db
from .recognition import DeclaredValueRecogniser, NullRecogniser, Recogniser
from .service import Conflict, NotFound, Service

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


class CheckIn(BaseModel):
    badge_code: str
    tablet_id: str | None = None


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
    staff_id: str


class CancelBacklog(BaseModel):
    staff_id: str


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

    def current(request_app: FastAPI = Depends(lambda: app)) -> Service:
        return request_app.state.service

    @app.exception_handler(NotFound)
    async def _not_found(_, exc: NotFound):
        raise HTTPException(status_code=404, detail=str(exc))

    @app.exception_handler(Conflict)
    async def _conflict(_, exc: Conflict):
        raise HTTPException(status_code=409, detail=str(exc))

    def guard(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Conflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/check-in")
    def check_in(body: CheckIn, service: Service = Depends(current)) -> dict[str, Any]:
        return guard(service.check_in, body.badge_code, body.tablet_id)

    @app.post("/students/{student_id}/calibration")
    def calibrate(student_id: str, body: Calibration,
                  service: Service = Depends(current)) -> dict[str, Any]:
        return guard(service.calibrate, student_id, body.samples)

    @app.get("/students/{student_id}/assignment")
    def assignment(student_id: str, location: Location = Location.CENTRE,
                   service: Service = Depends(current)) -> dict[str, Any]:
        return guard(service.assignment, student_id, location)

    @app.post("/attempts")
    def start_attempt(body: StartAttempt, service: Service = Depends(current)) -> dict[str, Any]:
        return guard(service.start_attempt, body.student_id, body.location)

    @app.post("/attempts/{attempt_id}/answers")
    def submit_answer(attempt_id: str, body: SubmitAnswer,
                      service: Service = Depends(current)) -> dict[str, Any]:
        return guard(
            service.submit_answer,
            attempt_id,
            body.problem_id,
            body.ink,
            active_seconds=body.active_seconds,
        )

    @app.post("/attempts/{attempt_id}/submit")
    def submit_attempt(attempt_id: str, service: Service = Depends(current)) -> dict[str, Any]:
        return guard(service.submit_attempt, attempt_id)

    @app.get("/students/{student_id}/corrections")
    def corrections(student_id: str, service: Service = Depends(current)) -> list[dict[str, Any]]:
        return guard(service.corrections, student_id)

    @app.post("/corrections/{correction_id}/resolve")
    def resolve(correction_id: str, service: Service = Depends(current)) -> dict[str, Any]:
        return guard(service.resolve_correction, correction_id)

    @app.post("/students/{student_id}/close-homework")
    def close_homework(student_id: str, service: Service = Depends(current)) -> dict[str, Any]:
        return guard(service.close_homework, student_id)

    @app.post("/students/{student_id}/corrections/cancel")
    def cancel_backlog(student_id: str, body: CancelBacklog,
                       service: Service = Depends(current)) -> dict[str, Any]:
        return guard(service.cancel_backlog, student_id, body.staff_id)

    @app.post("/answers/{answer_id}/override")
    def override(answer_id: str, body: Override,
                 service: Service = Depends(current)) -> dict[str, Any]:
        return guard(service.override, answer_id, body.value, body.staff_id)

    @app.get("/console/room")
    def room(service: Service = Depends(current)) -> list[dict[str, Any]]:
        return guard(service.room)

    return app


app = create_app
