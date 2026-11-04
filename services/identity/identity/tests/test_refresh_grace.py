"""Refresh reuse grace window: a lost rotation response must not end the session.

A tab that reloads or closes mid-refresh spends the token on the server but never
stores its successor; the next tab replays the spent token. Inside the window,
and only while nothing downstream has been used, that replay gets a sibling.
Everything else is still treated as theft and revokes the family.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from identity import services, tokens
from identity.models import RefreshToken, SecurityEvent, UserSession


@pytest.fixture
def issued(active_account, settings):
    settings.REFRESH_REUSE_GRACE_SECONDS = 20
    return services.login(email=active_account.email, password="DevPassw0rd!")


def _spend(raw: str) -> str:
    return tokens.rotate_refresh_token(raw)[4]


def test_replay_inside_the_window_gets_a_sibling_and_keeps_the_session(issued, active_account):
    lost = _spend(issued.refresh_token)  # the response that never reached the browser

    _, session, access, _, sibling = tokens.rotate_refresh_token(issued.refresh_token)

    assert access and sibling not in (issued.refresh_token, lost)
    session.refresh_from_db()
    assert session.revoked_at is None
    assert RefreshToken.objects.filter(revoked_at__isnull=False).count() == 0
    # The sibling keeps working, and so would the lost successor.
    assert _spend(sibling)
    assert SecurityEvent.objects.filter(
        account=active_account, type="refresh_reuse_within_grace"
    ).exists()


def test_replay_after_a_successor_was_used_is_still_theft(issued):
    successor = _spend(issued.refresh_token)
    _spend(successor)  # the chain moved on: the old token is stale, not lost

    with pytest.raises(tokens.TokenError):
        tokens.rotate_refresh_token(issued.refresh_token)
    assert RefreshToken.objects.filter(revoked_at__isnull=True).count() == 0
    assert UserSession.objects.filter(revoked_at__isnull=True).count() == 0


def test_replay_after_the_window_revokes_the_family(issued):
    _spend(issued.refresh_token)
    RefreshToken.objects.filter(used_at__isnull=False).update(
        used_at=timezone.now() - timedelta(seconds=21)
    )

    with pytest.raises(tokens.TokenError):
        tokens.rotate_refresh_token(issued.refresh_token)
    assert RefreshToken.objects.filter(revoked_at__isnull=True).count() == 0


def test_the_window_mints_a_bounded_number_of_siblings(issued):
    _spend(issued.refresh_token)
    for _ in range(tokens.REUSE_GRACE_MAX_SUCCESSORS - 1):
        tokens.rotate_refresh_token(issued.refresh_token)

    with pytest.raises(tokens.TokenError):
        tokens.rotate_refresh_token(issued.refresh_token)
    assert RefreshToken.objects.filter(revoked_at__isnull=True).count() == 0


def test_a_signed_out_session_gets_nothing_from_the_window(issued):
    _spend(issued.refresh_token)
    session = UserSession.objects.get()
    tokens.revoke_session(session)

    with pytest.raises(tokens.TokenError):
        tokens.rotate_refresh_token(issued.refresh_token)


def test_zero_disables_the_window(issued, settings):
    settings.REFRESH_REUSE_GRACE_SECONDS = 0
    _spend(issued.refresh_token)

    with pytest.raises(tokens.TokenError):
        tokens.rotate_refresh_token(issued.refresh_token)
