"""Feed API: the viewer's home feed in four modes, plus hide and snooze (2A, 1.7).

Every post-menu action handled here also writes one Tara Intelligence signal row
(``source=server``) in the request's transaction (WP 2.5); undoing it writes the
inverse row. Items carry ``st``, a serve token that attributes telemetry (WP 2.3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from intel import age, clock, config, discovery, experiments, exposure, intent, session_ctx
from intel import head as first_page_head
from intel import metrics as intel_metrics
from intel.models import EventType, ItemType
from intel.ranking import exposure_rank, serve_tokens
from intel.ranking.personal import Personal
from intel.signals.server import record as menu_signal
from intel.topics import attach as topic_attach
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination, KeysetCursorPagination
from tara_common.responses import data_response

from . import feedback, ranking, services
from .models import AuthorSnooze, PostHide
from .serializers import (
    AuthorSnoozeSerializer,
    FeedItemSerializer,
    HideRequestSerializer,
    PostHideSerializer,
    SnoozeRequestSerializer,
)
from .throttles import FeedFirstPageThrottle, FeedPeekThrottle

# How the client reached this first page (06 section 4.2, 08 section 7.6): a hint for
# the visit classifier (``intel.session_ctx``), never for eligibility. The R3 names plus
# the R2 ones the web already sends (``open`` = ``nav``, ``refresh`` = ``pull``).
ENTRIES = session_ctx.ENTRIES


def _delivery_size(request) -> int:
    """The page size of a non-peek page (08 section 7.2, WP 4c.2-B3): ``limit`` when
    sent (1 to ``max_page_size``), else ``delivery.first_page_size`` without a cursor
    and ``delivery.page_size`` with one, from the Home config."""
    raw = request.query_params.get("limit")
    if raw:
        try:
            return max(1, min(int(raw), CursorPagination.max_page_size))
        except ValueError:
            pass
    key = "page_size" if request.query_params.get("cursor") else "first_page_size"
    return int(config.for_surface("home").get(f"delivery.{key}"))


class FeedCursorPagination(KeysetCursorPagination):
    """The chronological modes: a keyset over ``(post_created_at, id)`` (WP 4c.8-B3)."""

    key_field = "post_created_at"
    ordering = "-post_created_at"

    def get_page_size(self, request) -> int:
        return _delivery_size(request)


class SnoozeCursorPagination(CursorPagination):
    ordering = "-snoozed_at"


def _mode(request) -> str:
    """The mode to serve: ``?mode=``, else the remembered one, else ``mode_hint``
    (the client's offline fallback), else the default (WP 4.6). Resolved once."""
    cached = getattr(request, "_feed_mode", None)
    if cached:
        return cached
    asked = request.query_params.get("mode") or None
    if asked is not None and asked not in services.MODES:
        raise ValidationError({"mode": [f"Must be one of: {', '.join(services.MODES)}."]})
    # Precedence of ``preferences.resolve_mode`` (WP 4.6), on the one preference row
    # the request reads anyway (R3 A8: the remembered mode and personalization_off).
    hint = request.query_params.get("mode_hint")
    mode = (
        asked
        or _preference_row(request)[0]
        or (hint if hint in services.MODES else None)
        or services.DEFAULT_MODE
    )
    request._feed_mode = mode
    return mode


def _since(request):
    raw = request.query_params.get("since")
    if not raw:
        return None
    when = parse_datetime(raw)
    if when is None:
        try:
            when = datetime.fromtimestamp(float(raw), tz=UTC)
        except (OverflowError, ValueError) as exc:
            raise ValidationError({"since": ["An ISO 8601 time or epoch seconds."]}) from exc
    if timezone.is_naive(when):
        when = timezone.make_aware(when, UTC)
    return when


def ad_slots() -> list[int]:
    """Home ad positions from the config (``ads.slots``, default ``[4]``, decision 14):
    distinct, non-negative indexes, in order. They place ads; they never move organic items."""
    slots = config.for_surface("home").get("ads.slots")
    return sorted({int(i) for i in slots if isinstance(i, int) and i >= 0})


def sponsored_for_slots(viewer, slots: list[int]) -> list[dict]:
    """One sponsored object per slot at most, never the same creative twice."""
    from .ads_client import feed_sponsored

    picked: list[dict] = []
    for _ in slots:
        ad = feed_sponsored(viewer)
        if not ad:
            break
        if any(p.get("creative_id") == ad.get("creative_id") for p in picked):
            break
        picked.append(ad)
    return picked


def _page_size(request) -> int:
    try:
        size = int(request.query_params.get("limit") or CursorPagination.page_size)
    except ValueError:
        size = CursorPagination.page_size
    return max(1, min(size, CursorPagination.max_page_size))


class HomeFeedView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FeedItemSerializer
    pagination_class = FeedCursorPagination
    # R3 WP 4b.8: first pages and peeks per account, rates from the active config.
    throttle_classes = [
        *api_settings.DEFAULT_THROTTLE_CLASSES,
        FeedFirstPageThrottle,
        FeedPeekThrottle,
    ]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "mode", OpenApiTypes.STR, enum=list(services.MODES), default=services.DEFAULT_MODE
            ),
            OpenApiParameter(
                "mode_hint",
                OpenApiTypes.STR,
                enum=list(services.MODES),
                description="The client's offline fallback, used only without `mode` "
                "and without a remembered mode.",
            ),
            OpenApiParameter("peek", OpenApiTypes.BOOL, description="New rows only (D4)."),
            OpenApiParameter(
                "since",
                OpenApiTypes.STR,
                description="Peek: rows after this (ISO 8601 or epoch seconds), clamped "
                "to `session.new_since.max_age_h`.",
            ),
            OpenApiParameter(
                "entry",
                OpenApiTypes.STR,
                enum=list(ENTRIES),
                description="How the client reached this first page: a hint only, the "
                "server classifies the visit from its own timestamps (`open` = `nav`, "
                "`refresh` = `pull`).",
            ),
            OpenApiParameter(
                "sid",
                OpenApiTypes.UUID,
                description="The client's telemetry session id (a hint only).",
            ),
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                description="Items per page (1 to 100). Without it, the first page has "
                "`delivery.first_page_size` items and later pages `delivery.page_size`.",
            ),
        ],
        responses={200: FeedItemSerializer(many=True)},
        tags=["feed"],
    )
    def get(self, request, *args, **kwargs):
        # WP 4b.14: the requesting account's own age class (rule E9b), from its own
        # token claims; safety data, captured whatever the personalization setting.
        age.capture(request.user.account_id, getattr(request.user, "claims", None))
        entry = request.query_params.get("entry")
        if entry is not None and entry not in ENTRIES:
            raise ValidationError({"entry": [f"Must be one of: {', '.join(ENTRIES)}."]})
        sid = _client_sid(request)
        mode = _mode(request)
        if request.query_params.get("peek") in ("1", "true"):
            return self._peek(request, mode)
        viewer = request.user.account_id
        token = request.query_params.get("cursor")
        first = token is None
        cfg = config.for_surface("home")
        visit, hot_state = None, None
        off = False
        if first:
            # WP 4b.15: the test clock (dev, flag on, seed or test account only).
            request._feed_now = clock.request_now(request, viewer)
            off = _personalization_off(request)
            ranked = mode == "for_you" and not off
            if ranked:
                # WP 5.4: a running experiment's variant (exposure written at this serve).
                cfg = experiments.config_for(viewer, ranking.SURFACE)
            use_interest, _use_session = config.schema.interest_ranking(cfg.params)
            hot_state = exposure_rank.prefetch(
                viewer,
                cfg,
                visit=not off,
                ledger=ranked and exposure_rank.applies(cfg),
                head=ranked and "head" in cfg.params,
                pools=ranked and discovery.retrieves(cfg),
                prof=ranked and use_interest,
                si=ranked,
            )
            if not off:
                visit = session_ctx.classify(
                    viewer,
                    ranking.SURFACE,
                    request._feed_now,
                    cfg,
                    entry=entry,
                    sid=sid,
                    state=hot_state.visit if hot_state.ok else None,
                )
                intel_metrics.visit(visit.kind)
        else:
            # A visit hash exists only for an account that is not personalization_off
            # (turning it on purges the hash), so the touch writes nothing for them.
            session_ctx.touch(viewer, timezone.now())
        # 02 section 13 / 04 WP 8.3: personalization off serves "for you" in the
        # chronological order with no inferred interests; its later pages carry the
        # chronological cursor (not a ranked one).
        chronological_for_you = mode == "for_you" and (
            off if first else not ranking.is_ranked_cursor(token)
        )
        if mode == "for_you" and not chronological_for_you:
            response = self._ranked(request, cfg, visit, hot_state)
        else:
            if chronological_for_you:
                request._feed_rows_mode = "recent"
            response = super().get(request, *args, **kwargs)
        if response.status_code == 200:
            if mode != "for_you" or chronological_for_you:
                # Ranked pages are stamped in _ranked (they know positions).
                found = topic_attach.attach(response.data["data"])
                serve_tokens.stamp_home_items(
                    viewer,
                    response.data["data"],
                    mode,
                    offset=None,
                    ranked=False,
                    visit_ord=visit.visit_ord if visit else None,
                    topics=topic_attach.primary(found),
                )
            response.data["mode"] = mode
            # WP 4c.2-B3: every page carries the Home delivery block, so the web holds
            # no delivery constants (08 section 7.2).
            response.data["meta"] = {
                **response.data.get("meta", {}),
                "delivery": config.delivery_for("home"),
            }
            # Ads go in after the organic page is complete (02 section 18), at the
            # config's slots, on the first page only; they never block organic content.
            if first:
                if mode != "for_you" or chronological_for_you:
                    self._chronological_visit(request, response, mode, cfg, visit)
                slots = ad_slots()
                ads = sponsored_for_slots(viewer, slots)
                response.data["sponsored"] = ads[0] if ads else None
                response.data["sponsored_slots"] = ads
                response.data["meta"] = {
                    **response.data.get("meta", {}),
                    "ad_slots": slots,
                    "as_of": timezone.now().isoformat(),
                    # 06 section 6.1: the client's refresh timers come from the config.
                    "refresh_after_s": int(cfg.get("session.refresh_after_s")),
                    "auto_refetch_after_s": int(cfg.get("session.auto_refetch_after_s")),
                    # R4 API contract: the web shows the "personalization is off" note.
                    "personalization_off": bool(off),
                }
        return response

    def _chronological_visit(self, request, response, mode: str, cfg, visit) -> None:
        """``meta.visit`` and the caught-up marker of a chronological first page (06
        section 6.2): the rows newer than ``since`` are counted on the page's own
        queryset; in ``recent`` they are exactly the top ``new_count`` rows, so the
        divider sits after them and the caught-up marker at the first older row. The
        order never changes."""
        new_count, capped = 0, False
        if visit is not None and visit.since is not None:
            new_count, capped = services.new_since_count(
                request.user.account_id, mode, visit.since, int(cfg.get("peek.max_count"))
            )
        anchor = new_count if new_count and not capped else None
        data = response.data.get("data") or []
        response.data["meta"] = {
            **response.data.get("meta", {}),
            "visit": session_ctx.meta(visit, cfg, new_count=new_count, anchor_index=anchor),
            "caught_up_index": anchor if anchor is not None and anchor < len(data) else None,
        }
        if visit is not None:
            session_ctx.finish(request.user.account_id, visit, new_count=new_count)

    def _peek(self, request, mode: str) -> Response:
        """``?peek=1`` (D4, WP 4.7; R3): new **eligible** rows for the "new posts" pill.
        Read only: it never writes or replaces the ranking session and never calls ads."""
        viewer = request.user.account_id
        cfg = config.for_surface("home")
        found = services.peek(
            viewer,
            mode,
            _since(request),
            _page_size(request),
            cfg,
            claims=getattr(request.user, "claims", None),
            now=clock.request_now(request, viewer),
        )
        data = FeedItemSerializer(found.rows, many=True).data
        topics = topic_attach.attach(data)
        serve_tokens.stamp_home_items(
            viewer, data, mode, offset=None, ranked=False, topics=topic_attach.primary(topics)
        )
        return Response(
            {
                "data": data,
                "ids": [str(r.post_id) for r in found.rows],
                "mode": mode,
                "peek": True,
                "new_count": found.new_count,
                "new_count_capped": found.capped,
                "since": found.since.isoformat(),
            }
        )

    def _ranked(self, request, cfg, visit, hot_state) -> Response:
        viewer, size = request.user.account_id, _delivery_size(request)
        token = request.query_params.get("cursor")
        claims = getattr(request.user, "claims", None)  # age claims for eligibility
        overlap = None
        try:
            if token is None:
                page = None
                if (
                    visit is not None
                    and visit.kind in (session_ctx.REFRESH, session_ctx.ONGOING)
                    and visit.entry in REUSE_ENTRIES
                ):
                    # A reload or a way back during the visit: the live frozen list
                    # again, same sid, no re-rank (08 scenario 5).
                    page = ranking.reuse_page(viewer, size, claims)
                if page is None:
                    personal = _personal(request, cfg, hot_state, visit)
                    page = ranking.first_page(
                        viewer,
                        size,
                        request._feed_now,
                        claims,
                        ctx=_exposure_context(request._feed_now, visit, hot_state),
                        pools=hot_state.pools if hot_state is not None else None,
                        since=visit.since if visit is not None else None,
                        cfg=cfg,
                        personal=personal,
                    )
                    request._feed_intent = personal.intent
                offset = 0
            else:
                cursor = ranking.decode_cursor(token)
                page = ranking.next_page(viewer, token, size, claims)
                offset = int(cursor.get("o", 0)) if cursor.get("k") == "r" else None
        except ranking.InvalidCursor as exc:
            raise NotFound("Invalid cursor.") from exc
        # A first page is ranked even when its session could not be stored; a later
        # page is ranked only while it reads the session (not the chronological fallback).
        ranked = offset is not None and (token is None or not page.fallback)
        data = FeedItemSerializer(page.items, many=True).data
        # R4: topics from the eligibility read (no extra query on a ranked page).
        found = topic_attach.attach(
            data, page.topics if page.items else {}, page.topic_labels if page.items else {}
        )
        if ranked and page.sources:
            # Additive (WP 4.3): the candidate source, which the web passes to post's
            # /posts/batch/ as the ``src`` hint.
            for item, source in zip(data, page.sources, strict=True):
                item["source"] = source
        serve_tokens.stamp_home_items(
            viewer,
            data,
            "for_you",
            offset=offset if ranked else None,
            ranked=ranked,
            cfg_version=page.cfg_version if ranked else None,
            visit_ord=visit.visit_ord if visit is not None else None,
            topics=topic_attach.primary(found),
        )
        if page.caught_up and ranked:
            intel_metrics.caught_up()
        meta = {"caught_up_index": page.caught_up_index if ranked else None}
        if token is None:
            if not page.reused:
                # WP 4b.11: overlap with the previous first page (ids only; nothing
                # stored under personalization_off or a version without the head block).
                overlap = first_page_head.record(
                    viewer,
                    ranking.SURFACE,
                    [i["post_id"] for i in data],
                    cfg,
                    previous=hot_state.head if hot_state is not None and hot_state.ok else None,
                    personalization_off=visit is None,
                )
            new_count, anchor = _visit_counts(page, visit)
            meta["visit"] = session_ctx.meta(visit, cfg, new_count=new_count, anchor_index=anchor)
            if visit is not None:
                # 06 section 4.5 (WP 6.8-B2): the shadow intent, stored, never used.
                chosen = intent.finalize(
                    getattr(request, "_feed_intent", None), visit, new_count, cfg
                )
                session_ctx.finish(
                    viewer,
                    visit,
                    new_count=new_count,
                    anchor_index=anchor,
                    head_overlap=overlap,
                    intent=chosen,
                )
                intent.store(viewer, chosen, cfg)
        return Response(
            {
                "data": data,
                "page": {
                    "next_cursor": page.next_cursor,
                    "prev_cursor": None,
                    "has_more": page.has_more,
                    "fallback": page.fallback,
                },
                # WP 4b.6: where this page's items leave the connection inventory.
                "meta": meta,
            }
        )

    def get_queryset(self):
        rows_mode = getattr(self.request, "_feed_rows_mode", None) or _mode(self.request)
        return services.home_feed(self.request.user.account_id, rows_mode)


