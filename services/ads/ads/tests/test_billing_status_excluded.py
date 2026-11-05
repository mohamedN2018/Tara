"""WP 4.11 (D13): a creative serves only while its advertiser's billing is ``active``.

An approved creative in an active, in-schedule, in-budget campaign is refused when
its advertiser is suspended, unfunded or in any other non-active state; the
``ads.E001`` boot check stays until verified funding ships.
"""

import pytest

from ads import checks, services
from ads.models import AdvertiserAccount
from ads.tests.test_ads import _acct, _make_active_creative

pytestmark = pytest.mark.django_db

NON_ACTIVE = ["suspended", "unfunded", "past_due", "pending", "closed", "Active", " active", ""]


def _set_billing(owner: str, status: str) -> None:
    AdvertiserAccount.objects.filter(owner_account_id=owner).update(billing_status=status)


def test_active_advertiser_still_serves():
    owner = _acct()
    _, creative = _make_active_creative(owner)
    assert AdvertiserAccount.objects.get(owner_account_id=owner).billing_status == "active"
    assert list(services.eligible_creatives("feed")) == [creative]
    slot = services.pick_for_viewer(_acct(), "feed")
    assert slot is not None and slot["creative_id"] == str(creative.id)


@pytest.mark.parametrize("status", NON_ACTIVE)
def test_non_active_billing_never_serves(status):
    owner = _acct()
    _make_active_creative(owner)
    _set_billing(owner, status)
    assert list(services.eligible_creatives("feed")) == []
    assert services.pick_for_viewer(_acct(), "feed") is None


def test_only_the_unpaid_advertiser_is_dropped():
    paying, unpaid = _acct(), _acct()
    _, kept = _make_active_creative(paying)
    _make_active_creative(unpaid)
    _set_billing(unpaid, "suspended")
    assert list(services.eligible_creatives("feed")) == [kept]
    for _ in range(3):  # whatever the frequency cap leaves, never the unpaid one
        slot = services.pick_for_viewer(_acct(), "feed")
        assert slot is not None and slot["creative_id"] == str(kept.id)


def test_reactivated_billing_serves_again():
    owner = _acct()
    _, creative = _make_active_creative(owner)
    _set_billing(owner, "suspended")
    assert services.pick_for_viewer(_acct(), "feed") is None
    _set_billing(owner, "active")
    assert services.pick_for_viewer(_acct(), "feed")["creative_id"] == str(creative.id)


def test_billing_check_does_not_lift_the_boot_check(settings):
    # The billing filter is not payment verification: ads.E001 still blocks
    # serving in production until verified funding ships (roadmap 6.3).
    settings.TARA_ENV, settings.ADS_SERVING_ENABLED = "production", True
    assert checks.PAYMENT_VERIFICATION_AVAILABLE is False
    assert [m.id for m in checks.check_serving_switch()] == ["ads.E001"]


@pytest.mark.parametrize("kind", ["impression", "click"])
def test_non_active_billing_records_no_billable_event(kind):
    """An ad rendered before its advertiser was suspended is not billed afterwards."""
    from ads.models import AdClickEvent, AdImpressionEvent, Campaign
    from tara_common.exceptions import TaraAPIError

    owner = _acct()
    campaign, creative = _make_active_creative(owner)
    spent = Campaign.objects.get(id=campaign.id).spent
    _set_billing(owner, "suspended")
    with pytest.raises(TaraAPIError) as exc:
        services.record_event(kind, str(creative.id), _acct())
    assert exc.value.http_status == 409
    assert AdImpressionEvent.objects.count() == 0 and AdClickEvent.objects.count() == 0
    assert Campaign.objects.get(id=campaign.id).spent == spent
