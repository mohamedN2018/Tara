"""Tara Intelligence WP 2.6 (D9): the highest-volume post events have JSON Schemas.

Each event is produced through the real service path and its payload is
validated against ``libs/tara_events/tara_events/schemas/<type>.v1.json``, so a
payload change that is not reflected in the schema fails here.
"""

import uuid

import pytest

from posts import services
from posts.models import OutboxEvent

from .event_schema import assert_all_valid

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def produced(media_stub):
    author, fan, other = _acct(), _acct(), _acct()
    photo = media_stub.add(author)
    post = services.create_post(
        author,
        body="hello #tara #مرحبا @someone " + "x" * 400,
        media_ids=[photo],
        post_type="image",
        tagged_ids=[],
    )
    services.create_post(author, body="plain")  # no media, no tags
    services.edit_post(author, str(post.id), body="edited #tara @other_one")
    services.edit_post(author, str(post.id), audience="friends", comment_policy="friends")
    services.edit_post(author, str(post.id), audience="public", comment_policy="everyone")
    services.react(fan, str(post.id), "like")
    services.react(fan, str(post.id), "love")
    services.unreact(fan, str(post.id))
    root = services.add_comment(fan, str(post.id), "first @someone")
    services.add_comment(other, str(post.id), "reply", reply_to_id=str(root.id))
    services.share(other, str(post.id), body="look")
    doomed = services.create_post(author, body="gone soon")
    services.delete_post(author, str(doomed.id))
    removed = services.create_post(author, body="removed by moderation")
    services.apply_moderation(str(removed.id), "remove")
    return post


@pytest.mark.parametrize(
    "event_type",
    [
        "post.created",
        "post.updated",
        "post.deleted",
        "post.reacted",
        "post.unreacted",
        "post.reaction.changed",
        "post.commented",
        "comment.replied",
        "post.shared",
    ],
)
def test_every_emitted_payload_matches_its_schema(produced, event_type):
    assert OutboxEvent.objects.filter(event_type=event_type).exists(), event_type
    assert assert_all_valid(event_type) >= 1


def test_a_schema_change_is_caught(produced):
    """The schemas are strict: an unknown field is a contract change (a new version)."""
    import jsonschema

    from .event_schema import assert_valid, payloads

    payload = {**payloads("post.reacted")[0], "surprise": 1}
    with pytest.raises(jsonschema.ValidationError):
        assert_valid("post.reacted", payload)


def test_every_schema_in_the_library_is_a_valid_json_schema():
    """libs/tara_events schema check: each file parses, is a valid schema for its
    ``$schema`` dialect, and is named after the event it describes."""
    import json

    import jsonschema

    from .event_schema import SCHEMAS

    if not SCHEMAS.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    files = sorted(SCHEMAS.glob("*.json"))
    assert files
    for path in files:
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.validators.validator_for(schema).check_schema(schema)
        assert path.name.endswith(".v1.json") or ".v" in path.name, path.name
        if "$id" in schema:
            assert schema["$id"].endswith(path.name), path.name
