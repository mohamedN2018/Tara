"""R4 HTTP endpoints: feedback, topics, My Algorithm (04 WP 6.4, 6.6, 7.1, 8.1; 07 WP
7.5-B2, 8.4-B2, 8.5-B2, 8.7-B2). Every body is ``{data: ...}``; anything the caller
may not see is one identical 404 (fail closed). All under ``/api/v1/feed/``, served
by the ``feed`` service (no new route reaches ``feed-signals``).
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError

from . import config, feedback, interests, preferences
from .models import Topic, UserInterest
from .topics import classify


class _AccountThrottle(UserRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.account_id}


class FeedbackThrottle(_AccountThrottle):
    """120 feedback writes per minute per account (``intel_feedback`` in settings)."""

    scope = "intel_feedback"


def _error(exc) -> TaraAPIError:
    code = getattr(exc, "code", "invalid")
    return TaraAPIError(str(exc), code=code, http_status_code=400)


# ---- feedback -------------------------------------------------------------------------


class FeedbackSerializer(serializers.Serializer):
    item_type = serializers.ChoiceField(choices=feedback.ITEM_TYPES)
    item_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=feedback.ACTIONS)
    topic = serializers.CharField(required=False, allow_blank=True, max_length=40)
    surface = serializers.CharField(required=False, allow_blank=True, max_length=12)
    st = serializers.CharField(required=False, allow_blank=True, max_length=512)


class FeedbackView(APIView):
    """``POST /api/v1/feed/feedback/``: one action on an item the viewer was served
    (or has on their own feed). 201 with the row; a live repeat is 200 with the same
    row. ``hide_creator`` with ``item_type=profile`` takes the account id."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [FeedbackThrottle]

    @extend_schema(request=FeedbackSerializer, responses={201: OpenApiTypes.OBJECT}, tags=["intel"])
    def post(self, request):
        body = FeedbackSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        v = body.validated_data
        if v["item_type"] in ("profile", "page") and v["action"] != "hide_creator":
            raise ValidationError({"action": ["Only hide_creator applies to a profile or page."]})
        if v["action"] == "mute_topic" and not v.get("topic"):
            raise ValidationError({"topic": ["Required for mute_topic."]})
        item = feedback.resolve_item(
            request.user.claims, v["item_type"], v["item_id"], v.get("st") or None
        )
        if item is None:
            raise NotFound()
        try:
            row, created = feedback.act(
                request.user.account_id,
                item,
                v["action"],
                topic_slug=v.get("topic") or None,
                surface=v.get("surface") or "",
            )
        except feedback.FeedbackError as exc:
            raise _error(exc) from exc
        return Response(
            {"data": feedback.body(row)},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class FeedbackUndoView(APIView):
    """``DELETE /api/v1/feed/feedback/{id}/``: the exact undo; 404 if not the caller's."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [FeedbackThrottle]

    @extend_schema(responses={204: None, 404: OpenApiTypes.OBJECT}, tags=["intel"])
    def delete(self, request, action_id):
        if not feedback.undo(request.user.account_id, action_id):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- topics -----------------------------------------------------------------------------


class TopicsView(APIView):
    """``GET /api/v1/feed/topics/?q=&limit=``: active topics (the picker, My Algorithm).
    ``q`` matches the slug or either label, normalized (``tara_common.text``)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["intel"])
    def get(self, request):
        from tara_common.text import normalize_ar

        q = normalize_ar(request.query_params.get("q") or "")
        try:
            limit = max(1, min(int(request.query_params.get("limit") or 50), 100))
        except ValueError:
            limit = 50
        rows = []
        for t in sorted(classify.load_aliases().topics.values(), key=lambda x: x["slug"]):
            hay = " ".join((t["slug"], normalize_ar(t["label_ar"]), normalize_ar(t["label_en"])))
            if q and q not in hay:
                continue
            rows.append(
                {
                    "slug": t["slug"],
                    "label_ar": t["label_ar"],
                    "label_en": t["label_en"],
                    "sensitive": t["sensitive"],
                }
            )
        return Response({"data": rows[:limit]})


# ---- preferences ----------------------------------------------------------------------


def _conflict(exc):
    return TaraAPIError("Preferences changed elsewhere.", code="conflict", http_status_code=409)


class PreferencesView(APIView):
    """``GET/PATCH /api/v1/feed/preferences/`` (04 WP 8.1). PATCH takes any subset of
    the editable fields plus ``version``; a stale ``version`` is 409. The reply is the
    whole body plus ``change_id`` (null when nothing changed), for ``undo``."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["intel"])
    def get(self, request):
        return Response({"data": preferences.body(preferences.get(request.user.account_id))})

    @extend_schema(
        request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT}, tags=["intel"]
    )
    def patch(self, request):
        data = dict(request.data or {})
        version = data.pop("version", None)
        if not data:
            raise ValidationError({"detail": ["Nothing to change."]})
        if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
            raise ValidationError({"version": ["An integer."]})
        try:
            row, change = preferences.patch(request.user.account_id, data, expected_version=version)
        except preferences.StaleVersion as exc:
            raise _conflict(exc) from exc
        except preferences.PreferenceError as exc:
            raise _error(exc) from exc
        out = preferences.body(row)
        out["change_id"] = str(change.id) if change is not None else None
        return Response({"data": out})


class PreferencesUndoView(APIView):
    """``POST /api/v1/feed/preferences/undo/ {change_id}``: 404 when not the caller's."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT}, tags=["intel"]
    )
    def post(self, request):
        try:
            change_id = uuid.UUID(str((request.data or {}).get("change_id")))
        except ValueError as exc:
            raise NotFound() from exc
        found = preferences.undo(request.user.account_id, change_id)
        if found is None:
            raise NotFound()
        row, change = found
        out = preferences.body(row)
        out["change_id"] = str(change.id) if change is not None else None
        return Response({"data": out})


