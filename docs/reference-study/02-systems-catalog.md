# 02. Systems catalog

This catalog describes each system shown in the reference captures. For every system it covers purpose, sub-features, screens, data entities, key flows, permissions and Tara's current status.

**Status labels:**
- **Exists**: built and wired end to end.
- **Partial**: some pieces are built, gaps remain.
- **Missing**: no model and no screen.

**Path conventions:**
- Evidence paths are relative to the repo root.
- `FE` means `frontend/web/src`.
- Screen IDs (`Sxx`) point to [01-screens.md](01-screens.md).
- Tara items flagged `built:false` in `FE/components/layout/menuCatalog.ts` are hidden from navigation by design.

**Architecture constraints applied below:**
- **Microservice ownership.** Data stays inside the service that owns it. The services are `identity`, `profile` (profiles, Pages, groups), `post` (posts, comments, reels, stories, gatherings/events), `feed` (ranking, intel), `graph`, `chat` (chat, calls), `notification`, `search`, `media`, `marketplace`, `ads`, `moderation`, `admin`, `realtime` and `bff`.
- **Outbox events.** Cross-service changes travel as `OutboxEvent` rows using the `tara_events` schemas.
- **Arabic RTL first.**
- **Privacy rules.** Field-level audiences, blocks, and minimal private signals.

---

## SYS-01 Shell and navigation

- **Purpose.** Provide one consistent frame for every page.
- **Sub-features:**
  - fixed top bar (logo, search, five centre tabs, app grid, chat, notifications, avatar menu);
  - start rail with "See more" and shortcuts;
  - end rail (birthdays, contacts, sponsored);
  - floating compose-message button;
  - a narrow-width collapse that keeps the top bar and adds **no bottom bar**;
  - an "All tools" site map;
  - footer links.
- **Screens.** S01, S24, S29, S56.
- **Entities.**
  - `Shortcut` (pinned groups and Pages).
  - Per-user nav preferences.
- **Flows:**
  - switch tab;
  - open a dropdown (chat, notifications, menu);
  - pin a shortcut.
- **Permissions.** Signed-in users. A guest sees the landing page instead.
- **Tara status: Exists.**
  - Shell: `FE/components/layout/AppNavbar.vue`, `navItems.ts`, `MainMenu.vue`, `ProfileMenu.vue`, `LeftSidebar.vue`, `RightSidebar.vue`, `shortcuts.ts`, `menuCatalog.ts` (app grid with `built` flags), `chat/ChatDock.vue`.
  - Gap: Tara has `MobileBottomNavigation.vue`, but the reference keeps everything in the top bar.
  - Gap: no ads- or business-specific "All tools" drawer.
  - Note: business and ads surfaces use their own light shell with an icon rail and a floating assistant button (01, "Business and ads chrome").

## SYS-02 Home feed

- **Purpose.** Rank content from friends, followed accounts, groups and Pages, plus suggestions and ads.
- **Sub-features:**
  - stories tray;
  - composer card;
  - ranked posts;
  - suggested group or Page posts with inline "· Join" / "· Follow";
  - hide (×) with a reason card, snooze for 30 days, unfollow, report and undo;
  - in-feed Reels carousel;
  - sponsored posts;
  - hover cards;
  - "state-controlled media" labels;
  - **Feeds** entry in the start rail (S24): an alternative feed with filters **Favorites, Friends, Groups, Pages** and a **chronological** (most recent) order, plus a manage page for favorites and snoozes.
- **Screens.** S01, S24, S25, S29.
- **Entities.**
  - `FeedItem` (rank signals).
  - `HideFeedback {reason}`.
  - `AuthorSnooze {until}`.
  - `Impression`.
  - `Suggestion {reason}`.
  - `SponsoredSlot`.
- **Flows:**
  - load the feed page by cursor;
  - hide an item, then pick a reason;
  - undo a hide;
  - join a group or follow a Page inline.
- **Permissions.** The viewer must be allowed by the post's audience and by blocks.
- **Tara status: Exists, with gaps.**
  - Built: `services/feed` (feed, intel ranking, impressions); `FE/components/post/HideFeedbackCard.vue`, `SponsoredCard.vue`, `reels/ReelsRail.vue`, `social/NameHoverCard.vue`, `views/FeedPreferencesView.vue`.
  - Built (Feeds): `FE/components/layout/menuCatalog.ts:156-157` has `feeds` (opens `/home?mode=for_you`) and `feedPreferences` (`/feeds/manage`), both `built:true`. `FE/services/feed.ts` `FEED_MODES` = `for_you`, `recent` (chronological), `favorites`, `following`; favorites live in `graph` `FavoriteRelation`.
  - Feeds filter check against the reference: Favorites **exists**, chronological **exists** (`recent`), Friends, Groups and Pages filters are **missing** (no such modes; `following` mixes friends and follows). See 03 #158.
  - Partial: the inline "· Join / · Follow" link in the suggested-post header needs checking.
  - Missing: state-media labels.

## SYS-03 Posts and composer

- **Purpose.** Create, edit and schedule posts as a person, a Page or inside a group.
- **Sub-features:**
  - audience;
  - tag people;
  - feeling;
  - location;
  - poll;
  - photo/video drag and drop;
  - schedule and drafts;
  - share to story;
  - live preview;
  - comment policy;
  - **collaborator (co-author)**;
  - **life event**;
  - **GIF**;
  - **text background ("Aa")**;
  - **post title** (seen in groups);
  - **AI-content label**;
  - **cross-post to groups**;
  - call CTA;
  - monetization;
  - **boost toggle**;
  - system stories ("updated cover photo", with an avatar caption);
  - owner "See insights / Create ad" strip;
  - **hashtags**: `#tag` in the body is linked in the brand colour (seen in a feed post behind the S03 dropdown); a tag opens a **hashtag page** (posts using the tag, top and recent); hashtags appear in search suggestions and in a Hashtags results tab; trending tags.
- **Screens.** S03 (hashtag in a feed post), S07, S13, S30, S31, S35.
- **Entities.**
  - `Post {author_type, author_id, group_id, page_id, type, body, title, bg_style, audience, feeling, location, publish_at, state, ai_label, story_kind}`.
  - `PostMedia`.
  - `PostTag`.
  - `Poll`.
  - `PostCollaborator {post, account, accepted_at}`.
  - `LifeEvent {kind, date}`.
  - `CrossPost {post, group}`.
  - `BoostRequest {post, campaign}`.
  - `Hashtag {tag}` and `PostHashtag {post, hashtag}` (already built).
- **Flows:**
  - compose and publish;
  - tap a hashtag, then browse its posts;
  - compose and schedule (the planner shows it);
  - invite a collaborator, who accepts, after which the post appears on both profiles;
  - boost on publish, which creates an ads draft;
  - label as AI.
- **Permissions:**
  - the author or Page editor;
  - group posting rules and approval;
  - boosting follows the **boost-eligibility rule** in 03 #16: an ineligible post shows a disabled "Promote unavailable" button with the reason in a tooltip (S44).
- **Tara status: Partial.**
  - Built: `services/post/posts/models.py` `Post` (types text/image/video/link/share/poll/reel; `feeling`, `location`, `publish_at`, `state`, `author_type user|page`), `Poll*`, `PostTag`, `Mention`, `PostSettings`; `FE/components/post/ComposerDialog.vue`, `ComposerPreview.vue`, `PostComposerMeta.vue`, `MediaGrid.vue`.
  - Missing: collaborator, life event, GIF, text background on posts (stories only, `FE/services/stories.ts`), title, AI label, cross-post (single `group_id`), boost, and a system-story kind.
  - Missing: scheduling inside groups (the composer says it is not offered there).
  - Hashtags: **Partial.** Built: `Hashtag` and `PostHashtag` (`services/post/posts/models.py:343-351`); hashtag suggestions and a Hashtags tab (`FE/lib/search.ts` `SUGGEST_ORDER`, `SearchView.vue` hashtag posts); trending tags from `PublicPostHashtag` (`services/search/searchsvc/history.py`). Missing: a dedicated hashtag page (a tag currently routes to search with `q=#tag`, `FE/lib/searchRoutes.ts:15`) with top/recent sort and a post count. See 03 #159.

