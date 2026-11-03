"""Copy the pre-8.1 admin audit rows into the unified audit log.

``AuditLog`` held only admin's own role grants and flag changes, without a
request id. The copy keeps their ids (uuid7), so running it twice is harmless,
and leaves the old table in place (additive).
"""

from django.db import migrations

_ACTIONS = {
    "role.grant": ("role.granted", "account"),
    "role.revoke": ("role.revoked", "account"),
    "feature_flag.set": ("feature_flag.changed", "feature_flag"),
}
_DETAIL_KEYS = ("role", "enabled", "rollout_pct")


def copy_legacy(apps, schema_editor):
    AuditLog = apps.get_model("adminsvc", "AuditLog")
    AuditEntry = apps.get_model("adminsvc", "AuditEntry")
    existing = set(AuditEntry.objects.values_list("id", flat=True))
    rows = []
    for old in AuditLog.objects.order_by("created_at").iterator(chunk_size=500):
        if old.id in existing:
            continue
        action, target_type = _ACTIONS.get(old.action, (old.action[:64], ""))
        metadata = old.metadata if isinstance(old.metadata, dict) else {}
        rows.append(
            AuditEntry(
                id=old.id,
                occurred_at=old.created_at,
                actor_kind="account",
                actor_id=old.actor_id,
                action=action,
                target_type=target_type,
                target_id=(old.target or "")[:64],
                detail={k: metadata[k] for k in _DETAIL_KEYS if k in metadata},
            )
        )
        if len(rows) >= 500:
            AuditEntry.objects.bulk_create(rows)
            rows = []
    if rows:
        AuditEntry.objects.bulk_create(rows)


class Migration(migrations.Migration):
    dependencies = [
        ("adminsvc", "0003_platformstat_auditentry_outboxevent_processedevent"),
    ]

    operations = [migrations.RunPython(copy_legacy, migrations.RunPython.noop)]