# The first-page hints that reuse a live ranking session during a visit (refresh or
# ongoing): a browser reload, in-app navigation. ``pull``, ``return`` and ``load``
# re-rank (06 section 4.2).
REUSE_ENTRIES = frozenset({"reload", "nav"})


def _client_sid(request) -> str | None:
    raw = request.query_params.get("sid")
    if not raw:
        return None
    try:
        return uuid.UUID(raw).hex
    except ValueError as exc:
        raise ValidationError({"sid": ["A UUID."]}) from exc


def _exposure_context(now, visit, hot_state):
    """The ranker's exposure context from the first page's pipelined read (None under
    personalization_off: nothing behavioural is read or used)."""
    if visit is None:
        return None
    folds = {}
    if hot_state is not None and hot_state.ledger:
        folds = exposure.fold(hot_state.ledger, visit.visit_ord)
    previous = first_page_head.unpack(hot_state.head) if hot_state is not None else []
    return exposure_rank.Context(
        now=now,
        folds=folds,
        previous_head=frozenset(previous),
        since=visit.since,
        lapsed=visit.is_lapsed,
    )


def _visit_counts(page, visit) -> tuple[int, int | None]:
    """``(new_count, anchor_index)`` of a ranked first page: from its ranking, or, for
    a reused frozen list, what the visit's last ranked page stored."""
    if visit is None or visit.since is None:
        return 0, None
    if page.reused or page.new_count is None:
        return visit.stored_new_count, visit.stored_anchor
    return page.new_count, page.anchor_index