## SYS-04 Comments and reactions

- **Purpose.** Hold threaded conversation and reactions on posts, media, reels and stories.
- **Sub-features:**
  - seven post reactions plus a reactions dialog;
  - comment like, reply and edit, with an "edited" marker;
  - "show N replies";
  - **comment dislike**;
  - **owner hide**;
  - **"Author" badge** and an "author reacted" badge;
  - **sort** (most relevant, newest, all);
  - **media, GIF or sticker attachment**;
  - **comment as Page** with a "you are commenting as" warning;
  - **See translation**;
  - reporting.
- **Screens.** S05, S23, S30, S33, S35.
- **Entities.**
  - `Comment {author_type, author_id, parent, body, attachment_media_id, gif_ref, sticker_id, state, edited_at}`.
  - `CommentReaction {type incl. dislike}`.
  - `CommentState (hidden_by_owner)`.
  - `CommentTranslation` (cache).
- **Flows:**
  - comment;
  - reply, with a mention of the parent author;
  - hide (visible only to the owner);
  - switch acting identity;
  - change sort.
- **Permissions:**
  - post comment policy;
  - only the post owner can hide;
  - Page roles decide who can comment as the Page.
- **Tara status: Partial.**
  - Built: `Comment`, `CommentReaction`, `CommentReport` (`services/post/posts/models.py:263-314`); `FE/components/post/CommentList.vue`, `CommentItem.vue`, `CommentInput.vue` (emoji only), `ReactionPicker.vue`, `ReactionsDialog.vue`, `lib/commentThreads.ts`.
  - Missing: sort (ordered by `created_at` only), attachments, dislike, author badge, comment-as, translation.
  - **Missing: owner hide.** `Comment` (`services/post/posts/models.py:263-298`) has only `moderation_status` ok|removed and no owner-hidden state. The "hide" in `CommentList.vue:361` only collapses a reply thread (`post.hideReplies`); it is not a moderation action.

## SYS-05 Stories

- **Purpose.** Share 24-hour full-screen cards.
- **Sub-features:**
  - tray with a Create card;
  - viewer with progress segments;
  - side list with "N new cards" and a seen ring;
  - reply to DM;
  - seven quick reactions;
  - viewers list;
  - archive;
  - **story settings**;
  - **music**;
  - **stickers and mention stickers**;
  - multiple text blocks;
  - close friends.
- **Screens.** S20, S24.
- **Entities.**
  - `Story {segments[], audience, bg_style, music_track_id}`.
  - `StorySticker {kind, x, y, payload}`.
  - `StoryView`.
  - `StoryReaction`.
  - `CloseFriends`.
- **Flows:**
  - create;
  - view (marks it seen);
  - reply (sends a chat message);
  - react;
  - archive.
- **Permissions.** Story audience and close-friends list. Blocks apply.
- **Tara status: Partial.**
  - Built: `services/post/stories/*`; `FE/components/stories/StoriesRail.vue`, `StoryViewer.vue`, `StoryCreateDialog.vue` (photo, text, background), `CloseFriendsDialog.vue`; `views/StoryArchiveView.vue`.
  - Missing: music, stickers, mention stickers and a story settings page.

## SYS-06 Reels

- **Purpose.** Short vertical video with an endless pager.
- **Sub-features:**
  - For you, Following and Profile tabs;
  - pager;
  - like, comment, share and more;
  - follow;
  - **audio attribution page**;
  - profile reels grid (yours / saved) with view counts;
  - **editor:**
    - two-step wizard;
    - trim timeline;
    - crop;
    - **music lane**;
    - **captions, audio descriptions and transcripts**;
    - tags, feeling, location, collaborator.
- **Screens.** S19, S25, S38, S40.
- **Entities.**
  - `Reel {media, cover, caption, audio_track_id, trim_start_ms, trim_end_ms, captions_vtt_media_id, collaborators}`.
  - `AudioTrack {title, owner, original_reel}`.
  - `ReelView`.
  - `ReelHide`.
- **Flows:**
  - upload, edit, set options, publish;
  - open the audio page to see reels that use the sound.
- **Permissions.** Audience. Only the author edits.
- **Tara status: Partial.**
  - Built: `services/post/reels/models.py` (`Reel`, `ReelView`, `ReelHide`, `cover_media_id`, `duration_ms`); `FE/components/reels/ReelPager.vue`, `ReelPlayer.vue`, `ReelGrid.vue`, `CreateReelDialog.vue`, `ReelsRail.vue`.
  - Missing: audio model, trim/timeline, captions, tags on reels, and the two-step wizard.

## SYS-07 Video (Watch) and media theater

- **Purpose.** Full-screen media viewing and a video hub.
- **Sub-features:**
  - theater with zoom, pan, fullscreen and prev/next;
  - side panel with the post and comments;
  - video tab;
  - "videos are now reels" merge banner;
  - watch-time metrics.
- **Screens.** S05, S17.
- **Entities.**
  - `PostMedia`.
  - `VideoView {watch_ms, completed}` (for 3-second, 1-minute and average watch time).
- **Tara status: Partial.**
  - Built: `FE/components/post/MediaTheater.vue`, `PostTheaterPanel.vue`, `views/VideosView.vue`, `services/media`.
  - Missing: watch-time telemetry for videos (only `Reel.view_count` and feed impressions).

## SYS-08 Live video

- **Purpose.** Real-time broadcast to a profile, Page or group.
- **Sub-features:**
  - live hub (Go live, Create live ad);
  - saved settings presets;
  - host identity and destination;
  - camera or streaming software with a stream key;
  - schedule;
  - tabs for past, live now and scheduled;
  - live comments and reactions;
  - VOD after the end;
  - report a problem.
