"""Who is asking, and what that lets them do.

Three kinds of caller, and the distance between them is the security model:

  * **A parent** holds the account. No six-year-old manages credentials, and the
    parent's login is what gives access to reports and history.
  * **A facilitator** runs the console. Short sessions, because the console is a
    shared machine in a room full of children.
  * **A student session** is the tablet, working. It is opened either by a badge
    scan at the centre or by a parent unlocking at home, and it is scoped to one
    student. It can never reach the parent view — the child must not be left
    sitting inside a screen with their own scores and reports in it.

Passwords are hashed with scrypt from the standard library: memory-hard, no
dependency to keep current, and no chance of a home-made construction. argon2id
would be the other reasonable choice and would mean taking on argon2-cffi; if
that trade ever changes, `hash_password` and `verify_password` are the only two
functions that have to move.

Tokens are opaque and random. Only their SHA-256 is stored, so the sessions table
tells a reader nothing they could use.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

# Interactive-grade scrypt: ~32 MB and a few tenths of a second per hash.
_N = 2 ** 15
_R = 8
_P = 1
_MAXMEM = 96 * 1024 * 1024
_SALT_BYTES = 16
_KEY_BYTES = 32


class SessionKind(str, Enum):
    PARENT = "parent"
    STAFF = "staff"
    STUDENT = "student"


#: How long each kind of session lasts, and why.
LIFETIMES: dict[SessionKind, timedelta] = {
    # A parent checks reports on their phone; making them log in nightly would
    # only teach them to ignore the app.
    SessionKind.PARENT: timedelta(days=30),
    # A shared console in a room of children should not still be open tomorrow.
    SessionKind.STAFF: timedelta(hours=12),
    # One sitting, with room either side. A centre session is about 45 minutes
    # and homework is an evening; neither is a working day.
    SessionKind.STUDENT: timedelta(hours=4),
}


@dataclass(frozen=True)
class Principal:
    """The authenticated caller behind one request."""

    kind: SessionKind
    session_id: str
    parent_id: str | None = None
    staff_id: str | None = None
    student_id: str | None = None
    unlocked_by: str | None = None

    @property
    def subject_id(self) -> str:
        for candidate in (self.parent_id, self.staff_id, self.student_id):
            if candidate:
                return candidate
        raise ValueError("a principal with no subject")


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt$key`, all base64, self-describing so the parameters
    can be raised later without invalidating everyone's password."""
    if not password:
        raise ValueError("a password cannot be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=_KEY_BYTES
    )
    return "$".join(["scrypt", str(_N), str(_R), str(_P), _b64(salt), _b64(key)])


def verify_password(password: str, stored: str) -> bool:
    """Constant-time, and never raises on a malformed stored value.

    A hash that cannot be parsed is treated as a failed login rather than a
    crash: a row in the wrong format is a bug worth finding in the logs, not a
    500 that tells an attacker they found something interesting.
    """
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt":
            return False
        computed = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=_MAXMEM,
            dklen=len(_unb64(key)),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(computed, _unb64(key))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def new_token() -> tuple[str, str]:
    """A token to hand out, and the hash to keep. The plain one is never stored."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bearer(header: str | None) -> str | None:
    """Pull the token out of an Authorization header, or None."""
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()