class OnboardingView(APIView):
    """``POST /api/v1/feed/preferences/onboarding/ {topics: [slug <= 10], skipped}``."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT}, tags=["intel"]
    )
    def post(self, request):
        data = request.data or {}
        topics = data.get("topics") or []
        if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
            raise ValidationError({"topics": ["A list of topic slugs."]})
        try:
            row, _ = preferences.onboard(request.user.account_id, topics, bool(data.get("skipped")))
        except preferences.PreferenceError as exc:
            raise _error(exc) from exc
        return Response({"data": preferences.body(row)})


class ResetView(APIView):
    """``POST /api/v1/feed/preferences/reset/``: ``{}`` gives a confirm token, the scope
    and what is kept (200); ``{confirm_token}`` resets (202), or 429 with
    ``Retry-After`` within ``reset.min_interval_h``."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT}, tags=["intel"]
    )
    def post(self, request):
        token = (request.data or {}).get("confirm_token")
        account = request.user.account_id
        if not token:
            return Response({"data": preferences.reset_request(account)})
        try:
            out = preferences.reset_confirm(account, str(token))
        except preferences.PreferenceError as exc:
            if exc.code == "throttled":
                resp = Response(
                    {"error": {"code": "throttled", "message": str(exc)}},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
                resp["Retry-After"] = str(exc.retry_after or 1)
                return resp
            raise _error(exc) from exc
        return Response({"data": out}, status=status.HTTP_202_ACCEPTED)


class DebugConsentView(APIView):
    """``POST`` grants support a 24 h look at the viewer's ranking (decision 17);
    ``DELETE`` revokes it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={201: OpenApiTypes.OBJECT}, tags=["intel"])
    def post(self, request):
        row = preferences.grant_consent(request.user.account_id)
        return Response(
            {
                "data": {
                    "granted_at": row.granted_at.isoformat(),
                    "expires_at": row.expires_at.isoformat(),
                }
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses={204: None}, tags=["intel"])
    def delete(self, request):
        preferences.revoke_consent(request.user.account_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- the interest profile (04 WP 6.4, 07 WP 8.5-B2) -------------------------------------

DIM_KEYS = ("topic", "format", "creator", "lang", "market_cat", "group_cat")


def _topic_id(slug: str) -> int | None:
    return Topic.objects.filter(slug=slug, status="active").values_list("id", flat=True).first()


class ProfileView(APIView):
    """``GET /api/v1/feed/preferences/profile/``: the viewer's own interest rows by tier,
    with counts by event type (no item ids), muted topics and hidden creators.
    ``POST {dim: "topic", key: slug, polarity: like|dislike|muted}``: an explicit row."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["intel"])
    def get(self, request):
        account = request.user.account_id
        block = config.for_surface("home").section("interests")
        out = interests.profile_view(account, timezone.now(), block)
        out["sensitive_inference"] = bool(preferences.get(account).sensitive_inference)
        return Response({"data": out})

    @extend_schema(
        request=OpenApiTypes.OBJECT, responses={201: OpenApiTypes.OBJECT}, tags=["intel"]
    )
    def post(self, request):
        data = request.data or {}
        if data.get("dim") != "topic":
            raise ValidationError({"dim": ["Only topic rows can be added."]})
        polarity = data.get("polarity")
        if polarity not in interests.API_POLARITIES:
            raise ValidationError({"polarity": ["like, dislike or muted."]})
        topic_id = _topic_id(str(data.get("key") or ""))
        if topic_id is None:
            raise ValidationError({"key": ["Unknown topic."]})
        account = request.user.account_id
        now = timezone.now()
        with transaction.atomic():
            interests.set_explicit(account, "topic", str(topic_id), polarity, now)
        t = classify.load_aliases().topics.get(topic_id, {})
        row = {
            "dim": "topic",
            "key": t.get("slug"),
            "label_ar": t.get("label_ar"),
            "label_en": t.get("label_en"),
            "polarity": polarity,
            "source": "explicit",
            "counts": {},
            "updated_at": now.isoformat(),
        }
        return Response({"data": row}, status=status.HTTP_201_CREATED)


class ProfileRowView(APIView):
    """``DELETE /api/v1/feed/preferences/profile/{dim}/{key}/``: removes an explicit row
    (an unmute, an unhide), suppresses an inferred one. 404 when nothing matches."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None, 404: OpenApiTypes.OBJECT}, tags=["intel"])
    def delete(self, request, dim: str, key: str):
        if dim not in DIM_KEYS:
            raise NotFound()
        account = request.user.account_id
        stored = key
        if dim == "topic":
            topic_id = _topic_id(key)
            if topic_id is None:
                raise NotFound()
            stored = str(topic_id)
        hidden_before = (
            dim == "creator"
            and UserInterest.objects.filter(
                account_id=account, dim="creator", key=stored, source="explicit", polarity="hidden"
            ).exists()
        )
        with transaction.atomic():
            if not interests.remove(account, dim, stored):
                raise NotFound()
            if hidden_before:
                feedback._emit_creator_hidden(account, stored, False, timezone.now())  # noqa: SLF001
        return Response(status=status.HTTP_204_NO_CONTENT)