def _personalization_off(request) -> bool:
    """The viewer's ``personalization_off``, read with the remembered mode (one row)."""
    _preference_row(request)
    return request._feed_pref[1]


_PREF_SQL = """
SELECT p.default_mode, p.personalization_off, p.discovery_level, p.languages, p.formats,
       p.discovery_prefs, l.language
FROM (SELECT %s::uuid AS a) x
LEFT JOIN intel_user_preference p ON p.account_id = x.a
LEFT JOIN intel_account_language l ON l.account_id = x.a
"""


def _preference_row(request) -> tuple[str | None, bool]:
    """The remembered mode and ``personalization_off`` (R3 A8), plus (R4) the My
    Algorithm controls and the account language, in the same single statement
    (``request._feed_pref_full``)."""
    cached = getattr(request, "_feed_pref", None)
    if cached is None:
        from django.db import connection

        try:
            with connection.cursor() as cur:
                cur.execute(_PREF_SQL, [str(request.user.account_id)])
                row = cur.fetchone()
        except Exception:  # noqa: BLE001 - fail closed: unreadable counts as off
            row = (None, True, None, None, None, None, None)
        mode, off, level, languages, formats, prefs, account_lang = row
        cached = request._feed_pref = (mode if mode in services.MODES else None, bool(off))
        request._feed_pref_full = {
            "discovery_level": 2 if level is None else int(level),
            "languages": list(languages or []),
            "formats": formats if isinstance(formats, dict) else {},
            "discovery_prefs": prefs if isinstance(prefs, dict) else {},
            "account_language": account_lang,
        }
    return cached