- **Screens.** S39 (and the Live entry in the S07/S24/S30 composers).
- **Entities.**
  - `LiveBroadcast {host_type, host_id, destination_type, destination_id, title, audience, status scheduled|live|ended, stream_key_hash, scheduled_at, started_at, ended_at, vod_media_id}`.
  - `LiveViewerStat`.
  - `LiveComment` (or reuse `Comment` on the broadcast's post).
- **Flows:**
  - set up, preview, go live (this creates a post);
  - end, which turns the stream into VOD and updates the post.
- **Permissions:**
  - the host;
  - Page roles for a Page destination;
  - group admins can disable live.
- **Tara status: Missing.**
  - `menuCatalog.ts` has `live built:false`.
  - LiveKit is used only for 1:1 and group calls (`services/chat/calls/livekit.py`, `Call`, `CallParticipant`), so it can be reused as the WebRTC ingest.

## SYS-09 Groups

- **Purpose.** Communities with their own feed, roles and moderation.
- **Sub-features:**
  - **Hub:** feed, discover (a friends' groups carousel plus a suggestions grid), your groups with sort, managed and joined lists with "last active", create.
  - **Group page:**
    - header with privacy and visibility, facepile, invite, share and a "Joined ▾" menu;
    - tabs: Discussion, Featured, Guides, Open questions, Members, Events, Media, Files, About;
    - feed sort;
    - "managed by Page" banner.
  - **Posting:**
    - **anonymous posting** with stable aliases;
    - **member badges** (top contributor, admin, new member);
    - titles;
    - featured items with a "N new" count.
  - **Admin:**
    - pending posts, requests, rules, reports;
    - **Admin assist auto-rules**;
    - **potential spam queue**;
    - **scheduled posts**;
    - **admin activity log**;
    - **keyword alerts**;
    - **group status/quality**;
    - community roles;
    - **add features**.
  - **Member profile in a group:**
    - posts and comments;
    - admin-only summary: 90-day moderation, 30-day participation chart, badges.
  - **Stats and actions:**
    - "N posts a day";
    - "you last visited";
    - pin a group.
- **Screens.** S01, S18, S31, S32, S33, S45, S46.
- **Entities.**
  - `Group {privacy, visibility, managed_by_page_id, cover, member_count, last_activity_at, posts_per_day (derived), features[]}`.
  - `GroupMember {role, joined_at, last_visited_at, pinned, anon_alias, badges[]}`.
  - `GroupRule`.
  - `GroupReport`.
  - `GroupFeatured {post, seen_by}`.
  - `GroupGuide {title, units[]}`.
  - `GroupFile {media}`.
  - `GroupQuestion`.
  - `AdminAssistRule {criterion, action}`.
  - `GroupKeywordAlert`.
  - `GroupAdminLog`.
  - `MemberBadge`.
- **Flows:**
  - join (approval when private);
  - post anonymously (an admin approves, the alias is stable per member);
  - an admin creates an auto-rule (for example "decline posts with links from members < 2 weeks");
  - schedule a group post;
  - **create a group (wizard, inferred, no capture):** name → privacy (public or private) and visibility (visible or hidden) → invite friends → optional cover and description.
- **Permissions:**
  - admin, moderator, member;
  - real identities behind aliases are visible to admins only;
  - the admin member summary is visible to admins and moderators only.
- **Tara status: Partial (core exists).**
  - Built: `services/profile/groups/models.py` (`Group` privacy public/private/hidden, `GroupMember` roles admin/moderator/member, `GroupRule`, `GroupReport`, `GroupSuggestionDismissal`); post-side `GroupRef`, `GroupMembership`, `GroupReportReview`, `Post.pinned_at`, approval state.
  - Built UI: `FE/views/GroupsView.vue`, `GroupDetailView.vue`, `GroupManageView.vue`, `GroupFormView.vue`, `components/groups/*` (`GroupHeader.vue`, `JoinButton.vue`, `GroupInviteDialog.vue`, `GroupRailItem.vue`).
  - Missing: anonymous posting, badges, guides, files, questions, sort, managed-by-Page, last-visited, posts-per-day, pin, admin assist, spam queue, keyword alerts, admin log, group scheduling, member summary, and the two-section discover layout.
  - Group creation: **Partial.** `FE/views/GroupFormView.vue` is one form (name, handle, privacy, rules). Missing: privacy and visibility as separate choices (Tara folds them into `public|private|hidden`) and an invite-friends step (03 #179).

## SYS-10 Pages

- **Purpose.** Public identities for brands, creators and places.
- **Sub-features:**
  - **Hub:** managed cards with unread counts, Create post, Promote, discover, followed, invites with a "new" count, deactivated Pages with reactivate.
  - **Page profile:**
    - follow, message, search;
    - tabs: All, About, Followers, Photos, Mentions, Reels, More;
    - details;
    - **ratings/reviews**;
    - links;
    - contact info;
    - photos.
  - **Transparency:** created, category, name history, "updated N ago".
  - **Verified badge.**
  - **Community channel.**
  - **Manage rail:** dashboard, insights, planner, monetization, ad centre, create ads, settings, leads centre.
  - **"Switch to Page".**
- **Screens.** S09, S26, S29, S34, S35.
- **Entities.**
  - `Page {category, contact, location, status draft|published|suspended|deactivated|pending_deletion, verified_at}`.
  - `PageMember {role}`.
  - `PageNameChange`.
  - `PageReview {author, rating?, recommends, text}`.
  - `PageInvite {page, invitee, sent_by}`.
  - `PageMention` (derived from `Mention`).
  - `Lead {form, page, answers}`.
- **Flows:**
  - create a Page (**wizard, inferred, no capture**): name, category and bio → profile and cover images → contact details and link → invite friends;
  - invite friends to like it;
  - switch to the Page and act as it;
  - deactivate and reactivate;
  - promote.
- **Permissions.** `PageRole` owner, admin, editor, moderator, advertiser, analyst.
- **Tara status: Partial.**
  - Built: `services/profile/profiles/models.py` (`Page`, `PageMember`, `PageRole`, `PageNameChange`); `FE/views/PagesView.vue`, `PageDetailView.vue`, `PageByIdView.vue`, `PageInboxView.vue`; `components/pages/PageHeader.vue` (tabs posts/about/reels/team), `ManagePageRail.vue`, `PageTransparencyDialog.vue`, `PageManageCard.vue`, `PageLinksCard.vue`, `PageContactFields.vue`.
  - Missing: reviews, invites, deactivate/reactivate, unread counts on cards, Followers/Photos/Mentions tabs, the "updated N ago" line, verification, channels, leads, promote, and act-as-Page.
  - Page creation: **Partial.** `FE/components/pages/PageCreateDialog.vue` covers name and handle, images and a contact step in one dialog. Missing: the category and bio step order and the final invite-friends step (03 #178).

## SYS-11 Events

- **Purpose.** Gatherings with RSVP.
- **Sub-features:**
  - list (upcoming/past);
  - create;
  - detail;
  - RSVP;
  - invites;
  - reminders;
  - group events tab;
  - profile Events collection;
  - "event by {host}";
  - scheduled live events (link to SYS-08).
- **Screens.** S31, S32, S36.
- **Entities.**
  - `Gathering`.
  - `GatheringRSVP`.
  - `GatheringInvite`.
  - `GatheringReminderLog`.
  - `GatheringReport`.
- **Tara status: Partial.**
  - Built: `services/post/gatherings/models.py`; `FE/views/EventsView.vue`, `EventDetailView.vue`, `EventFormView.vue`.
  - Missing: profile Events section and the live-event link. Group Events tab: confirm it lists the group's gatherings.

## SYS-12 Marketplace

- **Purpose.** Local buying and selling.
- **Sub-features:**
  - browse all and "Today's picks";
  - notifications, inbox, buying, selling;
  - **seller status (account health)**;
  - create listing;
  - **location plus radius (km)**;
  - **category icons**;
  - **buy/sell group listings** feeding Marketplace, with a "new items" banner;
  - listing detail, seller page, reviews, compare, save, report;
  - marketplace chat folder with an assistant bot;
  - **listing types (inferred, no capture of the form):** item for sale, vehicle, property for rent, each with its own fields (vehicle: make, model, year, mileage; rental: rooms, bathrooms, rent period), in a **multi-step form** (type → photos → details → location → publish).
- **Screens.** S14, S02.
- **Entities.**
  - `Listing {price, price_type, title, category, location_text, geo_point, photos}`.
  - `MarketplaceCategory {icon}`.
  - `SellerProfile {standing, violations}`.
  - `UserMarketLocation {place, lat, lng, radius_km}`.
  - `GroupSaleListing` (a listing with `group_id`).
- **Permissions.** Seller standing gates listing. Reporting goes through moderation.
- **Tara status: Partial (core exists).**
  - Built: `services/marketplace/marketplace/models.py` (`Listing.location` text, `MarketplaceCategory` tree, `SellerProfile`, `SellerReview`, `ListingSave`, `ListingReport`); `FE/views/MarketplaceView.vue`, `ListingDetailView.vue`, `MarketplaceSellerView.vue`, `MarketplaceCompareView.vue`; `components/marketplace/MarketplaceNav.vue`, `CreateListingModal.vue`, `MarketplaceInbox.vue`.
  - Missing: geo and radius, category icons, seller status hub, group sale posts, the banner, and an assistant bot.
  - Missing: listing types. `Listing` has no type field and `CreateListingModal.vue` is one step (03 #180).

## SYS-13 Tara chat, messages and calls

- **Purpose.** Real-time 1:1 and group messaging, plus voice and video calls.
- **Naming.** Tara calls this product **Tara chat** (messages), as in `MessagesView.vue`. The reference chat brand is never used in copy. Code names such as `MessengerDropdown.vue` or the `messenger.*` i18n namespace are internal and not shown to users.
- **Sub-features:**
  - dropdown and full page;
  - filter chips (All, Unread, **Groups**, **Communities**);
  - folders (requests, archived, marketplace);
  - voice notes;
  - calls with call-ended previews;
  - mute;
  - seen-by;
  - reactions, edits, pins, reports;
  - **reply nudges**;
  - **bots**;
  - **broadcast channels/communities** (Page channel, group-linked chats);
  - story replies.
- **Screens.** S02, S09, S20.
- **Entities.**
  - `Conversation {type direct|group|page|channel, page_id, group_id}`.
  - `ConversationMember`.
  - `Message`.
  - `MessageAttachment`.
  - `MessageReaction`.
  - `PinnedMessage`.
  - `ChatSettings`.
  - `Call`.
  - `CallParticipant`.
- **Permissions:**
  - message requests for non-friends;
  - blocks;
  - in a channel only admins post and members read and react.
- **Tara status: Exists for the core.**
  - Built: `services/chat/chat/models.py`, `services/chat/calls/*`; `FE/components/chat/MessengerDropdown.vue`, `NewMessageModal.vue`, `GroupPanel.vue`, `VoicePlayer.vue`; `views/MessagesView.vue` (folders).
  - Missing: Groups and Communities chips, channels, nudges and bots.

## SYS-14 Notifications

- **Purpose.** Tell users about activity that concerns them.
- **Sub-features:**
  - dropdown and page;
  - All and Unread;
  - New and Earlier sections;
  - type badges;
  - unread dot;
  - mark all read;
  - preferences;
  - **kinds:** reactions, comments, mentions, friend events, group growth, scheduled post published, Page activity, marketplace, ads alerts, birthdays, memories;
  - per-row `…` menu: mark read, remove, turn off this type;
  - per-kind channel preferences: in-app, push, email.
- **Screens.** S03.
- **Entities.**
  - `Notification {kind, actor, object, read_at}`.
  - `NotificationPreference`.
- **Tara status: Exists for the core; kinds and email channel partial.**
  - Built: `services/notification/notifications/*`; `FE/components/notifications/NotificationPanel.vue`, `dropdownSections.ts`, `kinds.ts`, `NotificationPreferences.vue`; `views/NotificationsView.vue`.
  - Built: the per-row `…` menu (mark read, remove, turn off this type) in `NotificationItem.vue`.
  - Partial: channel preferences. `registry.channel_enabled` reads per-kind and per-category toggles for `in_app` and `push`; `email` exists only as a delivery-log channel value (`models.py:130`), not as a per-kind preference.
  - **Missing: the group-growth ("new member joined") and scheduled-post-published kinds** from S03. Neither is in the registry.

**Kinds in the registry today** (`services/notification/notifications/registry.py`):

| Area | Kinds |
|---|---|
| Posts and comments | `post.reaction`, `post.comment`, `comment.reply`, `mention` (posts and comments, from `user.mentioned` with an optional `comment_id`), `post.tag`, `post.share` |
| Friends | `friend.request`, `friend.accepted` |
| Groups | `group.invite`, `group.request`, `group.approved`, `group.post`, `group.role`, `group.announcement` |
| Events | `gathering.invite`, `gathering.reminder`, `gathering.update`, `gathering.cancel`, `gathering.rsvp` |
| Pages, marketplace, ads | `page.follow`, `listing.status`, `listing.inquiry`, `ad.review` |
| Moderation | `moderation.decision`, `moderation.appeal` |
| Messages and calls | `message.page`, `message.support`, `call` (push only), `call.missed` |
| Other | `story.reaction`, `video.ready`, `system.notice`, `unknown` (fallback) |

**Kinds to add** (each owned by the epic that builds its system):

| Kind (proposed) | Seen in | Sent to | Default channels | Epic |
|---|---|---|---|---|
| `group.member_joined` (aggregated per group) | S03 | Group admins | in-app | 13 |
| `post.scheduled_published` | S03 | Author (or Page editors) | in-app, push | 4 |
| `page.invite` | S26, S44 | Invitee | in-app, push | 12 |
| `post.collaborator_invite` | S07, S40 | Invitee | in-app, push | 17 |
| `friend.birthday` | S24 | Friends | in-app | 17 |
| `memory.daily` | S24 | Owner | in-app, push | 18 |
| `live.started` | S39 | Followers | push, in-app | 16 |
| `page.review` | S34, S35 | Page admins | in-app | 12 |
| `ad.account_status` and `ad.billing` | S51, S54 | Ad-account admins and finance | in-app, email | 2, 19 |
| Page activity while switched to the Page (recipient type `page`) | S27, S34 | Page members by role | in-app | 1 |

A "mention in a comment" kind is **not** missing: `mention` already covers comments. Every new kind is added to the registry with a category, default `in_app`/`push`, an optional aggregate, and an Arabic and English template.

## SYS-15 Search

- **Purpose.** Global search across people, Pages, groups, posts, events, marketplace and reels.
- **Sub-features:**
  - pill search with recent searches;
  - typeahead;
  - tabbed results;
  - scoped searches (settings, groups, marketplace, help, chat, tools);
  - **hashtag** suggestions, a Hashtags results tab and trending hashtags (see SYS-03).
- **Screens.** S01, S06, S10, S14, S18, S56 (scoped boxes).
- **Entities.**
  - Search index documents per type.
  - `RecentSearch`.
- **Permissions.** Results honour audiences, blocks and searchability settings.
- **Tara status: Exists for global search.**
  - Built: `services/search/searchsvc`, `FE/views/SearchView.vue`, `SearchabilitySetting.vue`, settings search (`components/settings/settingsIndex.ts`).
  - Missing: help search and tools search (they depend on those systems).

## SYS-16 Friends and people

- **Purpose.** Run the social graph: friendship, follow and suggestions.
- **Sub-features:**
  - hub (home, requests, suggestions, all, birthdays, **custom lists**);
  - "people you may know" with mutual friends, add and remove;
  - separate friend and follow states;
  - followers and following;
  - "recently added";
  - current-city friends.
- **Screens.** S08, S22, S36.
- **Entities.**
  - `Friendship`.
  - `FriendRequest`.
  - `FollowEdge`.
  - `SuggestionDismissal`.
  - `FriendList {name, members[]}`.
- **Permissions.** Friend-list visibility follows the profile field privacy.
- **Tara status: Exists, with gaps.**
  - Built: `services/graph` (`graph/models.py`, `suggestions.py`); `FE/views/FriendsView.vue`, `ConnectionsView.vue`; `components/friends/SuggestionCard.vue`, `social/FriendButton.vue`, `FollowButton.vue`, `PeopleYouMayKnowStrip.vue`.
  - Missing: custom lists (only story close-friends exists), and the recently-added, birthdays and current-city filters in the profile friends tab.

## SYS-17 Profile

- **Purpose.** A person's public identity.
- **Sub-features:**
  - **Header and identity:**
    - cover (edit, reposition) and avatar crop;
    - **temporary avatar**;
    - **avatar caption post**;
    - **note bubble**;
    - **alternate name** and other names;
    - followers and following;
    - bio, website and a meta line;
    - **professional mode** (category, Dashboard button, followers-first counting).
  - **Tabs and posts:**
    - tabs: All, About, Reels, Photos, Friends, More (Videos, Check-ins, Groups, Events, Reviews);
    - posts filters, list/grid toggle and **Manage posts** (bulk).
  - **About:**
    - 14 About sections with per-field audience;
    - **pinned details**;
    - typed contact handles.
  - **Collections:**
    - **places visited**;
    - **reviews**.
  - **Visitor buttons:** Message, Add friend, Follow.
- **Screens.** S11, S12, S13, S22, S23, S30, S36.
- **Entities.**
  - `UserProfile {display_name, alternate_name, bio, website, category, professional_mode, cover_offset_y, pinned_fields[]}`.
  - `ProfileFieldPrivacy`.
  - `UserLink`.
  - `UserContactHandle {network, handle}`.
  - `UserEducation`.
  - `UserWorkExperience`.
  - `ProfileNote {text, expires_at}`.
  - `TemporaryAvatar {media, revert_at, previous_media}`.
  - `UserInterest`, `UserHobby`, `UserTravel`.
  - `OtherName`.
  - `CheckIn {place, at}`.
- **Permissions:**
  - per-field audience (`ProfileFieldPrivacy`, `FE/components/AudienceSelect.vue`);
  - the note follows its own audience.
- **Tara status: Partial (strong base).**
  - Built: `services/profile/profiles/models.py` (`UserProfile`, `ProfileFieldPrivacy`, `UserLink`, `UserEducation`, `UserWorkExperience`); `FE/components/profile/ProfileHero.vue`, `ProfileDetails.vue`, `ProfileAboutTab.vue`, `ProfilePhotosTab.vue`, `ProfileFriendsTab.vue`, `ProfilePostsHeader.vue`, `AvatarCropDialog.vue`, `PhotoPickerDialog.vue`, `EditProfileModal.vue`.
  - Missing: alternate name, note, temporary avatar, caption post, professional mode (`professionalProfile built:false`), category, pinned details, the extra About sections, Manage posts, check-ins, reviews, and the More-tab sections.

## SYS-18 Photos and albums

- **Purpose.** Media library per person, Page and group.
- **Sub-features:**
  - photos of you, your photos, **albums** (user-created plus system albums: profile pictures, cover photos, uploads);
  - edit tile;
  - album picker tab in "Update picture".
- **Screens.** S11, S36, S37.
- **Entities.**
  - `Album {owner_type, owner_id, name, kind user|profile|cover|uploads, audience, cover_media}`.
  - `AlbumItem {album, media, post}`.
- **Tara status: Partial.**
  - Built: `ProfilePhotosTab.vue` builds virtual albums in `services/post/posts/services.py`.
  - Missing: an `Album` model, albums created by the user, and the album tab in the picker.

## SYS-19 Saved

- **Purpose.** Bookmark posts, reels, listings and events into collections.
- **Tara status: Exists.**
  - `SavedCollection`, `SavedItem` (`services/post/posts/models.py:407-419`), `FE/views/SavedView.vue`, reels saved tab, `ListingSave`.

## SYS-20 Memories

- **Purpose.** "On this day" resurfacing of the user's past posts, friendships and photos.
- **Sub-features:**
  - daily memories page;
  - notification;
  - share a memory;
  - hide dates or people.
- **Screens.** S24 (nav entry).
- **Entities.**
  - `MemoryPreference {hidden_people, hidden_ranges}`.
  - Derived query over posts by month and day.
- **Tara status: Missing.**
  - `menuCatalog.ts:143` has `memories built:false`.

## SYS-21 Settings, privacy and account center

- **Purpose.** All account, privacy and preference controls.
- **Sub-features:**
  - **Settings home:** search and "most visited" tiles.
  - **Account center:** password, security, personal details, ad preferences, **verification**.
  - **Privacy tools:**
    - **privacy checkup wizard**;
    - **family centre / supervision**;
    - **default audience**.
  - **Preferences:**
    - **reaction preferences** (hide counts);
    - notifications;
    - **accessibility**;
    - language and region;
    - **media (autoplay, quality)**;
    - dark mode;
    - **ads in your content**.
  - **Visibility:**
    - profile details;
    - **professional mode**;
    - find & contact.
  - **Other tools:** blocking, activity log, privacy centre.
  - **Account menu:**
    - **multi-profile switcher**;
    - **report a problem (Ctrl+B)**;
    - display & accessibility.
- **Screens.** S04, S06, S09, S41.
- **Entities.**
  - `Account {theme, language, default_audience, reaction_counts_hidden, autoplay, reduce_motion}`.
  - `Verification {subject_type, subject_id, status, method, granted_at}`.
  - `PrivacyCheckupProgress`.
  - `SupervisionLink`.
- **Tara status: Partial.**
  - Built: `FE/views/SettingsView.vue`, `components/settings/settingsIndex.ts` (`MOST_VISITED`, search), `ProfilePrivacySettings.vue`, `SearchabilitySetting.vue`, `LinkedAccounts.vue`, `DisplaySettings.vue`, `ThemeToggle.vue`; `services/identity/identity/account_center.py` (security, 2FA, devices); `views/ActivityLogView.vue` (its menu entry is `activityLog built:false`).
  - Missing: privacy checkup, family centre, default audience (the composer hard-defaults to public), reaction preferences, media and accessibility keys, professional mode, verification, multi-profile switcher, and report-a-problem.

**Privacy-controls inventory** (reference controls, mostly inferred from the S06 settings home; gap rows in 03):

| Control | Tara status | Evidence | 03 row |
|---|---|---|---|
| Default audience for new posts | Missing | composer defaults to public | #105 |
| Who can send you friend requests | Exists | `graph` `RelationshipSettings.friend_requests_from` (everyone, friends of friends); `RelationshipPrivacySettings.vue` | #162 |
| Who can see your friends list (and follow lists, counts) | Exists | `RelationshipSettings.friends_list_visibility`, `follow_lists_visibility`, `counts_visibility` | #163 |
| Who can look you up by email or phone | Missing | `UserProfile.searchable` (`SearchabilitySetting.vue`) is one switch for people search, not per-identifier | #164 |
| Search-engine indexing of the profile | Missing | no noindex control | #165 |
| Who can follow you | Missing | no follow policy | #166 |
| Public-post comment controls and keyword filters | Partial | per-post `Post.comment_policy` (everyone, friends, off) in `ComposerDialog.vue`; no account default, no keyword filter | #167 |
| Who can post on your profile | Missing | no profile-wall posting setting | #168 |
| Tag review and profile review | Partial | `PostSettings.who_can_tag` (`TagPrivacySetting.vue`); the tagged person can remove a tag; no review queue | #169 |
| Story audience and "hide story from" | Partial | `Story.audience` and `CloseFriend`; no hide-from list | #170 |
| Active status | Exists | `SettingsView.vue` `#active-status`; `realtime` consumers honour it | #171 |
| Read receipts | Missing | chat keeps read pointers, but there is no switch | #172 |
| Blocking by category (users, messages, app and event invites, Pages) | Partial | user block (`graph` `BlockRelation`); no per-category blocks | #173 |
| Restricted list | Partial | `graph` `RestrictRelation` and the person menu; no list screen in settings | #174 |
| Limit the audience of past posts | Missing | – | #175 |
| Profile lock | Missing | owner decision | #176 |
| Profile field audiences | Exists | `ProfilePrivacySettings.vue`, `ProfileFieldPrivacy`; `BirthdayGenderSettings.vue` | – |
| Privacy checkup | Missing | – | #106 |
| Reaction counts hidden | Missing | – | #107 |

**Account lifecycle flows** (inferred, no capture):
- **Deactivate and delete: Exists.** `FE/components/settings/DeactivateAccount.vue`, `DeleteAccount.vue`; deletion fans out to services (for example `services/feed/intel/deletion.py`). 03 #181.
- **Download your information: Missing.** A per-account export job that collects each service's data into one archive, with a progress state and an expiring download link. 03 #182.

## SYS-22 Help center and problem reports

- **Purpose.** Self-service help and bug reporting.
- **Sub-features:**
  - category rail;
  - article page (platform tabs, related chips, copy link);
  - search;
  - **feedback tab** ("was this helpful");
  - language switcher;
  - **report a problem** dialog with a screenshot and Ctrl+B;
  - AI panel (SYS-30).
- **Screens.** S10, S04, S39.
- **Entities.**
  - `HelpCategory`.
  - `HelpArticle {slug, title_ar, title_en, body_md, platform_variants, related[], updated_at}`.
  - `ArticleFeedback {helpful, comment}`.
  - `ProblemReport {area, text, screenshot_media, client_info}`.
- **Permissions.** Public read. Article editing is for admins with a `help.edit` capability.
- **Tara status: Missing.**
  - `menuCatalog.ts:199` has `helpCenter built:false`.
  - `FE/views/SupportView.vue` is a support/moderation inbox, not a help centre.
  - There is no report-a-problem dialog.

## SYS-23 Creator studio

- **Purpose.** A professional dashboard for creators and Pages.
- **Sub-features:**
  - **Home:**
    - KPI carousel (views, viewers, engagement, follows, earnings) with **% versus the previous period**;
    - daily chart;
    - latest-post KPIs;
    - planned-content week strip;
    - **weekly goals**;
    - survey card.
  - **Insights.**
  - **Content library:**
    - Published, Scheduled, Drafts;
    - search, filters, date range;
    - **column chooser**;
    - **bulk select**;
    - CSV export;
    - video metrics (watch time, 3-second and 1-minute views).
  - **Planner:**
    - week and month;
    - timezone;
    - drag to reschedule;
    - "+N more";
    - **"Add post" chooser** (Post, Reel, **Bulk upload**) with drafts.
  - **Playlists.**
  - **Monetization:** eligibility (500 followers, 30 days), earnings.
  - **Engagement.**
  - **All tools.**
  - **Per-post insights** reached from the post card.
- **Screens.** S15, S16, S17, S27, S30, S34, S42.
- **Entities.**
  - `DailyMetric {subject_type, subject_id, date, views, viewers, engagement, follows, earnings}`.
  - `PostMetric {post, views, viewers, watch_ms, views_3s, views_60s, ad_impressions}`.
  - `CreatorGoal {week, target, progress}`.
  - `Playlist {items}`.
  - `MonetizationEnrollment {status, eligibility_snapshot}`.
- **Permissions.** The owner, or Page analyst and above.
- **Tara status: Partial (good base).**
  - Built: `FE/views/studio/*` (`StudioHomeView.vue`, `StudioInsightsView.vue`, `StudioLibraryView.vue` with CSV, `StudioPlannerView.vue` week/month and drag, `StudioEngagementView.vue`); `components/studio/StudioLayout.vue`, `StudioCreateMenu.vue`, `PlannerPostDialog.vue`, `EngagementChart.vue`; feed `PostStats` and intel impressions.
  - Missing: deltas, viewers and watch metrics, column chooser, bulk select, Reel and bulk upload in the chooser, playlists, goals, monetization (`built:false`), per-post insights link, and Page scoping.

## SYS-24 Tara Business

- **Purpose.** A single hub for managing business assets: Pages, ad accounts and inboxes, grouped into a **business portfolio**.
- **Sub-features:**
  - **Portfolio and asset switcher** (with search, add asset, create portfolio).
  - **Home:**
    - cover and follower counter (Tara followers only; the reference's sister-app counter is out of scope);
    - Create post, ad, reel, story;
    - **to-do list** of unread messages and comments;
    - content tabs (Planner, Posts & Reels, Stories) with **Boost** and per-item insights;
    - recent ads (last 60 days);
    - growth tips and a follower goal;
    - boost-eligibility state on content cards (disabled "Promote unavailable").
  - **Unified inbox.**
  - **Content and planner** (shared with SYS-23 but Page-scoped).
  - **Insights.**
  - **Monetization.**
  - **Creator marketing hub:** partnerships, partner content, content authorization via code.
  - **Settings:**
    - business info;
    - users: people, partners, system users;
    - accounts: Pages, ad accounts, asset groups;
    - requests;
    - brand safety;
    - integrations;
    - billing link;
    - verification.
  - **All tools.**
- **Screens.** S26, S27, S41, S42, S43, S44, S49, S56, S57.
- **Entities.**
  - `BusinessPortfolio {name, owner_account_id, logo}`.
  - `PortfolioMember {account, role admin|employee}`.
  - `PortfolioAsset {kind page|ad_account|catalog, ref_id}`.
  - `AssetPermission {member, asset, tasks[]}`.
  - `PortfolioPartner {partner_portfolio, asset, tasks}`.
  - `AccessRequest {requester, asset, tasks, status pending|approved|declined}`.
  - `SystemUser {portfolio, name, token_hash, tasks}`.
  - `AssetGroup {portfolio, name, assets[]}`.
  - `BusinessVerification {portfolio, status, documents, decided_at, reason}`.
  - `PortfolioSecurity {require_2fa none|admins|everyone}`.
  - `TodoItem` (derived).
  - `CreatorPartnership {brand_portfolio, creator_account, status, permissions}`.
- **Roles and access (full definition).**
  - **Portfolio roles.** Admin has **full control** (people, partners, assets, billing, settings, deletion). Employee has **partial access**: only the assets and tasks they are given.
  - **System users.** Non-human identities owned by the portfolio for integrations (API tokens scoped to assets and tasks). They cannot log in; an admin creates, rotates and revokes their tokens.
  - **Partners.** Another portfolio given tasks on one of our assets. The partner's admins then assign those tasks to their own people.
  - **Per-asset task matrix.** Pages: content, messages, community (comments, moderation), ads, insights, revenue. Ad accounts: manage, advertise, analyze.
  - **Two-factor requirement.** A portfolio toggle: off, admins only, or everyone. A member without 2FA loses access until they enable it.
  - **Access requests.** A person or partner asks for an asset; an admin approves (choosing tasks) or declines; the requester is notified.
  - **Asset groups.** Named sets of assets so tasks are assigned once per group.
  - **Business verification.** States: not started → submitted → in review → verified, or rejected (with reason, resubmit allowed), later revoked. Verification unlocks higher limits (S41 settings tree, S51 "verify business location").

**Role × action matrix** (the BFF and `profile` enforce it, as in Epic 1):

| Action | Admin | Employee with task | Employee without task | Partner with task | System user with task |
|---|---|---|---|---|---|
| Add or remove people and partners | yes | no | no | no | no |
| Add an asset, create an asset group | yes | no | no | no | no |
| Assign tasks | yes | no | no | own people only | no |
| Approve access requests | yes | no | no | no | no |
| Set the 2FA requirement | yes | no | no | no | no |
| Start business verification | yes | no | no | no | no |
| Page: publish content | yes | content | no | content | content |
| Page: answer messages | yes | messages | no | messages | messages |
| Page: moderate comments | yes | community | no | community | no |
| Page: run ads as the Page | yes | ads | no | ads | ads |
| Page: view insights | yes | insights | no | insights | insights |
| Page: monetization and payouts | yes | revenue | no | no | no |
| Ad account: settings, billing, people | yes | manage | no | manage | no |
| Ad account: create and edit ads | yes | advertise or manage | no | advertise | advertise |
| Ad account: view reports | yes | any ad-account task | no | analyze | analyze |

- **Permissions.**
  - Portfolio admin or employee, as above.
  - Asset tasks map onto `PageRole` (owner, admin, editor, moderator, advertiser, analyst) and the ad-account roles.
- **Tara status: Missing.**
  - `menuCatalog.ts:166` has `businessCenter built:false`.
  - Parts exist elsewhere and can be reused: `PageMember` RBAC, `PageInboxView.vue` (team inbox), `Conversation.type=page`, and studio (account-scoped only).
  - There is no portfolio, no asset switcher and no boost.

## SYS-25 Tara Ads

- **Purpose.** Self-serve advertising (the reference calls this its ads manager; Tara calls it **Tara Ads**).
- **Sub-features:**
  - **Ad accounts:**
    - owned by a person or a portfolio;
    - ID, currency, timezone;
    - status (active, disabled, unsettled);
    - spend cap;
    - switcher.
  - **Hierarchy: campaign → ad set → ad.**
    - **Objectives:** awareness, traffic, engagement, leads, app promotion, sales.
    - **Buying type:** auction.
    - **Budget:**
      - campaign budget (CBO) vs ad-set budget (ABO);
      - daily or lifetime;
      - **projections** (max daily, weekly);
      - **bid strategy** (highest volume, cost cap, bid cap);
      - schedule and end date;
      - special ad categories.
  - **Create wizard (S47 modal, S48 editor; fields beyond S48 are inferred).** Tree pane and breadcrumb; each step validates on its own, and **Next is disabled until the step's required fields are valid** (S47 shows "Continue" disabled until an objective is chosen).
    - **Campaign step:** name; special ad categories; buying type; objective; campaign budget (CBO) on or off; A/B test toggle.
    - **Ad set step:** conversion location (website, app, messages, calls, Page); performance goal; data source (the reference's dataset); budget and schedule (when ABO); audience (saved, new, or custom); placements (automatic or manual); cost-per-result goal.
    - **Ad step:** acting identity (which Page); ad setup (create new, or use an existing post); format; media; primary text; headline; description; CTA; destination URL; URL parameters and tracking; preview per placement.
    - **Per-step validation:** name 1–160 characters; objective required; a special category locks targeting (below); budget ≥ the account minimum and, for lifetime budgets, an end date after the start; at least one location; at least one placement in manual mode; a destination URL that is `https://` and passes the link safety check whenever the CTA needs one; primary text within the per-placement limit.
  - **Audiences (inferred: no audience screen captured; S53 shows only shortcuts):**
    - **saved audiences:** location (country, city, radius), age range, gender, languages, interests;
    - **detailed targeting** with **include**, **exclude** and **narrow** (must also match) groups;
    - **custom audience sources:** Page engagement; post, reel or video viewers by % watched (for example 25/50/75/95%); lead-form openers and submitters; Tara Events attendees (RSVP going or interested); marketplace activity (listing viewers, messagers); website data source (tracking tag); app activity; customer list;
    - **customer lists:** CSV upload of emails or phones, normalised and **hashed with SHA-256 on the client** before upload (the server hashes too when a raw value arrives, then discards it), with a **minimum match size** (for example 100 matched people) before the list can be used;
    - **lookalike:** a source audience plus a 1–10% size per country;
    - **reach estimate:** an audience-size gauge (too narrow, fine, too broad) with a rounded estimate range, never an exact count;
    - **special ad categories:** housing, employment, credit, social issues/elections/politics. Choosing one **locks age (18–65+), gender (all) and postcode targeting**, removes lookalikes and exclusions on protected attributes, and requires a paid-for-by disclaimer for social issues;
    - **account-level controls:** minimum age for all ads, excluded locations, excluded placements (S53 "Audience controls" and "Placement controls");
    - **audience lifecycle:** retention window in days per source (for example 1–180 for engagement, 1–180 for website), a **"too small"** state that blocks delivery below the minimum size, expiry of unused lists, and **sharing** an audience with other ad accounts in the same portfolio.
  - **Placements:**
    - automatic or manual (feed, stories, reels, marketplace, search, right rail);
    - placement controls.
    - Today Tara stores **one placement per ad set** (`AdSet.placement`, a single choice field, `services/ads/ads/models.py:57-66`). Manual multi-placement (03 #138) needs a schema change from one value to a list.
  - **Boost eligibility (S44):** a post can be boosted when it is public, published (not draft or scheduled), authored by a person or Page the user may advertise for, not removed or under review by moderation, not anonymous, not a shared post of someone else's content, and contains no unsupported media. An ineligible post shows a disabled "Promote unavailable" button with the reason in a tooltip.
  - **Appeals:** an advertiser can request another review of a **rejected ad**, and request a review of a **disabled ad account** (S51, S54 notices; the appeal screens are inferred).
  - **Creative:**
    - single image or video, carousel, existing post (boost);
    - headline, primary text, CTA, URL;
    - **preview per placement**;
    - review status.
  - **Table:**
    - Campaigns / Ad sets / Ads tabs;
    - on/off toggles;
    - delivery and effective status;
    - **columns presets and chooser**;
    - **breakdowns** (age, gender, placement, day, region);
    - **saved views**;
    - date range;
    - charts;
    - export;
    - duplicate;
    - bulk edit;
    - **A/B tests**;
    - **draft layer with "Review and publish (N)" and discard**.
  - **Guidance:**
    - campaign score and recommendations;
    - opportunity score;
    - learning phase.
  - **Account overview:** alerts, spend, top campaigns.
  - **Reporting:**
    - report builder;
    - templates (ROI, reach & frequency, performance, leads);
    - scheduled exports.
  - **Billing:**
    - balance;
    - **threshold billing**;
    - daily spend limit;
    - payment methods;
    - payment activity and invoices;
    - prepaid funds.
  - **Events manager:** Tara data sources and tracking tag (the reference's datasets/pixels), conversion events, custom conversions, integrations.
  - **Ad settings:** naming templates, value rules, beneficiary/payer transparency.
  - **More tools:** automated rules, instant forms (leads), creative hub, reach planner, experiments.
  - **Ads transparency:** "why am I seeing this ad", ad library.
  - **Live-video ads** (from SYS-08) and **boost** (from SYS-03, SYS-10, SYS-24).
- **Screens.** S07, S24, S26, S30, S39, S44, S47-S57.
- **Entities (target).**
  - `AdAccount {owner_type person|portfolio, owner_id, currency, timezone, status, spend_cap, daily_spend_limit}`.
  - `AdAccountMember {role admin|advertiser|analyst|finance}`.
  - `Campaign {objective, buying_type, budget_mode cbo|abo, daily_budget, lifetime_budget, bid_strategy, bid_amount, start, end, special_categories, status, effective_status}`.
  - `AdSet {campaign, budget fields (ABO), conversion_location, performance_goal, cost_per_result_goal, data_source_id, audience_id or inline targeting (include, exclude, narrow), placements[] (a list), optimization_goal, schedule, frequency_cap}`.
  - `Ad {ad_set, creative, status}`.
  - `AdCreative {format, identity_page_id, headline, body, description, cta, link_url, url_params, media_ids[], source_post_id}`.
  - `SavedAudience`.
  - `CustomAudience {source page|video|lead_form|event|marketplace|data_source|app|customer_list, rule_json, retention_days, size_estimate, state ready|too_small|expired, hashed_members (customer_list)}`.
  - `AudienceShare {audience, target_ad_account}` (same portfolio only).
  - `AdAccountControls {min_age, excluded_locations[], excluded_placements[]}`.
  - `AdAppeal {subject ad|ad_account, subject_id, text, status open|upheld|overturned}`.
  - `LookalikeAudience {source, country, ratio}`.
  - `DraftChange {entity, payload, author}`.
  - `AdInsightDaily {level, entity_id, date, breakdown_key, impressions, reach, clicks, spend, results}`.
  - `Report`.
  - `ReportTemplate`.
  - `ExportJob`.
  - `BillingAccount {balance, threshold, next_bill_date}`.
  - `PaymentMethod`.
  - `Invoice`.
  - `Dataset {kind web|app|offline}`.
  - `ConversionEvent`.
  - `CustomConversion`.
  - `AutomatedRule {condition, action, schedule}`.
  - `LeadForm`.
  - `Lead`.
  - `Experiment`.
  - `NamingTemplate`.
  - `AccountAlert`.
- **Permissions:**
  - ad-account roles;
  - finance role for billing;
  - Page advertiser role to run ads as a Page;
  - `ads.review` capability for ad review.
- **Tara status: Partial (foundation only).**
  - Built: `services/ads/ads/models.py` (`AdvertiserAccount` one per user, `Campaign` with objective reach/traffic/engagement, a single `budget`, `spent`, status, schedule; `AdSet` with `targeting` JSON "not evaluated", **one placement per ad set** (`placement` choice feed, marketplace or search; `models.py:57-66`), fixed `cpc`/`cpm`, `frequency_cap`; `AdCreative` plus `AdReview`; privacy-bucketed `AdImpressionEvent`/`AdClickEvent`; `AdBudgetLedger`); report endpoint per campaign; `FE/views/AdsView.vue` (card list), `AdCampaignView.vue`, `AdReviewView.vue`, `services/ads.ts`, `components/post/SponsoredCard.vue`.
  - Missing: the table UI, the wizard, objectives beyond three, CBO/ABO, bid strategy, audiences, breakdowns, the draft layer, scores, the overview, the report builder, billing UI, payment methods, the events manager, rules, lead forms, experiments, boost, multi-account, multi-placement, special ad categories, the reach estimate, and advertiser appeals (ad rejection, disabled account).

## SYS-26 Trust, safety, moderation and admin

- **Purpose.** Keep the platform safe and operable.
- **Sub-features:**
  - **Reporting and enforcement:**
    - reporting on every object;
    - moderation cases, actions and appeals;
    - content policies.
  - **Labels and transparency:**
    - **AI-content label**;
    - **state-media label**;
    - Page transparency;
    - verification;
    - impersonation protection.
  - **Group moderation tooling** (SYS-09).
  - **Advertiser account integrity:** disabled, verify location, request review (appeal).
  - **Multi-step report flow (inferred):** choose a category → choose a sub-reason → optional details → confirm → "next steps" (block, unfollow, restrict, hide) and a link to the report's status.
  - **Platform admin console:** users, roles, capabilities, flags, notices, audit, monitor, support.
- **Screens.** S09, S24, S32, S33, S35, S51, S54.
- **Tara status: Exists for the core.**
  - Built: `services/moderation/moderation/models.py` (`Report`, `ModerationCase`, `ModerationAction`, `Appeal`, `ContentPolicy`, `ModerationAuditLog`); `services/admin`; `FE/views/Admin*View.vue` (audit, capabilities, flags, moderation, monitor, notices, roles, support, users); `CommunityStandardsView.vue`.
  - Missing: AI and state-media labels, verification, and ad-account integrity states.
  - Report flow: **Partial.** `FE/components/social/ReportDialog.vue` (and the chat, event and group report dialogs) is one step: a reason list plus details. Missing: sub-reasons and the next-steps screen (03 #183).
  - Appeals: user moderation appeals exist (`moderation` `Appeal`, `components/moderation/AppealDialog.vue`); advertiser appeals for ads and ad accounts are missing (03 #184, #185).

## SYS-27 Accessibility, display and i18n

- **Purpose.** Make the product usable by everyone in Arabic and English.
- **Sub-features:**
  - **Display:**
    - dark/light;
    - compact mode;
    - keyboard shortcuts (Ctrl+K search, Ctrl+B report);
    - reduce motion.
  - **Accessibility:**
    - alt text;
    - **closed captions, audio descriptions and transcripts** for video and reels;
    - ARIA labels on icon-only tabs;
    - arrow-key repositioning (cover, crop).
  - **Translation:** "See translation" on comments and posts.
  - **Locale:**
    - language switcher (landing footer, help);
    - Arabic-Indic digits for money and counts;
    - LTR islands for IDs and URLs.
- **Screens.** S04, S10, S12, S13, S23, S28, S40, S47.
- **Tara status: Partial.**
  - Built: RTL default and i18n (`FE/i18n`), `LocaleToggle.vue`, `ThemeToggle.vue`, `DisplaySettings.vue`; reduced-motion handling in `style.css`, `MediaTheater.vue`, `CommentList.vue`.
  - Missing: captions, transcripts, translation and a keyboard shortcut map.
  - Unclear: the landing language footer is not confirmed.

## SYS-28 Auth, landing and onboarding

- **Purpose.** Let guests sign up or log in.
- **Sub-features:**
  - landing hero;
  - login (email or phone);
  - forgot password;
  - create account;
  - language links;
  - **post-signup onboarding (inferred, no capture):** add a profile photo → find friends (suggestions and contact search) → pick interests → done, each step skippable.
- **Screens.** S28.
- **Tara status: Exists.**
  - Built: `FE/views/LandingView.vue`, `LoginView.vue`, `RegisterView.vue`, `ForgotPasswordView.vue`, `ResetPasswordView.vue`, `VerifyEmailView.vue`, `ConfirmEmailView.vue`; `services/identity`.
  - Missing: post-signup onboarding (no onboarding route; 03 #177).

## SYS-29 Acting identity: profile and Page switching

- **Purpose.** One login acts as a person, as a Page it manages, or as a second profile. This is cross-cutting.
- **Sub-features:**
  - profile switcher in the account menu;
  - "Switch to Page" banner and card;
  - Page-mode top tabs (Home, Pages, Insights, Ads);
  - "comment as / reply as" chevron;
  - "you are commenting as …" warning;
  - Page notifications and inbox while switched.
- **Screens.** S04, S05, S23, S27, S30, S33, S34, S35.
- **Entities.**
  - `ActingContext {account_id, actor_type user|page, actor_id}`, sent as a header (for example `X-Tara-Actor: page:<id>`).
  - The BFF checks `PageMember` role for the requested action.
  - Every write records `author_type` and `author_id` plus `acted_by_account_id` for audit.
- **Permissions.** Only Page members whose role allows the action (editor and above to post; moderator and above to comment and reply).
- **Tara status: Missing.**
  - Pages can post through `PagePostComposer.vue` (`Post.author_type`).
  - There is no actor switch anywhere (no `actingAs`), and comments have no actor type.
  - This is the **key enabler** for the Pages, Business and Ads parity work.

## SYS-30 Tara assistant (AI)

- **Purpose.** An in-product assistant (the reference has a branded one; Tara builds its own).
- **Sub-features:**
  - nav entry;
  - help-article panel (summary, suggested questions, Q&A grounded in articles);
  - **floating assistant button** inside the Tara Business and Tara Ads shells: a round button at the bottom end corner (left in RTL) that opens a side panel aware of the current screen (asset, campaign, report). Tara uses its own icon and neutral wording such as "Ask Tara";
  - later: post-writing help and an ads "Analyze" assistant.
- **Screens.** S10, S24, S29, S41, S44, S47 (Analyze and the floating button), S53, S02 (marketplace bot).
- **Entities.**
  - `AssistantSession {account, context_type help|business|ads, context_id}`.
  - `AssistantMessage`.
  - Retrieval over `HelpArticle`.
- **Permissions.** Signed-in users only. The assistant must not read private content beyond the requesting user's own data.
- **Tara status: Missing.**
  - No assistant module exists.
  - Owner decision needed on the model and hosting (local LLM vs API).

## Out of scope (seen in captures, recommended to skip)

- **Gaming tab and games in shortcuts** (S22, S24). `AppNavbar.vue` documents that no gaming module exists.
- **Photo-app cross-promotion and linked-account counters** (S30, S34, S44 hero). Tara has no sister app.
- **External messaging-app button** (S44). This is an optional integration only.
- **Fundraisers, appointments and commerce manager** (S56). These are listed in "All tools" only, with no screens to study.
