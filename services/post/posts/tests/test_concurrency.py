"""Races run as two real transactions on two connections.

The first transaction does its work and stays open; the second starts and has
to wait on the first's row lock; then the first commits.
"""

import threading
import time
import uuid

import pytest
from django.db import connection, transaction

from posts import services
from posts.models import OutboxEvent, Post
from tara_common.exceptions import TaraAPIError

pytestmark = pytest.mark.django_db(transaction=True)

WAIT = 15  # seconds; generous, so a slow CI box does not flake


def _race(first, second, hold: float = 0.5) -> dict:
    """Run ``first`` in an open transaction, then ``second``; commit ``first`` after ``hold``."""
    first_done, release = threading.Event(), threading.Event()
    out: dict = {"errors": []}

    def run_first():
        try:
            with transaction.atomic():
                out["first"] = first()
                first_done.set()
                release.wait(WAIT)
        except Exception as exc:  # noqa: BLE001 - reported by the assertions
            out["errors"].append(exc)
            first_done.set()
        finally:
            connection.close()

    def run_second():
        try:
            first_done.wait(WAIT)
            out["second"] = second()
        except Exception as exc:  # noqa: BLE001 - reported by the assertions
            out["second_error"] = exc
        finally:
            connection.close()

    t1 = threading.Thread(target=run_first)
    t2 = threading.Thread(target=run_second)
    t1.start()
    assert first_done.wait(WAIT)
    t2.start()
    time.sleep(hold)  # the second is now blocked on the first's uncommitted row
    release.set()
    t1.join(WAIT)
    t2.join(WAIT)
    assert not t1.is_alive() and not t2.is_alive(), "a transaction never finished"
    assert not out["errors"], out["errors"]
    return out


def test_two_concurrent_deletes_of_a_share_decrement_the_original_once():
    author, sharer, other = (str(uuid.uuid4()) for _ in range(3))
    original = services.create_post(author, body="original")
    share = services.share(sharer, str(original.id))
    services.share(other, str(original.id))
    assert Post.objects.get(id=original.id).share_count == 2

    def delete():
        return services.delete_post(sharer, str(share.id))

    out = _race(delete, delete)
    assert isinstance(out.get("second_error"), TaraAPIError)
    assert out["second_error"].http_status == 404
    assert Post.objects.get(id=original.id).share_count == 1
    deleted = OutboxEvent.objects.filter(event_type="post.deleted")
    assert [e.payload["payload"]["post_id"] for e in deleted] == [str(share.id)]
