from django.urls import include, path

from tara_common import health

# Gateway has no DB — readiness only checks the cache/channel-layer backend.
health.register_readiness_check("cache", health.cache_check())

urlpatterns = [
    path("healthz/", health.liveness, name="liveness"),
    path("readyz/", health.readiness, name="readiness"),
    path("startupz/", health.readiness, name="startup"),
    path("", include("django_prometheus.urls")),
]
