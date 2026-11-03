"""Admin beat tasks: service health and platform statistics (roadmap 8.11)."""

from __future__ import annotations

from celery import shared_task

from . import services


@shared_task(name="adminsvc.poll_service_health", ignore_result=True)
def poll_service_health() -> int:
    return len(services.poll_service_health())


@shared_task(name="adminsvc.poll_platform_stats", ignore_result=True)
def poll_platform_stats() -> int:
    return len(services.poll_platform_stats())
