"""A complete sign-up body (1D), for tests that register through the API."""

from __future__ import annotations

from datetime import date

from django.conf import settings


def adult_birth_date(years: int = 30) -> str:
    today = date.today()
    return today.replace(year=today.year - years, day=min(today.day, 28)).isoformat()


def signup_data(email: str, password: str, **fields) -> dict:
    return {
        "email": email,
        "password": password,
        "password_confirm": password,
        "first_name": "Test",
        "last_name": "Person",
        "date_of_birth": adult_birth_date(),
        "accept_terms": True,
        "terms_version": settings.LEGAL_TERMS_VERSION,
        "privacy_version": settings.LEGAL_PRIVACY_VERSION,
        **fields,
    }
