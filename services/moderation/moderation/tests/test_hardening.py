"""Milestone 1.2: case state guards, action table, report intake, appeals."""

import uuid

import pytest
from django.urls import reverse

from moderation import services
from moderation.handlers import (
    on_comment_reported,
    on_listing_reported,
    on_listing_review_reported,
    on_post_reported,
)
from moderation.models import (
    Appeal,
    ModerationAction,
    ModerationAuditLog,
    ModerationCase,
    OutboxEvent,
    Report,
)
from tara_common.exceptions import Conflict, TaraAPIError
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _case(target_type="post", target_id=None, owner_id=None) -> ModerationCase:
    return services.ingest_report(
        reporter_id=_acct(),
        target_type=target_type,
        target_id=target_id or _acct(),
        owner_id=owner_id,
    )


def _actioned() -> int:
    return OutboxEvent.objects.filter(event_type="moderation.actioned").count()


def _post_reported(payload: dict) -> None:
    on_post_reported(
        EventEnvelope(
            event_type="post.reported",
            subject_id=payload.get("post_id", "x"),
            producer="post-service",
            payload=payload,
        )
    )


@pytest.fixture
def moderator(client_for):
    mod_id = _acct()
    return mod_id, client_for(mod_id, roles=["moderator"])


# ---- assign -----------------------------------------------------------------


def test_assign_open_case_moves_it_to_review_with_an_audit_row(moderator):
    mod_id, client = moderator
    case = _case()
    resp = client.post(reverse("moderation:case-assign", args=[case.id]))
    assert resp.status_code == 200
    assert resp.json()["data"]["state"] == "in_review"
    assert resp.json()["data"]["assigned_to"] == mod_id
    audit = ModerationAuditLog.objects.get(case=case, action="assign")
    assert audit.before == {"state": "open", "assigned_to": None}
    assert audit.after == {"state": "in_review", "assigned_to": mod_id}


def test_in_review_case_can_be_reassigned(moderator):
    _, client = moderator
    case = _case()
    first = _acct()
    services.assign(str(case.id), first)
    resp = client.post(reverse("moderation:case-assign", args=[case.id]))
    assert resp.status_code == 200
    audits = ModerationAuditLog.objects.filter(case=case, action="assign").order_by("created_at")
    assert audits.count() == 2
    assert audits.last().before == {"state": "in_review", "assigned_to": first}


def test_assigning_a_resolved_case_returns_409_and_changes_nothing(moderator):
    _, client = moderator
    case = _case()
    services.take_action(str(case.id), _acct(), "dismiss")
    resp = client.post(reverse("moderation:case-assign", args=[case.id]))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"
    case.refresh_from_db()
    assert case.state == ModerationCase.State.RESOLVED
    assert case.assigned_to is None
    assert not ModerationAuditLog.objects.filter(case=case, action="assign").exists()


def test_assigning_an_old_case_while_a_newer_one_is_open_returns_409(moderator):
    # This used to reopen the old case and hit the one-open-case index (HTTP 500).
    _, client = moderator
    target = _acct()
    old = _case(target_id=target)
    services.take_action(str(old.id), _acct(), "dismiss")
    newer = _case(target_id=target)
    assert newer.id != old.id
    assert client.post(reverse("moderation:case-assign", args=[old.id])).status_code == 409


def test_assign_unknown_case_returns_404(moderator):
    _, client = moderator
    assert client.post(reverse("moderation:case-assign", args=[uuid.uuid4()])).status_code == 404


def test_assign_requires_the_moderator_role(client_for):
    case = _case()
    assert (
        client_for(_acct()).post(reverse("moderation:case-assign", args=[case.id])).status_code
        == 403
    )
    case.refresh_from_db()
    assert case.state == ModerationCase.State.OPEN


# ---- take_action ------------------------------------------------------------


def test_second_action_returns_409_and_one_actioned_row_exists(moderator):
    _, client = moderator
    case = _case()
    url = reverse("moderation:case-action", args=[case.id])
    assert client.post(url, {"action": "remove"}, format="json").status_code == 200
    second = client.post(url, {"action": "dismiss"}, format="json")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"
    assert _actioned() == 1
    assert ModerationAction.objects.filter(case=case).count() == 1
    assert ModerationAction.objects.get(case=case).action == "remove"


