# 03. Gap matrix

One row per feature seen in the reference captures. Screen IDs point to [01-screens.md](01-screens.md) and systems to [02-systems-catalog.md](02-systems-catalog.md).

**Keys**

| Key | Meaning |
|---|---|
| **Status E** | Exists |
| **Status P** | Partial |
| **Status M** | Missing |
| **Effort S** | 1–2 days, one service or FE only |
| **Effort M** | 3–7 days, model + API + UI |
| **Effort L** | More than 1 week, new service area or cross-service |
| **P0** | Unblocks many others or a visible core gap |
| **P1** | Core parity |
| **P2** | Depth |
| **P3** | Nice to have |

Rows with status E are listed so the matrix stays complete; they need only a visual parity check.

**Inferred rows.** A screen cell that says *inferred* means the feature is standard in the reference product but no capture shows its screen. Its scope comes from this study, not from an observed layout.

**Dependency IDs used in the table**

| ID | What it is |
|---|---|
| **D-ACT** | Acting identity (SYS-29) |
| **D-ALB** | Album model |
| **D-MET** | Per-post or daily metrics pipeline |
| **D-ADS** | Ads hierarchy rework |
| **D-PORT** | Business portfolio |
| **D-LIVE** | Live broadcast model |
| **D-HELP** | Help article store |
| **D-AI** | Assistant model and hosting decision |

