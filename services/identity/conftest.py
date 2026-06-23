"""Pytest configuration for the Identity service.

Generates an ephemeral RS256 keypair for the test session (so token issuance
works without on-disk keys), and isolates tests from external infra (locmem
cache + email, eager Celery, null event publisher).
"""

import pytest
from identity.keys import generate_keypair

# One keypair for the whole test run.
_PRIVATE_PEM, _PUBLIC_PEM = generate_keypair()


@pytest.fixture(autouse=True)
def _isolated_settings(settings):
    settings.JWT_PRIVATE_KEY = _PRIVATE_PEM
    settings.JWT_PUBLIC_KEY = _PUBLIC_PEM
    settings.TARA_JWT_PUBLIC_KEY = _PUBLIC_PEM
    settings.TARA_EVENT_PUBLISHER = "null"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    return settings


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def active_account(db):
    from identity.models import Account

    account = Account.objects.create_user(
        email="active@tara.local",
        password="DevPassw0rd!",
        status=Account.Status.ACTIVE,
        email_verified=True,
    )
    return account
