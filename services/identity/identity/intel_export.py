"""Account lifecycle export for Tara Intelligence (WP 3.2 / 3.3), under
``/internal/v1/intel/export/accounts/``.

feed (``author_ref``, rule E6) and graph (``AccountRef.active``, D5) learn that an
account is deactivated or suspended from ``account.deactivated`` /
``account.suspended``. An account that was already inactive before they consumed
those events stays "active" for them until its next event. This export lets each
of them backfill once (and after missed events): it lists **only the accounts that
are not active today**, so a complete scan also tells the reader that every
account it does not list is active.

Each item is ``{account_id, deactivated, suspended}``: the two flags are kept apart
the way the events keep them (a suspended account that was deactivated before the
suspension goes back to deactivated when it is lifted). Ids and booleans only, the
same facts every consumer of the account events already receives on the bus; no
reason, date or actor. Never routed by the edge; an internal token for
``identity-internal`` is required (``SearchExportView``).
"""

from __future__ import annotations

from django.db.models import Prefetch
from django.urls import path

from tara_common.search_export import SearchExportView

from .models import Account, AccountSuspension

INACTIVE = (Account.Status.DEACTIVATED, Account.Status.SUSPENDED)


def _accounts():
    return Account.objects.filter(status__in=INACTIVE).prefetch_related(
        Prefetch(
            "suspensions",
            queryset=AccountSuspension.objects.filter(lifted_at__isnull=True),
            to_attr="open_suspensions",
        )
    )


def account_item(account: Account) -> tuple:
    suspended = account.status == Account.Status.SUSPENDED
    if suspended:
        open_ = account.open_suspensions
        deactivated = bool(open_) and open_[0].previous_status == Account.Status.DEACTIVATED
    else:
        deactivated = account.status == Account.Status.DEACTIVATED
    return account.id, {
        "account_id": str(account.id),
        "deactivated": deactivated,
        "suspended": suspended,
    }


urlpatterns = [
    path(
        "export/accounts/",
        SearchExportView.as_view(source=_accounts, to_item=account_item),
        name="intel-export-accounts",
    ),
]
