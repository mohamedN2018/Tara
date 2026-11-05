# 04. Build plan for the next round

**Scope.** This plan covers the next round, which brings Tara up to the reference's systems, structure and layout. Feature rows are numbered as in [03-gap-matrix.md](03-gap-matrix.md) (`#nn`); systems use the IDs in [02-systems-catalog.md](02-systems-catalog.md).

## Ground rules for every epic

1. **Brand.** Copy only the structure, flows, density and layout of the reference.
   - Tara keeps its own name, logos, purple palette, icon set (lucide), illustrations and copy.
   - Do not copy the reference wordmark, reference icon glyphs, reference colour blue, or names of reference programmes such as its AI assistant, its paid verification or its business suite.
   - Use Tara names instead: *Tara Assistant*, *Tara Verified*, *Tara Business*, *Tara Ads*, *Tara chat* (never the reference chat brand), *Tara data sources / tracking tag* (for the reference's datasets and pixels).
   - Light mode is checked against S22 (social), S44 (business) and S53 (ads); dark mode against the social captures.
2. **Service ownership.** Each service owns its own models. Other services learn about changes only through `OutboxEvent` rows, which follow the schemas in `libs/tara_events/tara_events/schemas/<domain>.<entity>.<verb>.v1.json`.
   - Consumers are idempotent and record what they have handled in `ProcessedEvent`.
   - Synchronous reads go through internal URLs (the existing `internal_urls.py` pattern) or through the BFF.
   - Every new event is added to `docs/architecture/phase-0/04-event-contracts.md` §5.
3. **Privacy.**
   - Every new user-facing field gets an audience, either through `ProfileFieldPrivacy` or an `audience` column.
   - Blocks are enforced on every read path.
   - Anonymous identities, hashed customer lists and aggregated metrics never leak raw identities across services.
   - Ads metrics keep the existing privacy bucketing.
4. **Arabic RTL first.**
   - Use logical CSS properties.
   - Wrap IDs, URLs and currency in LTR islands.
   - Add every string to the Arabic and English i18n files.
   - Arabic-Indic digits are pending an owner decision (D7 in `README.ar.md`).
5. **Navigation flags.** Leave a `menuCatalog.ts` item at `built:false` until its epic meets its acceptance criteria, then flip it. Never show a "coming soon" placeholder.
6. **Tests for every epic.**
   - Backend: pytest unit tests plus API tests in the owning service (`scripts/test-service.sh <svc>`).
   - Contracts: event contract tests against the JSON schema.
   - Frontend: Vitest specs under `FE/__tests__`.
   - End to end: one Playwright journey per epic, run in Arabic RTL and in English, in both the light and dark themes.
7. **Delivery.** Commit and push each verified step. Never commit `.env_prod`. Log every step in `docs/ecosystem/07-work-log.ar.md`.

## Step 0: close the current round first

The owner asked to finish the current work before starting this round.

**Branch state.** The `feat/web-social-platform` branch has a large uncommitted change set:
- feed intel and deletion;
- graph suggestions;
- moderation hardening;
- the post and reels internal APIs;
- dokploy env generation;
- `docs/intelligence/results/phase-03-track-b.md`.

**Exit criteria:**
- all service test suites pass;
- the change set is committed in logical steps and pushed;
- the work log is updated;
- the intel phase-3 track-B results are recorded.

Do not start Epic 1 on top of uncommitted work.

---

## Phase A: foundations (P0)

### Epic 1. Acting identity: switch between a person and a Page (SYS-29; #25, #61, #110, enables #50, #121-124)

**Scope.**
- A user can act as a Page they manage. This covers:
  - posting;
  - commenting and replying;
  - reacting;
  - messaging from the Page inbox;
  - viewing Page notifications.
- An account-menu profile switcher with "See all profiles".
- A "Switch to this Page" banner and card on Pages.
- A "commenting as …" chevron and warning line.
- Page-mode top tabs: Home, Pages, Insights, Ads.

**Backend.**
- `bff`:
  - accept an `X-Tara-Actor: user|page:<id>` header;
  - validate the requester's `PageMember` role against an action-to-role matrix (post: editor+; comment, reply and react: moderator+; inbox: moderator+; insights: analyst+; ads: advertiser+);
  - forward `actor_type`, `actor_id` and `acted_by_account_id` to downstream services.
- `profile`: expose `GET /internal/pages/<id>/role/<account>`, cached.
- `post`:
  - add `author_type` and `acted_by_account_id` to `Comment`, `CommentReaction` and `PostReaction` (`Post` already has `author_type`);
  - migrate existing rows to `user`.
- `chat`: when acting as a Page, send through the `Conversation.type=page` path.
- `notification`: add a recipient type `page` and a per-Page unread count.
- **Events:**
  - add the actor fields to `post.commented.v1` and `post.reacted.v1`, as a backward-compatible optional field;
  - add a new `actor.switched.v1` for audit only, consumed by `admin`.

**Frontend.**
- A `useActingIdentity` store holding the actor, persisted per tab in sessionStorage, with a server re-check on load.
- Profile switcher in `ProfileMenu.vue`.
- An actor chevron in `CommentInput.vue` and the composer header.
- A switch banner component on `PageDetailView.vue`.
- A Page-mode variant of `AppNavbar.vue`.

**Acceptance criteria.**
- An editor switches to a Page. Then:
  - a new post, comment and reaction all show the Page as author;
  - an admin audit row records the real account.
- An analyst cannot comment as the Page and gets a 403 with an Arabic message.
- Reloading the browser keeps the actor.
- Signing out clears the actor.
- Revoking the role ends acting on the next request.

**Tests.**
- BFF role-matrix unit tests covering every role and action.
- Post API tests for comments and reactions as a Page.
- Contract tests for the updated events.
- Playwright: switch, comment, check the author, switch back.

### Epic 2. Tara Ads foundation: account, hierarchy, table and wizard (SYS-25; #128-132, #134, #149)

**Scope.**
- Multiple ad accounts per person, owned by a person now and by a portfolio later (Epic 9).
- An ad-account switcher.
- A dedicated ads shell with an icon rail, an account selector and an all-tools list.
- A **Campaigns / Ad sets / Ads data table** with:
  - on/off toggles;
  - delivery status;
  - sortable metric columns;
  - a date range;
  - a column preset.
- A **create wizard**:
  - a Create modal with two tabs: "New campaign" (buying type and objective) and "New ad set or ad in an existing campaign" (pick the campaign, then the ad set);
  - then Campaign › Ad set › Ad steps with a tree pane, a breadcrumb and autosave;
  - **Campaign step fields:** name, special ad categories, buying type, objective, campaign budget (CBO) on or off, A/B test toggle;
  - **Ad set step fields:** conversion location (website, app, messages, calls, Page), performance goal, data source, budget and schedule (under ABO), audience (saved, new or custom; the evaluator comes in Epic 8), placements (automatic or manual), cost-per-result goal;
  - **Ad step fields:** acting identity (Page), ad setup (create new or use an existing post), format, media, primary text, headline, description, CTA, destination URL, URL parameters and tracking, preview per placement;
  - **per-step validation** (rules in 02 SYS-25): a step's Next button stays disabled until its required fields are valid, and the tree pane marks a step with errors.
- **Objectives:** awareness, traffic, engagement, leads, app promotion, sales.
- **Budget:** CBO or ABO, daily or lifetime, with spend projections.
- A **draft layer** with "Review and publish (N)" and Discard.

**Backend (`ads`).**
- Rename `AdvertiserAccount` to `AdAccount` in place:
  - add `owner_type`, `owner_id`, `currency`, `timezone`, `status`, `spend_cap`;
  - drop the uniqueness on owner;
  - add `AdAccountMember{role admin|advertiser|analyst|finance}`.
- `Campaign`:
  - add `buying_type`, `budget_mode`, `daily_budget`, `lifetime_budget`, `bid_strategy`, `effective_status`, `special_ad_categories[]`, `ab_test`;
  - widen the objective enum.
- `AdSet`:
  - add budget fields (used under ABO), `optimization_goal`, `conversion_location`, `performance_goal`, `cost_per_result_goal` and `data_source_id` (nullable until Phase D);
  - keep the `targeting` JSON for now (Epic 8 evaluates it);
  - keep the single `placement` field here; Epic 8 migrates it to a list.
- `AdCreative`: add `identity_page_id`, `description`, `url_params`.
- Add `Ad` as the link between `AdSet` and `AdCreative`, so one creative can be reused.
- Add `DraftChange{entity, entity_id, payload, author}` and `POST /ads/accounts/<id>/publish`, which applies the drafts atomically.
- Add `AdInsightDaily{level, entity_id, date, impressions, reach, clicks, spend, results}`.
  - It is filled by aggregating the existing `AdImpressionEvent` and `AdClickEvent` with a Celery task.
- Table endpoint: `GET /ads/accounts/<id>/table?level=campaign|adset|ad&from&to&sort&columns`, with server-side sort and paging.
- **Events:**
  - `ad.campaign.published.v1`;
  - `ad.account.status_changed.v1`, consumed by `notification`.

**Frontend.**
- `views/ads/` with `AdsShell.vue` (icon rail on the start side).
- `AdsTable.vue`: virtualised rows, sticky header, column picker, row checkboxes.
- `CreateCampaignModal.vue`.
- `CampaignWizard.vue` with three step forms and a projection helper.
- `ReviewPublishBar.vue`.
- The old `AdsView.vue` card list is replaced.

**Acceptance criteria.**
- A user with two ad accounts can switch between them, and the table scopes to the selected account.
- A new campaign appears as a draft row before it is published.
- "Review and publish (N)" publishes all drafts or none.
- A daily budget of $200 shows the projections from S48: daily maximum 1.75× and weekly maximum 7×.
- Sorting by spend works server-side across pages.
- **Wizard validation.** On each step, Next is disabled while any required field is empty or invalid (for example an empty name, no objective, a lifetime budget without an end date, or a non-`https://` URL), and becomes enabled within one render after the last field turns valid. The server rejects the same invalid payload with 400 and a field map.
- **Create modal.** The "Continue" button is disabled until an objective is selected; the second tab lists only campaigns of the current ad account.
- **RTL table.** In Arabic:
  - the columns run from the start side (right) in this order: checkbox, on/off toggle, name, delivery, attribution setting, results, cost per result, budget, amount spent, impressions, reach, end date, bid strategy;
  - the checkbox, toggle and name columns are **sticky on the start side** (right offset 0) while the table scrolls horizontally;
  - direction icons (chevrons, sort arrows, breadcrumb separators, the tree pane's expand arrow) are mirrored; charts, media and brand icons are not;
  - ad-account and campaign IDs, money, percentages and dates sit in `dir="ltr"` islands (or `<bdi>`), so "$200.00" and "2026/11/03 - 2026/10/05" never reorder.
  A Playwright check asserts the column order, `position: sticky` on the name column, and the `dir` attribute on ID, money and date cells.

**Tests.**
- Model migration test that carries the old rows over.
- Publish atomicity test.
- Insights aggregation test.
- Table sort and paging API tests.
- Vitest for the projection maths.
- Vitest for each step's validation (Next disabled and enabled cases).
- Playwright: create → draft → publish → toggle off, run in Arabic and English.

---

## Phase B: core parity (P1)

### Epic 3. Comments parity (SYS-04; #20, #21, #23, #24)

**Backend (`post`).**
- Add `Comment.attachment_media_id` and `Comment.sticker_id`. GIF support comes in Epic 4.
- Add `GET comments?sort=relevant|newest|all`. Relevance score = (reactions + 2×replies + 3×[the post author replied] + 2×[the comment author is the viewer's friend]) × 0.5^(age_hours / 24), so the **decay half-life is 24 hours**. Ties break by newer first, then by id.
- Add an `is_post_author` flag in the serializer.
- Add an `author_reacted` flag.
- Add an owner-hide state on `Comment` (`hidden_by_owner_at`, `hidden_by`). Today `Comment` has only `moderation_status` ok|removed, and the "hide" in `CommentList.vue:361` only collapses replies. A hidden comment stays visible to its author and the post owner only.

**Frontend.**
- Sort dropdown in `CommentList.vue` and `PostTheaterPanel.vue`.
- Attachment button and preview in `CommentInput.vue`.
- "Author" badge and "author reacted" chip in `CommentItem.vue`.
- Hide action.

**Acceptance criteria.**
- The default sort is "relevant", and "newest" is strictly by time.
- **Relevance fixture.** With the viewer "now" fixed: comment A has 10 reactions, 0 replies and is 48 hours old (score 2.50); comment B has 1 reaction, 1 reply and is 2 hours old (score 2.83); comment C has no reactions or replies, the post author replied to it, and it is 1 hour old (score 2.91). `sort=relevant` returns C, B, A; `sort=newest` returns C, B, A by time; changing A to 12 hours old (score 7.07) puts A first.
- A hidden comment is visible to its author and the post owner only.
- A reply by the post author shows the badge.

**Tests.**
- Sort ordering fixtures.
- Hide visibility matrix.
- Badge rendering spec.

### Epic 4. Composer and post parity (SYS-03/21; #9, #10, #14, #18, #93, #105, #13, #159)

**Backend.**
- `post`:
  - add `Post.bg_style`, reusing the story `BACKGROUND_STYLES` keys; allowed only for text of **at most 130 characters and at most 5 lines** with no media;
  - add the `post.scheduled_published` notification kind (S03);
  - a hashtag page endpoint: posts for one tag, `sort=top|recent`, with a post count (#159).
  - add `Post.title`, used in groups only;
  - add `Post.ai_label` (bool);
  - add `Post.story_kind` (none|avatar_update|cover_update), with the avatar caption stored as the body.
- `identity`: add `Account.default_audience`.
- `media`: add a GIF proxy endpoint that calls an owner-chosen provider through a server-side key, with results cached. If the owner declines (D5), use a local sticker pack only.

**Frontend.**
- "Aa" background picker in `ComposerDialog.vue`.
- AI-label toggle in the sharing section, and an "AI content" chip on `PostCard.vue`.
- Description field in `AvatarCropDialog.vue`.
- Default-audience setting.

**Acceptance criteria.**
- A short text post with a background renders large and centred in the feed, in the theater and in RTL.
- A text of 131 characters or more, or of 6 lines or more, disables the background picker and shows the hint "Backgrounds are for short text"; a request that sets `bg_style` on such text gets 400.
- A scheduled post notifies its author when it is published.
- Tapping a hashtag opens the hashtag page, which lists only posts the viewer may see.
- Changing the avatar with a description creates one post with that caption.
- A new account composes with its default audience.

**Tests.**
- Serializer validation.
- Event contract for `post.created.v1` with the new optional fields.
- Visual Vitest snapshot of the background card.

### Epic 5. Profile parity and onboarding (SYS-17/18/28; #90, #94, #101, #66 photos, #97, #177)

**Backend (`profile`, `post`).**
- `UserProfile`:
  - add `alternate_name`, with an audience control;
  - add `professional_mode`;
  - add `category` (a curated list in Arabic and English).
- Add `UserContactHandle{network, handle}` with field privacy.
- `post`:
  - add `Album{owner_type, owner_id, name, kind user|profile|cover|uploads, audience}` and `AlbumItem`;
  - backfill the system albums from existing `story_kind` posts and uploads.
- Events: `album.created.v1`, `album.updated.v1`.

**Frontend.**
- `ProfileHero.vue`: alternate name, category in the meta line, and a Dashboard button when professional mode is on (links to `/studio`).
- Flip `professionalProfile` in the menu.
- Albums tab in `PhotoPickerDialog.vue` and `ProfilePhotosTab.vue`, with create, rename and delete for albums.
- Photos tab on Pages.
- Post-signup onboarding (#177): profile photo → find friends → interests → done, every step skippable, shown once after the first verified login.

**Acceptance criteria.**
- A visitor sees the alternate name only when its audience allows it.
- A new account sees onboarding once; skipping every step lands on the home feed; finishing it records the chosen interests for the feed.
- The album audience is enforced on album items.
- Professional mode switches the header count to followers-first.

**Tests.**
- Privacy matrix for new fields.
- Album audience tests.
- Backfill idempotency test.

### Epic 6. Groups core parity (SYS-09; #43, #44, #51, #56, #19)

**Backend.**
- `profile/groups`:
  - add `GroupMember.last_visited_at` (updated on visit and throttled);
  - add `Group.last_activity_at`;
  - add a nightly `posts_per_day` rollup;
  - add `GroupAdminLog{actor, action, target, at}` for every admin action.
- `post`:
  - add a group feed sort `recent_activity|new|relevant`;
  - add `Post.is_anonymous` plus `GroupMember.anon_alias`, a stable per-member generated pseudonym;
  - reads expose only the alias, except to group admins and moderators;
  - the post owner can still edit and delete;
  - remove scheduling and draft restrictions in groups.
- Events: `group.member.visited` must **not** be an event (it is too chatty). Use an internal update. Add `group.admin.actioned.v1`.

**Frontend.**
- Sort dropdown in `GroupPostList.vue`.
- Anonymous toggle in the group composer, when enabled in the group settings.
- Alias avatars.
- "Last active" and "posts a day" on cards and in the rail.
- Admin log section in `GroupManageView.vue`.

**Acceptance criteria.**
- An anonymous post never exposes the author id in any API response to non-admins, including search, notifications and feed.
- The admin log lists approvals and removals with the actor.

**Tests.**
- A **privacy leak test** across post, feed, search and notification payloads for anonymous posts.
- Sort tests.
- Admin log tests.

### Epic 7. Metrics pipeline and studio depth (SYS-23/07; #17, #38, #115, #121)

**Backend.**
- `feed/intel`:
  - add `DailyMetric{subject_type user|page, subject_id, date, views, viewers, engagement, follows}`;
  - add `PostMetric{post, views, viewers, watch_ms, views_3s, views_60s}`;
  - both are filled from the existing impression events plus a new `video.watched.v1` (batched client beacons, privacy-bucketed).
- API `studio/insights?subject=page:<id>&from&to&compare=previous`.

**Frontend.**
- KPI carousel with % deltas.
- "See insights" on the owner's `PostCard.vue`, opening a per-post insights sheet.
- Studio scoped to a Page when acting as that Page (depends on Epic 1).
- Library column chooser and new columns.

**Acceptance criteria.**
- The delta equals (current - previous) / previous, and shows "–" when the previous period is zero.
- An analyst on a Page sees that Page's insights only.

**Tests.**
- Aggregation tests with fixed fixtures.
- Delta edge cases.
- Permission tests.

### Epic 8. Boost, audiences, placements and reporting (SYS-25; #16, #68, #129, #135, #138, #139, #140, #186, #187, #188)

**Scope.**
- **Boost** from a post, the composer toggle, a Page card or a business home card.
  - A one-step dialog creates a campaign, an ad set and an ad with `AdCreative.source_post_id`.
  - **Boost-eligibility rule:** the post is public, published (not draft or scheduled), not removed or under moderation review, not anonymous, not a reshare of someone else's post, and the user may advertise for the author (self, or Page advertiser role). The API returns `eligible` and a `reason` code per post.
- **Saved audiences:**
  - fields: location (country or city), age range, gender, languages, interests from a curated taxonomy;
  - detailed targeting with include, exclude and narrow groups;
  - a **targeting evaluator** at serve time against coarse, consented profile attributes.
- **Special ad categories (#186):** housing, employment, credit, social issues. When set, the evaluator ignores age, gender and postcode, and the UI locks those fields.
- **Reach estimate (#187):** a gauge with a rounded range (never below 1,000, rounded to two significant figures).
- **Account-level controls (#188):** minimum age, excluded locations, excluded placements, applied to every ad set of the account.
- **Placements:**
  - feed, right rail, marketplace, search, stories, reels;
  - automatic or manual;
  - **schema change:** `AdSet.placement` (one choice) becomes `placements[]`, with a data migration that wraps the old value in a list;
  - new ad slots in stories and reels.
- **Creative formats:** image, video, carousel and existing post, with a per-placement preview.
- **Reporting:** breakdowns by day, placement, age band and gender band (bucketed), plus CSV export.

**Privacy.**
- Targeting uses only attributes the user has not hidden.
- A breakdown cell is suppressed when it has **fewer than 50 distinct people (estimated reach) or fewer than 100 impressions**. It shows "–" with the tooltip "Too few people to show". When only one cell of a breakdown is suppressed, the next-smallest cell is suppressed too, so the total cannot be used to work it out. The totals row still shows the full figures.
- "Why am I seeing this ad" explains the matched criteria.

**Acceptance criteria.**
- A boosted post shows as sponsored to an audience matched by age and city.
- Users outside the audience never see it.
- **Boost eligibility.** For a friends-only post, a scheduled post and an anonymous group post, the Boost button is rendered disabled as "Promote unavailable" and its tooltip names the reason; the boost API returns 422 with the same reason code.
- **Suppression fixture.** A breakdown by age band with cells of 400, 120, 45 and 30 people shows 400 and 120, and "–" for 45 and 30; a breakdown with cells of 400, 120 and 45 suppresses 45 and also 120.
- **Special category.** A housing campaign saved with an age range of 25–34 is stored as 18–65+, and the evaluator serves it to a matching 50-year-old.
- **Placements migration.** An existing ad set with `placement=search` reads back as `placements=["search"]`.

**Tests.**
- Evaluator unit tests, including include, exclude and narrow.
- Suppression tests with the fixture above.
- Boost-eligibility reason codes, one test per rule.
- Placement migration test.
- Boost end to end.

### Epic 9. Tara Business: portfolio and business home (SYS-24; #122-126, #192)

**Backend.**
- Decide placement: a new `business` app inside `profile` (recommended; no new service yet) or a new service (D3).
- Models: `BusinessPortfolio`, `PortfolioMember{role admin|employee}`, `PortfolioAsset{kind page|ad_account}`, `AssetPermission{tasks[]}`, `AccessRequest`, `PortfolioSecurity{require_2fa}`.
- Tasks follow the per-asset task matrix and the role × action matrix in 02 SYS-24 (Pages: content, messages, community, ads, insights, revenue; ad accounts: manage, advertise, analyze).
- `ads.AdAccount.owner_type=portfolio` is wired through an internal check.
- A to-do aggregation endpoint in `bff` combines:
  - unread Page messages from `chat`;
  - unanswered comments on Page posts from `post`.

**Frontend.**
- `/business`, flipped to `built:true`, with:
  - an asset switcher popover (portfolios on one side, assets on the other);
  - home cards: hero, action row, to-do, content tabs with Boost and insights, recent ads, a follower goal ring;
  - settings: people, Pages, ad accounts, requests.

**Acceptance criteria.**
- A portfolio admin can add an asset (a Page they administer, or an ad account they own) and assign tasks on it to an employee; the employee then has exactly those tasks and no others.
- An employee with only the "content" task on a Page cannot see its ad account.
- Removing a member revokes access immediately.
- An access request appears for admins, and approving it with chosen tasks grants exactly those tasks; declining notifies the requester.
- With "require 2FA: everyone" on, a member without 2FA gets 403 with an Arabic message on every portfolio endpoint until they enable it.

**Tests.**
- Permission matrix: one test per row of the role × action matrix in 02 SYS-24.
- To-do aggregation contract.
- Playwright business home journey.

### Epic 10. Help centre, report a problem and the report flow (SYS-22/26; #111, #112, #183)

**Backend.**
- A `help` app in `admin`:
  - `HelpCategory`;
  - `HelpArticle` (Arabic and English bodies, platform variants, related articles);
  - `ArticleFeedback`.
- Indexed in `search`.
- Add `ProblemReport{area, text, screenshot_media_id, client_info}`, feeding the admin support inbox.
- Multi-step content report (#183): category → sub-reason → optional details → confirm → next steps (block, unfollow, restrict, hide), reusing `moderation` `Report`.

**Frontend.**
- `/help`: category rail, article page, copy link, related chips, a feedback tab, and search.
- A report-a-problem dialog reachable from the account menu, with the Ctrl+B shortcut and an optional screenshot.

**Acceptance criteria.**
- Articles render RTL and LTR from the same slug.
- Feedback is counted per article.
- A report with a screenshot appears in `AdminSupportView.vue`.
- **Search relevance.** A title match ranks above a body-only match: for the query "كلمة المرور", the article titled "تغيير كلمة المرور" is first.
- **Arabic search.** Queries are normalised the same way as the index: hamza forms (أ إ آ → ا), taa marbuta (ة → ه), alef maqsura (ى → ي) and diacritics are folded, so "اعاده تعيين كلمه المرور" finds "إعادة تعيين كلمة المرور". English queries are stemmed ("passwords" finds "password").
- The report flow does not submit until a category and a sub-reason are chosen, and ends on the next-steps screen.

**Tests.**
- Article API tests.
- Search indexing contract.
- Dialog spec.

### Epic 11. Marketplace location radius (SYS-12; #75, #76; #180 optional)

**Backend (`marketplace`).**
- Add `Listing.lat` and `Listing.lng`, geocoded from a curated list of Egyptian and Gulf cities. No external geocoder is needed at first.
- Add `UserMarketLocation{place, lat, lng, radius_km}`.
- Use a bounding-box plus haversine query. Move to PostGIS only if the owner approves (D4).
- Add `MarketplaceCategory.icon`.

**Frontend.**
- A location and radius dialog (10/20/40/60/80/100/250/500 km).
- A location chip on "Today's picks".
- Category icons.

**Acceptance criteria.**
- **Radius fixture.** The distance method is **haversine** (earth radius 6,371 km) after a bounding-box prefilter, not PostGIS (D4). With the user's point at Cairo (30.0444, 31.2357) and a listing stored at (30.0444, 31.5470), about 30 km away: the listing appears at a 40 km radius and is hidden at 20 km.
- Results are sorted by distance, then by newest.
- The listing city is still shown.
- A user's exact location is never exposed, only city-level data.

**Tests.**
- Distance query tests with the fixture above, plus the 0 km and 500 km edges.
- Privacy test.

---

## Phase C: depth (P2)

These epics come after Phase B. The scope table lists the gap rows; the acceptance table after it gives each epic its own testable criteria and tests.

| Epic | Scope (gap rows) |
|---|---|
| **12. Pages depth** | Reviews and recommendations (#62); Page invites (#63); deactivate and reactivate (#64); unread counts on manage cards (#65); Followers and Mentions tabs (#66); the "updated N ago" line (#67); **Tara Verified** badge with a request and admin approval flow (#71, owner policy D6); the Page-creation wizard (#178); `page.invite` and `page.review` notification kinds. |
| **13. Groups depth** | Member badges (#45); featured "N new" and a setup carousel (#46); Files tab (#49); managed-by-Page (#50); sort and pin in Your groups (#52); discover carousel (#53); Admin assist rules (#54); spam queue and keyword alerts (#55, in `moderation`); member profile in group with an admin summary chart (#58); the group-creation wizard (#179); the `group.member_joined` notification kind. |
| **14. Reels creation** | Tags, feeling, location and collaborator (#32); an audio track model and audio page (#33); a trim and crop timeline using ffmpeg in `media` (#34); captions, transcripts and audio descriptions as VTT plus text (#35); a two-step wizard (#36). |
| **15. Stories creative** | Stickers and mention stickers, multiple text blocks (#29); a settings page (#30). Music (#28) waits for #33. |
| **16. Tara Live** | `LiveBroadcast` in `chat` (reusing LiveKit plus LiveKit Ingress for RTMP/WHIP stream keys); a live hub (#39); live comments and reactions over `realtime`; VOD via egress into `media` (#40); scheduled lives linked to `gatherings`. Needs an infra sizing check (D8). |
| **17. Settings, privacy and friends depth** | Privacy checkup wizard (#106); reaction preferences (#107); media and accessibility keys (#108); the privacy-controls inventory in 02 SYS-21 (#164-#167, #169, #170, #173-#175); custom friend lists usable as audiences (#87); profile friends filters (#88); About sections and pinned details (#95, #96); Manage posts in bulk (#98); the More tab (#99); collaborator posts (#11); cross-post to groups (#15); Feeds filters Friends, Groups and Pages (#158); per-kind email channel (#160); download your information (#182); `friend.birthday` and `post.collaborator_invite` kinds. |
| **18. Memories** | An "On this day" page and a daily notification, plus hide people and date ranges (#103). Flip the `memories` menu item. |
| **19. Ads and business depth** | Billing: balance, threshold billing, daily limit, payment methods, activity, invoices (#145, payment provider D9); report builder, templates and export jobs (#142); account overview and alerts (#143, #151); duplicate, bulk edit and A/B tests (#147); ads transparency and an ad library (#150); bid strategies (#133); custom audiences with hashed lists (#136); ad rejection and disabled-account appeals (#184, #185); business verification, system users, partners and asset groups (#189-#191); `ad.account_status` and `ad.billing` kinds. |
| **20. Studio depth** | Column chooser and bulk select (#116); a Reel and bulk-upload chooser (#117); a chat Groups/Communities chip (#80); an "All tools" drawer (#4); a floating compose button (#3); Arabic-Indic digits if chosen (#154). |

**Phase C acceptance criteria and tests.** Each epic still follows ground rules 1–7 (events, privacy, RTL, tests in Arabic and English, light and dark).

| Epic | Acceptance criteria (each one is a test) | Tests |
|---|---|---|
| **12. Pages depth** | (1) **Tara Verified states** (#71): `draft → submitted → in_review → approved` or `rejected` (with a reason); `approved → revoked`. Only holders of the `verify.review` capability move a request; every illegal transition returns 409; every transition writes an admin audit row; the badge renders only in `approved`; a rejected Page can resubmit after 30 days. (2) A review with a recommendation is shown under its audience, and the Page summary shows the share of recommendations to the nearest whole percent. (3) Inviting the same person to the same Page twice within 30 days returns 409; the hub's "new" count equals unseen invites. (4) A deactivated Page returns 404 to non-members and reactivation restores its followers. | State-machine unit tests over every transition; audit test; review aggregate test; invite idempotency test; Playwright request → approve → badge. |
| **13. Groups depth** | (1) An Admin assist rule "decline posts with links from members who joined less than 14 days ago" declines a fixture post and writes an admin-log row. (2) A post containing an alert keyword appears in the keyword queue for admins and moderators only. (3) The "new member" badge shows for exactly 14 days after joining. (4) Three joins within 24 hours produce one aggregated `group.member_joined` row for each admin ("3 new members"). | Rule engine tests; queue permission tests; badge clock test with a frozen time; notification aggregation test. |
| **14. Reels creation** | (1) Trimming a 60-second fixture to 10–25 s produces a file whose duration (ffprobe) is 15 s ± 0.1 s. (2) An uploaded VTT shows captions with a toggle; an invalid VTT returns 400. (3) The audio page lists the reels that use a track, newest first, and hides reels the viewer may not see. (4) A collaborator who accepts sees the reel on both profiles; a declined invite shows it on the author's only. | Media pipeline tests with fixtures; VTT parser tests; audience test on the audio page; Playwright trim → publish. |
| **15. Stories creative** | (1) A mention sticker notifies the mentioned person only when they can view the story. (2) Text blocks are stored in normalised 0–1 coordinates and render at the same place in RTL and LTR. (3) Changing the default story audience in settings applies to the next story only. | Sticker notification test; coordinate snapshot tests in both directions; settings test. |
| **16. Tara Live** | (1) **Go-live → VOD:** `scheduled → live → ended → vod_processing → vod_ready` (or `vod_failed`, with a retry); viewers see the live badge only in `live`; a 30-minute fixture stream has its VOD within 10 minutes of ending, with a duration within ± 2 s. (2) `live.started` notifies each follower once per broadcast, even if the event is redelivered. (3) Live comments reach viewers in under 2 s at p95 in a 200-viewer load test. (4) A scheduled live creates a linked gathering, and cancelling one cancels the other. | State-machine tests; egress-to-media integration test; notification idempotency test; realtime load test; Playwright go live → end → watch VOD. |
| **17. Settings, privacy and friends depth** | (1) Each control in the SYS-21 inventory is enforced on the read or write path, for example "who can follow you = friends" makes a non-friend's follow return 403, and "look up by email = only me" makes an email search return nothing. (2) A post shared to a custom friend list is visible to list members and hidden from everyone else, in feed, search and notifications. (3) "Download your information" produces an archive with one JSON file per service; only the owner can download it and the link expires after 4 days. (4) The Feeds filters Friends, Groups and Pages return only posts from those sources. | Privacy matrix tests per control; audience leak test; export job test; feed filter tests. |
| **18. Memories** | (1) **Date matching across leap years:** a post from 29 February 2024 appears on 28 February in non-leap years (2025) and on 29 February in leap years (2028), and never twice in one year. (2) **Time zones:** matching uses the viewer's time zone, so a post made at 23:30 UTC on 4 November by a viewer in Cairo (UTC+2) is a 5 November memory. (3) Hidden people and hidden date ranges are excluded, and so are deleted posts and posts the viewer can no longer see. (4) At most one `memory.daily` notification per day. | Date-matching tests with a frozen clock over leap and non-leap years; time-zone tests; exclusion tests; notification rate test. |
| **19. Ads and business depth** | (1) **Threshold billing:** when unbilled spend reaches the threshold (for example $10), a charge is created within one aggregation cycle; if the monthly bill date comes first, the charge is made then; a failed charge sets the account to `unsettled` and pauses delivery until it is paid. (2) With a $5 daily spending limit, a fixture of 1,000 impressions at $0.01 spends at most $5.00 that day. (3) A customer list never stores a raw email or phone (a database check finds only 64-character hex hashes), and a list with fewer than 100 matches is `too_small` and cannot be selected. (4) A rejected ad allows one open appeal at a time, and the appeal creates a new review. (5) Business verification moves through its states with an audit row for each change. | Billing simulation with a fake provider; spend-limit test; hashing and minimum-size tests; appeal tests; verification state tests. |
| **20. Studio depth** | (1) The library column choice persists per user and comes back after a reload. (2) Selecting 50 rows and applying a bulk action updates all 50 in one request and reports any per-row failure. (3) The "All tools" drawer search finds "billing" from both "الفوترة" and "billing". (4) If D7 chooses Arabic-Indic digits, money and counts render as ٢٠٠٫٠٠ in Arabic and 200.00 in English. | Preference persistence test; bulk API test; drawer search spec; digit formatting spec. |

## Phase D: later (P3)

Pick these up after Phase C, on demand:
- Tara Assistant (#113, #82; needs D2), including the floating context-aware assistant button in the business and ads shells (#193);
- read receipts switch (#172), who can post on your profile (#168), profile lock (#176);
- events manager and datasets (#141);
- lookalikes (#137);
- automated rules (#148);
- campaign and opportunity scores (#144);
- naming templates and value rules (#146);
- monetization (#120);
- creator partnerships (#127);
- leads centre and instant forms (#69);
- Page broadcast channels (#70);
- life events (#12);
- comment dislike (#22);
- translation (#26);
- temporary avatar (#92);
- check-ins (#100);
- playlists (#119);
- weekly goals (#118);
- family centre (#109);
- state-media label (#8);
- marketplace group sales (#78);
- reply nudges (#81);
- keyboard shortcut map (#153);
- landing language footer (#156).

## Suggested order and rough size

| Order | Epic | Size | Depends on |
|---|---|---|---|
| 0 | Close the current round | – | – |
| 1 | Acting identity | L | – |
| 2 | Ads foundation | L | – |
| 3 | Comments parity | M | 1 (comment-as) |
| 4 | Composer parity | M | – |
| 5 | Profile parity | M | – |
| 6 | Groups core | M | – |
| 7 | Metrics and studio | M | 1 |
| 8 | Boost, audiences and reporting | L | 2, 7 |
| 9 | Tara Business | L | 1, 2 |
| 10 | Help centre | M | – |
| 11 | Marketplace radius | S–M | – |
| 12–20 | Phase C | – | As noted in each epic |

Epics 3, 4, 5, 6, 10 and 11 are independent of each other and can run in parallel with Epics 1 and 2.