| # | System | Feature | Screens | Tara | Effort | Dependencies | Priority |
|---|---|---|---|---|---|---|---|
| 1 | Shell | Top bar, centre tabs, dropdowns, app grid | S01, S29 | E | – | – | – |
| 2 | Shell | Narrow width keeps everything in the top bar (no bottom bar) | S01 | P | S | Owner decision | P2 |
| 3 | Shell | Floating new-message button on every page | S08, S29 | P | S | – | P2 |
| 4 | Shell | "All tools" searchable site map | S56, S57 | P | S | – | P2 |
| 5 | Feed | Inline "· Join" / "· Follow" on suggested posts | S01, S29 | P | S | – | P1 |
| 6 | Feed | Hide card (reasons, snooze, unfollow, report, undo) | S24 | E | – | – | – |
| 7 | Feed | In-feed reels carousel | S25 | E | – | – | – |
| 8 | Feed | "State-controlled media" label | S24 | M | S | Policy decision | P3 |
| 9 | Composer | Text on coloured background (posts) | S07, S31 | P | S | – | P1 |
| 10 | Composer | Post title | S31 | M | S | – | P2 |
| 11 | Composer | Collaborator (co-author with accept) | S07, S40 | M | M | Notifications | P2 |
| 12 | Composer | Life event | S07 | M | M | – | P3 |
| 13 | Composer | GIF picker (posts and comments) | S05, S07 | M | M | GIF provider decision | P2 |
| 14 | Composer | AI-content label toggle and badge | S07, S33, S35 | M | S | – | P1 |
| 15 | Composer | Share to several groups (cross-post) | S07 | M | M | – | P2 |
| 16 | Composer | Boost toggle and owner "Create ad" on post, with the **boost-eligibility rule**: public, published, not removed or under review, not anonymous, not a reshare of someone else's post, and the user may advertise for the author. Acceptance: an ineligible post shows a **disabled "Promote unavailable" button with a reason tooltip** (S44) | S07, S30, S44 | M | M | D-ADS | P1 |
| 17 | Composer | Owner "See insights" on post | S30, S35 | P | M | D-MET | P1 |
| 18 | Composer | System posts (cover/avatar updated) with caption | S13, S23, S30 | P | S | – | P1 |
| 19 | Composer | Scheduling and drafts inside groups | S32 | M | S | – | P2 |
| 20 | Comments | Sort: most relevant, newest, all | S05 | M | S | – | P1 |
| 21 | Comments | Photo, GIF or sticker attachment | S05, S23 | M | M | #13 | P1 |
| 22 | Comments | Dislike (👎) | S05, S23, S30 | M | S | Owner decision | P3 |
| 23 | Comments | "Author" badge and "author reacted" | S23, S30 | M | S | – | P1 |
| 24 | Comments | Owner hides a comment (no owner-hide state on `Comment`, which has only `moderation_status` ok/removed; `CommentList.vue:361` "hide" only collapses replies) | S30 | M | S | – | P1 |
| 25 | Comments | Comment or reply as Page, with warning line | S05, S33, S35 | M | M | D-ACT | P0 |
| 26 | Comments | See translation | S23 | M | M | D-AI or MT service | P3 |
| 27 | Stories | Viewer, tray, reply, reactions, archive | S20, S24 | E | – | – | – |
| 28 | Stories | Music label | S20 | M | M | Audio library (#33) | P3 |
| 29 | Stories | Stickers and mention stickers, multiple text blocks | S20 | M | M | – | P2 |
| 30 | Stories | Story settings page | S20 | P | S | – | P2 |
| 31 | Reels | Pager, tabs, grid, saved, view counts | S19, S38 | E | – | – | – |
| 32 | Reels | Tags, feeling, location, collaborator on reels | S40 | M | S | #11 | P2 |
| 33 | Reels | Audio attribution and audio page | S19 | M | M | Licensing decision | P2 |
| 34 | Reels | Trim timeline and crop editor | S40 | M | L | media service (ffmpeg) | P2 |
| 35 | Reels | Closed captions, transcripts, audio descriptions | S40 | M | M | media service | P2 |
| 36 | Reels | Two-step Edit › Settings wizard with progress | S40 | P | S | – | P2 |
| 37 | Video | Theater zoom, pan, fullscreen, side panel | S05 | E | – | – | – |
| 38 | Video | Watch time, 3-second and 1-minute views | S17 | M | M | D-MET | P1 |
| 39 | Live | Live hub, go live, stream key, schedule, past/live/scheduled | S39 | M | L | LiveKit ingress | P2 |
| 40 | Live | Live comments and reactions, VOD after end | S39 | M | L | D-LIVE | P2 |
| 41 | Live | Live video ad | S39 | M | M | D-LIVE, D-ADS | P3 |
| 42 | Groups | Header, privacy, invite, join, tabs, manage basics | S31, S32 | E | – | – | – |
| 43 | Groups | Feed sort (recent activity, new posts, relevant) | S31 | M | S | – | P1 |
| 44 | Groups | Anonymous posting with stable aliases | S01, S31, S32 | M | M | Privacy review | P1 |
| 45 | Groups | Member badges (top contributor, new member) | S31, S33 | M | M | Group activity counts | P2 |
| 46 | Groups | Featured with "N new" and setup carousel | S31, S32 | P | S | – | P2 |
| 47 | Groups | Guides (units) tab | S31 | M | M | – | P3 |
| 48 | Groups | Open questions (Q&A) tab | S31 | M | M | – | P3 |
| 49 | Groups | Files tab | S31, S32 | M | M | media | P2 |
| 50 | Groups | "Managed by Page" banner | S31 | M | S | D-ACT | P2 |
| 51 | Groups | Last visited, last active, posts per day | S18, S45, S46 | M | S | – | P1 |
| 52 | Groups | Your groups sort and card menu with pin | S46 | P | S | #51 | P2 |
| 53 | Groups | Discover split: friends' carousel and suggestions grid | S45 | P | S | – | P2 |
| 54 | Groups | Admin assist auto-rules | S32 | M | M | moderation | P2 |
| 55 | Groups | Potential-spam queue and keyword alerts | S32 | M | M | moderation | P2 |
| 56 | Groups | Admin activity log | S32 | M | S | – | P1 |
| 57 | Groups | Group status (quality) and overview | S32 | M | M | – | P3 |
| 58 | Groups | Member profile in group with admin summary and chart | S33 | M | M | #45, #56 | P2 |
| 59 | Groups | Add features toggles (choose enabled tabs) | S32 | M | S | – | P3 |
| 60 | Pages | Hub, create, header, follow, message, team, transparency | S09, S26, S34 | E | – | – | – |
| 61 | Pages | Act as Page (switch banner, Page mode) | S27, S34, S35 | M | L | D-ACT | P0 |
| 62 | Pages | Reviews and recommendations, rating summary | S34, S35, S36 | M | M | moderation | P2 |
| 63 | Pages | Page invites ("invite friends to follow") with new count | S26, S44 | M | M | notifications | P2 |
| 64 | Pages | Deactivate and reactivate lifecycle | S26 | P | S | – | P2 |
| 65 | Pages | Unread notifications and messages on manage cards | S26 | P | S | chat, notification counts | P2 |
| 66 | Pages | Tabs: Followers, Photos, Mentions, More | S09, S34 | P | S | D-ALB for photos | P1 |
| 67 | Pages | "Profile updated N ago" in transparency | S09 | P | S | – | P3 |
| 68 | Pages | Promote (boost Page or post), using the boost-eligibility rule in #16. Acceptance: a disabled button with a reason tooltip for ineligible posts | S26, S34, S44 | M | M | D-ADS | P1 |
| 69 | Pages | Leads centre (instant forms) | S34, S56 | M | L | D-ADS | P3 |
| 70 | Pages | Community broadcast channel | S09 | M | M | chat | P3 |
| 71 | Verification | Verified badge (Tara-branded) and request flow | S09, S19, S41 | M | M | Owner policy decision | P2 |
| 72 | Events | List, create, detail, RSVP, invites | S36 | E | – | – | – |
| 73 | Events | Profile Events collection and group Events tab check | S31, S36 | P | S | – | P2 |
| 74 | Marketplace | Browse, picks, detail, seller, compare, saves | S14 | E | – | – | – |
| 75 | Marketplace | Geo location and radius km | S14 | P | M | PostGIS or haversine | P1 |
| 76 | Marketplace | Category icons | S14 | P | S | – | P2 |
| 77 | Marketplace | Seller status / account health | S14 | M | M | moderation | P2 |
| 78 | Marketplace | Buy/sell group listings feed and "new items" banner | S14 | M | M | groups | P3 |
| 79 | Chat | Dropdown, folders, voice, calls, mute | S02 | E | – | – | – |
| 80 | Chat | Groups and Communities filter chips | S02 | P | S | – | P2 |
| 81 | Chat | Reply nudges | S02 | M | S | – | P3 |
| 82 | Chat | Bots (marketplace assistant) | S02 | M | M | D-AI | P3 |
| 83 | Notifications | Dropdown, sections, chips, badges | S03 | E | – | – | – |
| 84 | Notifications | Missing kinds (full table in 02 SYS-14): group member joined (to admins), scheduled post published, Page invite, collaborator invite, birthday, memories, live started, review received, ad-account status and billing, Page activity while switched to the Page. Each ships with its owning epic | S03 | P | M (about half a day per kind, 11 kinds) | Each epic | P1 |
| 85 | Search | Global search and settings search | S06 | E | – | – | – |
| 86 | Friends | Hub, PYMK, requests, birthdays | S08 | E | – | – | – |
| 87 | Friends | Custom friend lists (usable as audiences) | S08 | P | M | graph and post audiences | P2 |
| 88 | Friends | Profile friends filters: recently added, birthdays, current city | S36 | P | S | – | P2 |
| 89 | Profile | Hero, cover reposition, avatar crop, details, filters, grid | S11, S12, S13, S30 | E | – | – | – |
| 90 | Profile | Alternate name and other names | S12, S22, S30 | M | S | – | P1 |
| 91 | Profile | Note bubble on avatar | S12, S30 | M | S | – | P2 |
| 92 | Profile | Temporary profile picture | S13 | M | S | Celery beat | P3 |
| 93 | Profile | Avatar description becomes the post caption | S13 | M | S | #18 | P1 |
| 94 | Profile | Professional mode (category, Dashboard button) | S06, S22, S30 | M | M | – | P1 |
| 95 | Profile | About sections: category, hobbies, interests, travel, names, communities | S36 | P | M | – | P2 |
| 96 | Profile | Pinned details | S36 | M | S | – | P2 |
| 97 | Profile | Typed contact handles with network icons | S23, S35 | P | S | – | P2 |
| 98 | Profile | Manage posts (bulk archive, delete, hide, untag) | S30 | M | M | – | P2 |
| 99 | Profile | More tab: Videos, Check-ins, Groups, Events, Reviews | S30, S36 | P | M | #62, #100 | P2 |
| 100 | Profile | Places visited (check-ins) | S36 | M | M | Place entity | P3 |
| 101 | Photos | Album model, user-created albums, album picker tab | S11, S36, S37 | P | M | – | P1 |
| 102 | Saved | Collections | – | E | – | – | – |
| 103 | Memories | On this day page and notification | S24 | M | M | – | P2 |
| 104 | Settings | Settings home, search, most visited | S06 | E | – | – | – |
| 105 | Settings | Default audience | S06 | M | S | – | P1 |
| 106 | Settings | Privacy checkup wizard | S06 | M | M | – | P2 |
| 107 | Settings | Reaction preferences (hide counts) | S06 | M | S | – | P2 |
| 108 | Settings | Media and accessibility preferences (autoplay, reduce motion) | S06 | P | S | – | P2 |
| 109 | Settings | Family centre / supervision | S06 | M | L | Owner decision | P3 |
| 110 | Settings | Multi-profile switcher in account menu | S04 | M | M | D-ACT | P0 |
| 111 | Help | Help centre (categories, articles, search, feedback) | S10 | M | M | D-HELP | P1 |
| 112 | Help | Report a problem dialog (Ctrl+B) | S04, S39 | M | S | – | P1 |
| 113 | Assistant | Tara assistant panel in help | S10 | M | L | D-AI, D-HELP | P3 |
| 114 | Studio | Home, insights, library, planner, engagement | S15, S16, S17 | E | – | – | – |
| 115 | Studio | KPI deltas vs previous period, viewers and follows tiles | S15 | P | S | D-MET | P1 |
| 116 | Studio | Library column chooser and bulk select | S17 | P | S | – | P2 |
| 117 | Studio | Add-post chooser with Reel and bulk upload | S16 | P | M | – | P2 |
| 118 | Studio | Week strip with empty-day nudge, weekly goals, survey | S15 | M | S | – | P3 |
| 119 | Studio | Playlists | S16 | M | M | – | P3 |
| 120 | Studio | Monetization (eligibility, earnings) | S15, S42 | M | L | Payments decision | P3 |
| 121 | Studio | Page-scoped studio (insights, planner for a Page) | S27, S34 | M | M | D-ACT | P1 |
| 122 | Business | Portfolio model, members (admin full control, employee partial access), assets, per-asset task matrix (Pages: content, messages, community, ads, insights, revenue; ad accounts: manage, advertise, analyze) | S41, S42 | M | L | D-ACT | P1 |
| 123 | Business | Asset switcher | S42, S44 | M | M | D-PORT | P1 |
| 124 | Business | Business home (to-do, content tabs, boost, recent ads, tips) | S44 | M | M | D-PORT, D-ADS | P1 |
| 125 | Business | Unified inbox (messages and comments) | S44 | P | M | chat, post | P2 |
| 126 | Business | Settings: people, partners, requests (access-request approval flow), linked ad accounts, role × action matrix in 02 SYS-24 | S41 | M | M | D-PORT | P2 |
| 127 | Business | Creator marketing hub / partnerships | S43 | M | L | D-PORT, D-ADS | P3 |
| 128 | Ads | Ad account entity: multi, owner person or portfolio, timezone, spend cap, switcher | S49 | P | M | D-PORT optional | P0 |
| 129 | Ads | Objectives: awareness, traffic, engagement, leads, app, sales | S47 | P | S | – | P1 |
| 130 | Ads | Campaigns / Ad sets / Ads data table with toggles and sort | S47, S50 | M | M | – | P0 |
| 131 | Ads | Create wizard with two-tab Create modal (new campaign, or new ad set or ad in an existing campaign), tree pane, breadcrumb, autosave, the Campaign, Ad set and Ad step fields in 02 SYS-25, per-step validation, and Next disabled until the step is valid | S47, S48 | M | M | #130 | P0 |
| 132 | Ads | Budget: CBO vs ABO, daily or lifetime, projections | S48 | M | M | – | P1 |
| 133 | Ads | Bid strategy (highest volume, cost cap, bid cap) and auction | S48 | M | M | Delivery engine | P2 |
| 134 | Ads | Draft layer with "Review and publish (N)" and discard | S47, S48, S50 | P | M | – | P1 |
| 135 | Ads | Saved audiences (location, age, gender, interests, language) with include, exclude and narrow | S53 shortcuts only (inferred, no audience screen captured) | M | M | Targeting evaluator | P1 |
| 136 | Ads | Custom audiences: Page engagement, video viewers by % watched, lead form, Tara Events attendees, marketplace activity, website data source, app activity, customer list (SHA-256 hashed, minimum match size); retention days, "too small" state, sharing within a portfolio | S53 shortcuts only (inferred, no audience screen captured) | M | L | Privacy review, #141 | P2 |
| 137 | Ads | Lookalike audiences | S53 shortcuts only (inferred, no audience screen captured) | M | L | #136 | P3 |
| 138 | Ads | Placements: automatic or manual (feed, stories, reels, marketplace, search, right rail) and controls. Needs a schema change: `AdSet.placement` is one choice field today, manual multi-placement needs a list | S53 | P | M | Ad slots in stories and reels | P1 |
| 139 | Ads | Creative formats (image, video, carousel, existing post) and placement preview | S47, S48 | P | M | – | P1 |
| 140 | Ads | Reporting columns presets, breakdowns, grouping, date range, charts, export | S47, S52 | P | M | D-MET (ads insights daily) | P1 |
| 141 | Ads | Events manager: datasets, conversion events, custom conversions | S55 | M | L | – | P3 |
| 142 | Ads | Report builder, templates, export jobs | S52 | M | M | #140 | P2 |
| 143 | Ads | Account overview, alerts, learning phase | S51 | M | M | – | P2 |
| 144 | Ads | Campaign score and recommendations, opportunity score | S48, S51 | M | M | – | P3 |
| 145 | Ads | Billing: balance, threshold, daily limit, payment methods, activity, invoices | S54 | P | L | Payment provider decision | P1 |
| 146 | Ads | Ad settings: naming templates, value rules, beneficiary/payer | S53 | M | S | – | P3 |
| 147 | Ads | Duplicate, bulk edit, A/B test | S47 | M | M | #130 | P2 |
| 148 | Ads | Automated rules | S56 | M | M | #140 | P3 |
| 149 | Ads | Ads manager shell (icon rail, account selector, all tools) | S47–S57 | M | S | #128 | P1 |
| 150 | Ads | Ads transparency ("why this ad", ad library) | S24, S53 | P | M | – | P2 |
| 151 | Trust | Advertiser account integrity states (disabled, verify) | S51, S54 | M | S | – | P2 |
| 152 | A11y | Arrow-key reposition and crop | S12, S13 | E | – | – | – |
| 153 | A11y | Keyboard shortcut map (Ctrl+K, Ctrl+B) | S04, S44 | M | S | – | P3 |
| 154 | i18n | Arabic-Indic digits for money and counts, LTR islands | S47–S54 | P | S | Owner decision | P2 |
| 155 | Auth | Landing, login, register, forgot | S28 | E | – | – | – |
| 156 | Auth | Language links footer on landing | S28 | P | S | – | P3 |
| 157 | Feed | Feeds entry with Favorites and chronological filters and a manage page (`menuCatalog.ts:156-157`, `FEED_MODES`) | S24 | E | – | – | – |
| 158 | Feed | Feeds filters: Friends, Groups, Pages | S24 | M | S | – | P2 |
| 159 | Composer | Hashtag page (dedicated route, top and recent, post count); linking, search and trending already exist | S03 | P | S | – | P2 |
| 160 | Notifications | Per-kind channel preferences including email (in-app and push exist) | S03 (inferred) | P | M | Email delivery | P2 |
| 161 | Notifications | Row `…` menu: mark read, remove, turn off this type (`NotificationItem.vue`) | S03 | E | – | – | – |
| 162 | Privacy | Who can send you friend requests (`RelationshipSettings.friend_requests_from`) | S06 (inferred) | E | – | – | – |
| 163 | Privacy | Who can see your friends list (`friends_list_visibility`) | S06 (inferred) | E | – | – | – |
| 164 | Privacy | Who can look you up by email or phone | S06 (inferred) | M | S | search | P2 |
| 165 | Privacy | Search-engine indexing of the profile | S06 (inferred) | M | S | – | P2 |
| 166 | Privacy | Who can follow you | S06 (inferred) | M | S | graph | P2 |
| 167 | Privacy | Account-level public-post comment controls and keyword filters (per-post `comment_policy` exists) | S06 (inferred) | P | M | – | P2 |
| 168 | Privacy | Who can post on your profile | S06 (inferred) | M | S | Profile-wall posting | P3 |
| 169 | Privacy | Tag review and profile review queue (`who_can_tag` exists) | S06 (inferred) | P | M | – | P2 |
| 170 | Privacy | Story "hide story from" list (`Story.audience`, close friends exist) | S20 (inferred) | P | S | – | P2 |
| 171 | Privacy | Active status switch (`SettingsView.vue` `#active-status`) | S02 | E | – | – | – |
| 172 | Privacy | Read receipts switch | S02 (inferred) | M | S | chat | P3 |
| 173 | Privacy | Blocking by category: messages, app and event invites, Pages (user block exists) | S06 (inferred) | P | M | – | P2 |
| 174 | Privacy | Restricted list screen in settings (`RestrictRelation` exists) | S06 (inferred) | P | S | – | P2 |
| 175 | Privacy | Limit the audience of past posts | S06 (inferred) | M | S | – | P2 |
| 176 | Privacy | Profile lock | S06 (inferred) | M | M | Owner decision | P3 |
| 177 | Auth | Post-signup onboarding: photo, find friends, interests | inferred | M | M | – | P1 |
| 178 | Pages | Page-creation wizard: name, category, bio → images → contact and link → invite friends | inferred | P | S | #63 | P2 |
| 179 | Groups | Group-creation wizard: name, privacy, visibility, invite | inferred | P | S | – | P2 |
| 180 | Marketplace | Listing types (item, vehicle, rental) and a multi-step listing form | S14 entry; form inferred | M | M | – | P2 |
| 181 | Settings | Account deactivation and deletion (`DeactivateAccount.vue`, `DeleteAccount.vue`, intel deletion) | inferred | E | – | – | – |
| 182 | Settings | Download your information (export archive across services) | inferred | M | L | Every service | P2 |
| 183 | Trust | Multi-step report flow: category, sub-reason, details, confirm, next steps | inferred | P | S | – | P1 |
| 184 | Ads | Ad rejection appeal (request another review) | inferred | M | S | `AdReview` | P2 |
| 185 | Ads | Ad-account-disabled appeal and request review | S51, S54 | M | M | #151 | P2 |
| 186 | Ads | Special ad categories (housing, employment, credit, social issues) lock age, gender and postcode targeting | inferred (campaign step) | M | S | #131, #135 | P2 |
| 187 | Ads | Audience size estimate gauge | inferred | M | M | #135 | P2 |
| 188 | Ads | Account-level controls: minimum age, excluded locations, excluded placements | S53 | M | S | #135 | P2 |
| 189 | Business | Business verification flow and states | S41, S51 | M | M | D-PORT | P2 |
| 190 | Business | System users and partner portfolios | S41 | M | M | D-PORT | P3 |
| 191 | Business | Asset groups | S41 | M | S | D-PORT | P3 |
| 192 | Business | Require 2FA for portfolio members | S41 (inferred) | M | S | D-PORT | P2 |
| 193 | Assistant | Floating context-aware assistant button in the business and ads shells | S41, S44, S47, S53 | M | M | D-AI | P3 |

## Totals

193 rows in all: 26 exist (E), 52 are partial (P) and 115 are missing (M).

Rows #1-#156 are the first pass. Rows #157-#193 were added in the review pass (Feeds, hashtags, notification channels, the privacy-controls inventory, creation and lifecycle flows, ads audience rules and appeals, business roles, the floating assistant). Row #24 moved from P to M.

| | P0 | P1 | P2 | P3 | Total |
|---|---|---|---|---|---|
| Missing (M) | 5 | 26 | 49 | 35 | 115 |
| Partial (P) | 1 | 16 | 33 | 2 | 52 |
| **Gaps** | **6** | **42** | **82** | **37** | **167** |

**The P0 set:**
- Acting identity: comment as Page (#25), act as Page (#61) and the profile switcher (#110).
- Ads foundation: ad-account rework (#128), the campaigns table (#130) and the create wizard (#131).

Everything in the Pages, Business and Ads systems depends on these six rows.