def _personal(request, cfg, hot_state, visit) -> Personal:
    """The ranker's personal inputs (R4) from the preference row and the first page's
    pipelined read: the interest profile only under a version that uses it, the
    session vector and the viewer's controls under every version."""
    from intel import interests

    _preference_row(request)
    full = getattr(request, "_feed_pref_full", {}) or {}
    now = request._feed_now
    use_interest, _use_session = config.schema.interest_ranking(cfg.params)
    profile, need = None, False
    if use_interest:
        # intel:prof from the pipelined read; a miss is filled from the eligibility
        # statement's rows by the ranker (no query of its own).
        profile = interests.Profile.from_bytes(hot_state.prof if hot_state is not None else None)
        need = profile is None
    si = session_ctx.si_decode(
        hot_state.si if hot_state is not None else None, now, cfg.section("session_interest")
    )
    personal = Personal(
        profile=profile,
        si=si,
        formats=full.get("formats") or {},
        discovery_level=full.get("discovery_level", 2),
        discovery_prefs=full.get("discovery_prefs") or {},
        languages=_languages(full),
        need_profile=need,
        account_id=str(request.user.account_id),
    )
    personal.intent = intent.classify(visit, si, cfg)
    return personal


def _languages(full: dict) -> frozenset | None:
    """E10's content languages: the viewer's chosen ones, else the account language
    when known (03 section 2.4), else None (no language filter)."""
    chosen = [x for x in full.get("languages") or [] if x]
    if not chosen and full.get("account_language"):
        chosen = [full["account_language"]]
    return frozenset(chosen) if chosen else None


