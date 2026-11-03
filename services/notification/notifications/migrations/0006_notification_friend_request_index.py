"""Index friend-request rows by request id (``services.resolve_friend_request``).

Graph names the request, not the recipient, so without it every accept or
withdrawal scanned the whole table. Built CONCURRENTLY, like 0005.
"""

import django.db.models.fields.json
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("notifications", "0005_notification_v2_indexes"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="notification",
            index=models.Index(
                django.db.models.fields.json.KeyTransform("request_id", "data"),
                condition=models.Q(("kind", "friend.request")),
                name="notif_friend_request_idx",
            ),
        ),
    ]