def test_service_refuses_to_action_a_resolved_case():
    case = _case()
    services.take_action(str(case.id), _acct(), "remove")
    with pytest.raises(Conflict):
        services.take_action(str(case.id), _acct(), "remove")
    assert _actioned() == 1


@pytest.mark.parametrize(
    ("target_type", "action"),
    [
        ("user", "remove"),
        ("user", "approve"),
        ("page", "shadow"),
        ("page", "approve"),
        ("post", "restrict"),
        ("post", "shadow"),
        ("listing", "restrict"),
        ("message", "shadow"),
        ("comment", "restrict"),
    ],
)
def test_action_that_does_not_fit_the_target_type_returns_400(moderator, target_type, action):
    _, client = moderator
    case = _case(target_type=target_type)
    resp = client.post(
        reverse("moderation:case-action", args=[case.id]), {"action": action}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"
    case.refresh_from_db()
    assert case.state == ModerationCase.State.OPEN
    assert _actioned() == 0
    assert not ModerationAction.objects.exists()


@pytest.mark.parametrize(
    ("target_type", "action"),
    [
        ("post", "remove"),
        ("post", "approve"),
        ("post", "warn"),
        ("comment", "remove"),
        ("message", "remove"),
        ("listing", "approve"),
        ("page", "remove"),
        ("page", "restrict"),
        ("user", "restrict"),
        ("user", "shadow"),
        ("user", "warn"),
        ("user", "dismiss"),
    ],
)
def test_action_that_fits_the_target_type_is_emitted(target_type, action):
    case = _case(target_type=target_type)
    services.take_action(str(case.id), _acct(), action)
    event = OutboxEvent.objects.get(event_type="moderation.actioned")
    assert event.payload["payload"]["action"] == action
    assert event.payload["payload"]["target_type"] == target_type


def test_a_case_on_an_unlisted_target_type_can_only_be_dismissed():
    case = ModerationCase.objects.create(target_type="legacy", target_id="x")
    with pytest.raises(TaraAPIError) as exc:
        services.take_action(str(case.id), _acct(), "remove")
    assert exc.value.http_status == 400
    services.take_action(str(case.id), _acct(), "dismiss")
    assert _actioned() == 1


def test_unknown_action_and_unknown_case(moderator):
    _, client = moderator
    case = _case()
    bad = client.post(
        reverse("moderation:case-action", args=[case.id]), {"action": "nuke"}, format="json"
    )
    assert bad.status_code == 400
    missing = client.post(
        reverse("moderation:case-action", args=[uuid.uuid4()]), {"action": "remove"}, format="json"
    )
    assert missing.status_code == 404
    assert _actioned() == 0


# ---- report intake ----------------------------------------------------------


@pytest.mark.parametrize("target_type", ["post", "comment", "message", "listing", "story"])
def test_generic_report_endpoint_refuses_content_targets(client_for, target_type):
    resp = client_for(_acct()).post(
        reverse("moderation:report-file"),
        {"target_type": target_type, "target_id": _acct(), "reason": "spam"},
        format="json",
    )
    assert resp.status_code == 400
    assert not ModerationCase.objects.exists()
    assert not Report.objects.exists()


def test_generic_report_needs_a_uuid_target(client_for):
    resp = client_for(_acct()).post(
        reverse("moderation:report-file"),
        {"target_type": "user", "target_id": "not-a-uuid"},
        format="json",
    )
    assert resp.status_code == 400
    assert not ModerationCase.objects.exists()


def test_user_report_makes_the_reported_account_the_case_owner(client_for):
    reported = _acct()
    resp = client_for(_acct()).post(
        reverse("moderation:report-file"),
        {"target_type": "user", "target_id": reported, "reason": "harassment"},
        format="json",
    )
    assert resp.status_code == 202
    case = ModerationCase.objects.get(target_type="user", target_id=reported)
    assert str(case.owner_id) == reported


def test_page_report_opens_a_case_with_no_owner(client_for):
    page = _acct()
    resp = client_for(_acct()).post(
        reverse("moderation:report-file"), {"target_type": "page", "target_id": page}, format="json"
    )
    assert resp.status_code == 202
    assert ModerationCase.objects.get(target_type="page", target_id=page).owner_id is None


def test_reporting_yourself_returns_400(client_for):
    me = _acct()
    resp = client_for(me).post(
        reverse("moderation:report-file"), {"target_type": "user", "target_id": me}, format="json"
    )
    assert resp.status_code == 400
    assert not ModerationCase.objects.exists()


def test_report_throttle_limits_each_account(client_for, settings):
    settings.MODERATION_REPORT_RATE = "2/min"
    reporter = client_for(_acct())
    url = reverse("moderation:report-file")
    for _ in range(2):
        body = {"target_type": "user", "target_id": _acct()}
        assert reporter.post(url, body, format="json").status_code == 202
    third = reporter.post(url, {"target_type": "user", "target_id": _acct()}, format="json")
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "throttled"
    assert ModerationCase.objects.count() == 2
    # Another account has its own budget.
    other = client_for(_acct()).post(
        url, {"target_type": "page", "target_id": _acct()}, format="json"
    )
    assert other.status_code == 202


def test_same_reporter_twice_counts_once():
    reporter, target = _acct(), _acct()
    for _ in range(2):
        case = services.ingest_report(reporter_id=reporter, target_type="post", target_id=target)
    assert case.report_count == 1
    assert Report.objects.filter(target_id=target).count() == 1


def test_report_after_resolution_opens_a_new_case():
    reporter, target = _acct(), _acct()
    first = services.ingest_report(reporter_id=reporter, target_type="post", target_id=target)
    services.take_action(str(first.id), _acct(), "dismiss")
    second = services.ingest_report(reporter_id=reporter, target_type="post", target_id=target)
    assert second.id != first.id
    assert second.state == ModerationCase.State.OPEN
    assert second.report_count == 1


def test_first_report_race_joins_the_winners_case(monkeypatch):
    """The loser of the one-open-case index retries inside a savepoint."""
    target = _acct()
    winner = services.ingest_report(reporter_id=_acct(), target_type="post", target_id=target)
    real_lookup = services._locked_open_case
    calls = []

    def stale_then_real(target_type, target_id):
        calls.append(target_id)
        # The first lookup ran before the winner committed, so it saw nothing.
        return None if len(calls) == 1 else real_lookup(target_type, target_id)

    monkeypatch.setattr(services, "_locked_open_case", stale_then_real)
    joined = services.ingest_report(reporter_id=_acct(), target_type="post", target_id=target)

    assert len(calls) == 2  # the insert hit IntegrityError and the lookup ran again
    assert joined.id == winner.id
    assert joined.report_count == 2
    assert ModerationCase.objects.filter(target_type="post", target_id=target).count() == 1
    # The savepoint kept the surrounding transaction usable.
    assert Report.objects.filter(target_id=target).count() == 2


def test_report_gives_up_with_409_if_the_case_keeps_moving(monkeypatch):
    target = _acct()
    services.ingest_report(reporter_id=_acct(), target_type="post", target_id=target)
    monkeypatch.setattr(services, "_locked_open_case", lambda *a: None)
    with pytest.raises(Conflict):
        services.ingest_report(reporter_id=_acct(), target_type="post", target_id=target)
    assert Report.objects.filter(target_id=target).count() == 1


# ---- owner_id from report events --------------------------------------------


def test_post_reported_owner_id_is_stored_on_the_case():
    post_id, owner = _acct(), _acct()
    _post_reported({"post_id": post_id, "reporter": _acct(), "owner_id": owner, "reason": "x"})
    assert str(ModerationCase.objects.get(target_id=post_id).owner_id) == owner


def test_old_post_reported_without_owner_still_opens_a_case_and_a_later_one_fills_it():
    post_id, owner = _acct(), _acct()
    _post_reported({"post_id": post_id, "reporter": _acct(), "reason": "x"})
    case = ModerationCase.objects.get(target_id=post_id)
    assert case.owner_id is None
    _post_reported({"post_id": post_id, "reporter": _acct(), "owner_id": owner})
    case.refresh_from_db()
    assert str(case.owner_id) == owner
    assert case.report_count == 2


def test_a_later_report_never_replaces_the_owner():
    post_id, owner = _acct(), _acct()
    _post_reported({"post_id": post_id, "reporter": _acct(), "owner_id": owner})
    _post_reported({"post_id": post_id, "reporter": _acct(), "owner_id": _acct()})
    assert str(ModerationCase.objects.get(target_id=post_id).owner_id) == owner


def test_malformed_owner_id_is_ignored():
    post_id = _acct()
    _post_reported({"post_id": post_id, "reporter": _acct(), "owner_id": "nope"})
    assert ModerationCase.objects.get(target_id=post_id).owner_id is None


def test_listing_reported_owner_id_is_stored_on_the_case():
    listing_id, seller = _acct(), _acct()
    on_listing_reported(
        EventEnvelope(
            event_type="listing.reported",
            subject_id=listing_id,
            producer="marketplace-service",
            payload={
                "listing_id": listing_id,
                "reporter": _acct(),
                "owner_id": seller,
                "reason": "fake",
            },
        )
    )
    case = ModerationCase.objects.get(target_type="listing", target_id=listing_id)
    assert str(case.owner_id) == seller


def test_comment_reported_opens_a_comment_case_with_its_owner():
    comment_id, author = _acct(), _acct()
    on_comment_reported(
        EventEnvelope(
            event_type="comment.reported",
            subject_id=comment_id,
            producer="post-service",
            payload={
                "comment_id": comment_id,
                "post_id": _acct(),
                "reporter": _acct(),
                "owner_id": author,
                "reason": "spam",
            },
        )
    )
    case = ModerationCase.objects.get(target_type="comment", target_id=comment_id)
    assert str(case.owner_id) == author
    assert Report.objects.filter(target_type="comment", target_id=comment_id).count() == 1


def test_review_report_opens_a_listing_review_case_that_can_be_removed():
    review_id, buyer = _acct(), _acct()
    on_listing_review_reported(
        EventEnvelope(
            event_type="marketplace.review.reported",
            subject_id=review_id,
            producer="marketplace-service",
            payload={
                "review_id": review_id,
                "listing_id": _acct(),
                "seller_id": _acct(),
                "reporter": _acct(),
                "owner_id": buyer,
                "reason": "abuse",
            },
        )
    )
    case = ModerationCase.objects.get(target_type="listing_review", target_id=review_id)
    assert str(case.owner_id) == buyer
    assert "remove" in services.ACTIONS_BY_TARGET["listing_review"]
    assert services.REVERSALS[("listing_review", "remove")] == "approve"


@pytest.mark.parametrize(
    "payload",
    [
        {"post_id": "p-missing-reporter", "reason": "x"},
        {"post_id": "p-bad-reporter", "reporter": "nope"},
        {"reporter": str(uuid.uuid4())},  # no target
    ],
)
def test_report_event_without_reporter_or_target_is_skipped(payload):
    _post_reported(payload)  # must not raise: a retry cannot fix it
    assert not ModerationCase.objects.exists()
    assert not Report.objects.exists()


def test_long_reason_is_truncated_to_the_column():
    post_id = _acct()
    _post_reported({"post_id": post_id, "reporter": _acct(), "reason": "x" * 500})
    assert len(Report.objects.get(target_id=post_id).reason) == 200


# ---- appeals ----------------------------------------------------------------


def _resolved_case(owner: str, action: str = "remove", target_type: str = "post"):
    case = _case(target_type=target_type, owner_id=owner)
    services.take_action(str(case.id), _acct(), action)
    return case


def _appeal(client, case_id):
    return client.post(
        reverse("moderation:case-appeal", args=[case_id]), {"text": "please review"}, format="json"
    )


def test_owner_can_appeal_a_resolved_case(client_for):
    owner = _acct()
    case = _resolved_case(owner)
    resp = _appeal(client_for(owner), case.id)
    assert resp.status_code == 201
    appeal = Appeal.objects.get(case=case)
    assert str(appeal.account_id) == owner
    event = OutboxEvent.objects.get(event_type="appeal.created")
    assert event.payload["payload"] == {"case_id": str(case.id), "account_id": owner}


def test_appeal_by_anyone_but_the_owner_returns_404(client_for):
    case = _resolved_case(_acct())
    stranger = _appeal(client_for(_acct()), case.id)
    unknown = _appeal(client_for(_acct()), uuid.uuid4())
    assert stranger.status_code == 404
    # Indistinguishable from a case that does not exist.
    assert stranger.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert not Appeal.objects.exists()
    assert not OutboxEvent.objects.filter(event_type="appeal.created").exists()


def test_moderators_and_reporters_cannot_appeal_someone_elses_case(client_for):
    reporter, owner = _acct(), _acct()
    case = services.ingest_report(
        reporter_id=reporter, target_type="post", target_id=_acct(), owner_id=owner
    )
    services.take_action(str(case.id), _acct(), "remove")
    assert _appeal(client_for(reporter), case.id).status_code == 404
    assert _appeal(client_for(_acct(), roles=["moderator"]), case.id).status_code == 404
    assert not Appeal.objects.exists()


def test_case_without_a_known_owner_cannot_be_appealed_by_anyone(client_for):
    case = _case()  # an old event: no owner_id
    services.take_action(str(case.id), _acct(), "remove")
    assert _appeal(client_for(_acct()), case.id).status_code == 404
    assert not Appeal.objects.exists()


def test_open_case_cannot_be_appealed(client_for):
    owner = _acct()
    case = _case(owner_id=owner)
    resp = _appeal(client_for(owner), case.id)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"
    # A stranger does not learn the state: still 404.
    assert _appeal(client_for(_acct()), case.id).status_code == 404
    services.assign(str(case.id), _acct())
    assert _appeal(client_for(owner), case.id).status_code == 409
    assert not Appeal.objects.exists()


def test_second_appeal_returns_409(client_for):
    owner = _acct()
    case = _resolved_case(owner)
    client = client_for(owner)
    assert _appeal(client, case.id).status_code == 201
    second = _appeal(client, case.id)
    assert second.status_code == 409
    assert Appeal.objects.filter(case=case).count() == 1
    assert OutboxEvent.objects.filter(event_type="appeal.created").count() == 1


def test_case_cannot_be_appealed_again_after_the_appeal_is_resolved(client_for):
    owner = _acct()
    case = _resolved_case(owner)
    services.file_appeal(str(case.id), owner, "first")
    services.resolve_appeal(str(Appeal.objects.get().id), _acct(), "upheld")
    assert _appeal(client_for(owner), case.id).status_code == 409


@pytest.mark.parametrize("action", ["dismiss", "approve"])
def test_decision_that_took_no_action_cannot_be_appealed(client_for, action):
    owner = _acct()
    case = _resolved_case(owner, action=action)
    assert _appeal(client_for(owner), case.id).status_code == 409
    assert not Appeal.objects.exists()


def test_reported_user_can_appeal_their_restriction(client_for):
    reported = _acct()
    client_for(_acct()).post(
        reverse("moderation:report-file"),
        {"target_type": "user", "target_id": reported},
        format="json",
    )
    case = ModerationCase.objects.get(target_type="user", target_id=reported)
    services.take_action(str(case.id), _acct(), "restrict")
    assert _appeal(client_for(reported), case.id).status_code == 201


def test_resolving_an_appeal_twice_returns_409_and_emits_one_reversal(client_for):
    owner = _acct()
    case = _resolved_case(owner)
    appeal = services.file_appeal(str(case.id), owner, "please")
    mod = client_for(_acct(), roles=["moderator"])
    url = reverse("moderation:appeal-resolve", args=[appeal.id])
    assert mod.post(url, {"status": "overturned"}, format="json").status_code == 200
    again = mod.post(url, {"status": "overturned"}, format="json")
    assert again.status_code == 409
    assert _actioned() == 2  # the removal and one reversal
    appeal.refresh_from_db()
    assert appeal.status == Appeal.Status.OVERTURNED


# ---- what an overturn sends back ----------------------------------------------


def _actions_emitted() -> list[str]:
    rows = OutboxEvent.objects.filter(event_type="moderation.actioned").order_by("created_at", "id")
    return [r.payload["payload"]["action"] for r in rows]


def _overturn(case: ModerationCase, owner: str) -> Appeal:
    appeal = services.file_appeal(str(case.id), owner, "please")
    return services.resolve_appeal(str(appeal.id), _acct(), "overturned")


def _decided(target_id: str, owner: str, action: str) -> ModerationCase:
    """A new case on the same target, resolved with ``action``."""
    case = _case(target_id=target_id, owner_id=owner)
    services.take_action(str(case.id), _acct(), action)
    return case


def _overturn_audit(case: ModerationCase) -> dict:
    return ModerationAuditLog.objects.get(case=case, action="appeal:overturned").after


@pytest.mark.parametrize("target_type", ["post", "comment", "message", "listing"])
def test_overturning_a_content_removal_emits_approve(target_type):
    owner = _acct()
    case = _resolved_case(owner, action="remove", target_type=target_type)
    _overturn(case, owner)
    assert _actions_emitted() == ["remove", "approve"]
    reversal = OutboxEvent.objects.filter(event_type="moderation.actioned").last()
    assert reversal.payload["payload"] == {
        "case_id": str(case.id),
        "target_type": target_type,
        "target_id": case.target_id,
        "action": "approve",
    }
    assert _overturn_audit(case) == {"status": "overturned", "reversal": "approve"}


@pytest.mark.parametrize(
    ("target_type", "action"),
    [
        ("post", "warn"),
        ("listing", "warn"),
        ("user", "warn"),
        ("user", "restrict"),
        ("user", "shadow"),
        ("page", "remove"),
        ("page", "restrict"),
    ],
)
def test_overturning_a_decision_without_an_inverse_emits_nothing(target_type, action):
    # Approve is not an inverse of these: on a post it would restore content
    # another case removed, and users and pages do not understand it at all.
    owner = _acct()
    case = _resolved_case(owner, action=action, target_type=target_type)
    appeal = _overturn(case, owner)
    assert appeal.status == Appeal.Status.OVERTURNED
    assert _actions_emitted() == [action]
    assert _overturn_audit(case) == {"status": "overturned", "reversal": None}


def test_overturning_a_warning_does_not_restore_a_later_removal():
    # The reviewer's probe: case 1 warns, case 2 removes, case 1 is overturned.
    owner, post = _acct(), _acct()
    warned = _decided(post, owner, "warn")
    _decided(post, owner, "remove")
    _overturn(warned, owner)
    assert _actions_emitted() == ["warn", "remove"]
    assert "approve" not in _actions_emitted()


@pytest.mark.parametrize("overturn_first", ["earlier", "later"])
def test_removal_stays_while_another_cases_removal_stands(overturn_first):
    # Two cases removed the same post (a late report). Undoing one of them
    # must not restore the post; undoing both does, exactly once.
    owner, post = _acct(), _acct()
    earlier = _decided(post, owner, "remove")
    later = _decided(post, owner, "remove")
    first, second = (earlier, later) if overturn_first == "earlier" else (later, earlier)

    _overturn(first, owner)
    assert _actions_emitted() == ["remove", "remove"]
    assert _overturn_audit(first) == {
        "status": "overturned",
        "reversal": None,
        "kept_by_case": str(second.id),
    }

    _overturn(second, owner)
    assert _actions_emitted() == ["remove", "remove", "approve"]
    assert _overturn_audit(second) == {"status": "overturned", "reversal": "approve"}


def test_upheld_appeal_on_another_case_keeps_its_removal_standing():
    owner, post = _acct(), _acct()
    kept = _decided(post, owner, "remove")
    appeal = services.file_appeal(str(kept.id), owner, "please")
    services.resolve_appeal(str(appeal.id), _acct(), "upheld")
    undone = _decided(post, owner, "remove")
    _overturn(undone, owner)
    assert "approve" not in _actions_emitted()
    assert _overturn_audit(undone)["kept_by_case"] == str(kept.id)


def test_a_removal_a_moderator_already_approved_no_longer_stands():
    # remove (case A), approve (case B) restored the post, remove (case C).
    # Overturning C goes back to B's approval, so the post is restored.
    owner, post = _acct(), _acct()
    _decided(post, owner, "remove")
    _decided(post, owner, "approve")
    removed = _decided(post, owner, "remove")
    _overturn(removed, owner)
    assert _actions_emitted() == ["remove", "approve", "remove", "approve"]


def test_removal_on_another_target_does_not_block_the_reversal():
    owner = _acct()
    _decided(_acct(), owner, "remove")  # a different post of the same owner
    case = _decided(_acct(), owner, "remove")
    _overturn(case, owner)
    assert _actions_emitted() == ["remove", "remove", "approve"]


def test_upheld_appeal_emits_nothing_and_is_audited():
    owner = _acct()
    case = _resolved_case(owner)
    appeal = services.file_appeal(str(case.id), owner, "please")
    services.resolve_appeal(str(appeal.id), _acct(), "upheld")
    assert _actions_emitted() == ["remove"]
    audit = ModerationAuditLog.objects.get(case=case, action="appeal:upheld")
    assert audit.after == {"status": "upheld"}


def test_resolve_unknown_appeal_returns_404(client_for):
    mod = client_for(_acct(), roles=["moderator"])
    resp = mod.post(
        reverse("moderation:appeal-resolve", args=[uuid.uuid4()]),
        {"status": "upheld"},
        format="json",
    )
    assert resp.status_code == 404