DELIVERY_SURFACES = ("home", "reels", "video")


class DeliveryView(APIView):
    """``GET /feed/delivery/`` (WP 4c.2-B3): the delivery block of Home, Reels and
    Video from the central config, for the surfaces whose pages do not come from
    ``/feed/``. The same for every viewer: no per-viewer data, no version label."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["feed"])
    def get(self, request):
        body = {surface: config.delivery_for(surface) for surface in DELIVERY_SURFACES}
        return data_response(body, headers={"Cache-Control": "private, max-age=300"})


class HideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=HideRequestSerializer, responses={201: PostHideSerializer}, tags=["feed"]
    )
    def post(self, request):
        body = HideRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        viewer, post_id = request.user.account_id, body.validated_data["post_id"]
        was_hidden = PostHide.objects.filter(account_id=viewer, post_id=post_id).exists()
        hide = feedback.hide_post(viewer, post_id, body.validated_data["reason"])
        if not was_hidden:  # a repeat or a new reason is the same hide, not a new action
            menu_signal(viewer, EventType.POST_HIDE, ItemType.POST, post_id, hide.author_id)
            # R4 (06 section 4.4): a hide subtracts from the session interest vector.
            from intel.handlers import session_vector_bus

            session_vector_bus(viewer, EventType.POST_HIDE, post_id)
        # R4 WP 7.4: spam / sexual hides past the threshold reach moderation (no hider named).
        from intel import integrity_flags

        integrity_flags.check(post_id, hide.author_id, hide.reason)
        return data_response(PostHideSerializer(hide).data, status=status.HTTP_201_CREATED)


class UnhideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["feed"])
    def delete(self, request, post_id):
        viewer = request.user.account_id
        hide = PostHide.objects.filter(account_id=viewer, post_id=post_id).first()
        feedback.unhide_post(viewer, post_id)
        if hide is not None:
            menu_signal(viewer, EventType.POST_UNHIDE, ItemType.POST, post_id, hide.author_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SnoozeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SnoozeRequestSerializer, responses={201: AuthorSnoozeSerializer}, tags=["feed"]
    )
    def post(self, request):
        body = SnoozeRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        viewer, author_id = request.user.account_id, body.validated_data["author_id"]
        snooze = feedback.snooze_author(viewer, author_id)
        menu_signal(viewer, EventType.AUTHOR_SNOOZE, ItemType.PROFILE, author_id, author_id)
        return data_response(AuthorSnoozeSerializer(snooze).data, status=status.HTTP_201_CREATED)


class UnsnoozeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["feed"])
    def delete(self, request, author_id):
        viewer = request.user.account_id
        was_snoozed = AuthorSnooze.objects.filter(account_id=viewer, author_id=author_id).exists()
        feedback.unsnooze_author(viewer, author_id)
        if was_snoozed:
            menu_signal(viewer, EventType.AUTHOR_UNSNOOZE, ItemType.PROFILE, author_id, author_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SnoozeListView(generics.ListAPIView):
    """Active snoozes, newest first (for the settings screen)."""

    permission_classes = [IsAuthenticated]
    serializer_class = AuthorSnoozeSerializer
    pagination_class = SnoozeCursorPagination

    @extend_schema(tags=["feed"])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return feedback.active_snoozes(self.request.user.account_id).order_by("-snoozed_at")
