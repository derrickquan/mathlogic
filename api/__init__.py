"""The server: HTTP, the database, recognition, and the wiring between them.

    api/recognition.py  the engine behind a protocol — none chosen yet
    api/grading.py      a reading plus the answer key becomes a verdict
    api/db.py           every statement that touches PostgreSQL
    api/service.py      the loop: the only place rules, queries and ink meet
    api/app.py          routes

Run it against a database that has the schema applied and a level loaded:

    MATHLOGIC_DSN=postgresql:///mathlogic uvicorn api.app:app --factory
"""

from __future__ import annotations

from .grading import Grade, Verdict, grade
from .recognition import DeclaredValueRecogniser, NullRecogniser, Reading, Recogniser
from .service import Conflict, NotFound, Service

__all__ = [
    "Conflict",
    "DeclaredValueRecogniser",
    "Grade",
    "NotFound",
    "NullRecogniser",
    "Reading",
    "Recogniser",
    "Service",
    "Verdict",
    "grade",
]
