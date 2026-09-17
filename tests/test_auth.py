"""Passwords and tokens, without a database."""

from __future__ import annotations

import pytest

from api.auth import (
    LIFETIMES,
    Principal,
    SessionKind,
    bearer,
    hash_password,
    new_token,
    token_hash,
    verify_password,
)


def test_a_password_verifies_against_its_own_hash():
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored)


def test_a_wrong_password_does_not():
    stored = hash_password("correct horse battery staple")
    assert not verify_password("correct horse battery stapl", stored)
    assert not verify_password("", stored)


def test_the_same_password_hashes_differently_every_time():
    """Per-password salt, so two parents who pick the same password do not share
    a hash and a stolen table cannot be attacked once for all of them."""
    a = hash_password("hunter2")
    b = hash_password("hunter2")
    assert a != b
    assert verify_password("hunter2", a) and verify_password("hunter2", b)


def test_the_hash_says_what_made_it():
    scheme, n, r, p, salt, key = hash_password("x").split("$")
    assert scheme == "scrypt"
    assert int(n) >= 2 ** 14, "memory-hard enough to be worth the name"
    assert int(r) >= 8 and int(p) >= 1
    assert salt and key


def test_a_malformed_stored_hash_is_a_failed_login_not_a_crash():
    """A row in the wrong shape is a bug to find in the logs, not a 500 that
    tells an attacker they have found something interesting."""
    for rubbish in ("", "nonsense", "scrypt$x$y$z$q$r", "bcrypt$1$2$3$4$5", "$$$$$"):
        assert verify_password("anything", rubbish) is False


def test_an_empty_password_cannot_be_set():
    with pytest.raises(ValueError, match="cannot be empty"):
        hash_password("")


def test_tokens_are_unguessable_and_stored_only_as_a_hash():
    token, digest = new_token()
    assert len(token) >= 40
    assert digest == token_hash(token)
    assert token not in digest, "the plain token is never what is kept"
    assert new_token()[0] != token


def test_bearer_headers_are_parsed_and_rubbish_is_not():
    assert bearer("Bearer abc123") == "abc123"
    assert bearer("bearer abc123") == "abc123"
    assert bearer("Basic abc123") is None
    assert bearer("Bearer   ") is None
    assert bearer("abc123") is None
    assert bearer(None) is None


def test_session_lifetimes_reflect_where_each_one_lives():
    """A shared console should not still be open tomorrow; a parent's phone
    should not ask for a password nightly, or they will stop reading the app."""
    assert LIFETIMES[SessionKind.STAFF] < LIFETIMES[SessionKind.PARENT]
    assert LIFETIMES[SessionKind.STUDENT] < LIFETIMES[SessionKind.STAFF]
    assert LIFETIMES[SessionKind.STUDENT].total_seconds() >= 60 * 60


def test_a_principal_knows_its_own_subject():
    assert Principal(SessionKind.STAFF, "s1", staff_id="abc").subject_id == "abc"
    assert Principal(SessionKind.STUDENT, "s1", student_id="def").subject_id == "def"
    with pytest.raises(ValueError, match="no subject"):
        Principal(SessionKind.PARENT, "s1").subject_id
