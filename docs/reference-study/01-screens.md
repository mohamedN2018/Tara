# 01. Reference screens, one section per capture

**Source folder:** `frontend/Desgin/Captures/` (57 files, captured 2026-11-03 and 2026-11-04).
**Reference files:** 56 of the 57 show the reference social product. **One file is not a reference:** S21, a camera NVR ("Frigate") screen, which this study ignores.
**How the files were read:** the full-page snapshots are 3440 px wide and very tall. They were downscaled and tiled with Pillow inside the `tara/media:dev` image. The tiles live in the session scratchpad and are not committed.

**Brand rule (applies to every section):** Tara copies the *structure, systems and layout*. It does not copy the name, logo, wordmark, proprietary icons, illustrations or copy. Reference-brand items seen in the captures appear here only as patterns, under neutral names:

| Reference-brand item | Pattern Tara rebuilds under its own name |
|---|---|
| AI assistant | Tara assistant |
| Paid verified subscription | Tara verified badge |
| Business suite | Tara Business |
| Messenger (the reference chat product) | Tara chat (messages, as in `MessagesView.vue`) |
| Ads manager | Tara Ads |
| Datasets & pixels | Tara data sources / tracking tag |
| Photo-app cross-posting | Not planned (Tara has no sister app) |
| "Ad choices" | Ads transparency link |

Each section names the systems it feeds. The `SYS-xx` IDs link into [02-systems-catalog.md](02-systems-catalog.md).

**Theme (corrected).** All captures are Arabic RTL, but the theme depends on the surface:
- **Social surfaces are dark** (S01–S40 except S21 and S22, plus S45 and S46).
- **Business and ads surfaces are light**, on a soft pastel gradient background: Tara Business (S41–S44, checked in S41 and S44) and the ads screens (S47–S57, checked in S47 and S53).
- S22 is the one light-theme *social* capture.
- Tara's light-mode checks therefore use S22 (social), S44 (business home) and S53 (ads settings).

**Common chrome (social desktop captures):**
- Fixed top bar, about 56 px:
  - Start edge (right in RTL): logo and pill search.
  - Centre: five icon tabs with an active underline.
  - End edge (left in RTL): avatar menu, notifications, chat and app grid.
- Sticky start-side navigation rail, about 340-360 px.
- Floating "new message" button at the bottom end corner.

**Business and ads chrome (S41–S44, S47–S57):**
- No social top bar. A narrow icon rail on the start side (right in RTL), with the asset or ad-account selector at its top.
- A **round floating assistant button** at the bottom corner on the end side (left in RTL). It is seen in S41, S44, S47 and S53 and feeds [SYS-30](02-systems-catalog.md#sys-30-tara-assistant-ai) as a context-aware assistant entry.

---

## Index

| # | File | Screen | Systems |
|---|---|---|---|
| S01 | `Facebook - Google Chrome 11_4_2026 10_13_31 AM.png` | Home feed, narrow width | SYS-01, SYS-02, SYS-09 |
| S02 | `… 10_14_23 AM.png` | Chat dropdown | SYS-13 |
| S03 | `… 10_14_29 AM.png` | Notifications dropdown | SYS-14 |
| S04 | `… 10_14_32 AM.png` | Account menu / profile switcher | SYS-21, SYS-29, SYS-22, SYS-27 |
| S05 | `… 2_45_48 PM.png` | Photo theater with comments | SYS-07, SYS-04 |
| S06 | `… 2_58_46 PM.png` | Settings & privacy home | SYS-21 |
| S07 | `… 3_08_14 PM.png` | Full-page Create post | SYS-03 |
| S08 | `… 3_26_32 PM.png` | Friends hub / people you may know | SYS-16 |
| S09 | `… 3_32_36 PM.png` | Page transparency dialog | SYS-10, SYS-26 |
| S10 | `… 3_33_56 PM.png` | Help center article and AI panel | SYS-22, SYS-30 |
| S11 | `… 3_34_34 PM.png` | "Update picture" picker | SYS-17, SYS-18 |
| S12 | `… 3_34_42 PM.png` | Cover reposition mode | SYS-17 |
| S13 | `… 3_35_54 PM.png` | Avatar crop dialog | SYS-17 |
| S14 | `Facebook Marketplace _ … 8_40_33 AM.png` | Marketplace browse | SYS-12 |
| S15 | `Facebook Marketplace _ … 8_40_43 AM.png` | Creator dashboard home | SYS-23 |
| S16 | `Facebook Marketplace _ … 8_40_59 AM.png` | Planner week view, "Add post" modal | SYS-23 |
| S17 | `Facebook Marketplace _ … 8_41_07 AM.png` | Content library | SYS-23 |
| S18 | `Facebook Marketplace _ … 8_41_39 AM.png` | Groups feed | SYS-09 |
| S19 | `Facebook Marketplace _ … 8_41_46 AM.png` | Reels viewer | SYS-06 |
| S20 | `Facebook Marketplace _ … 8_44_52 AM.png` | Story viewer | SYS-05 |
| S21 | `Live - Frigate - Google Chrome 11_4_2026 4_07_35 PM.png` | **NOT A REFERENCE** (camera NVR) | none |
| S22 | `New folder/(20+) … 9_02_49 AM.png` | Profile header, visitor view, light theme | SYS-17 |
| S23 | `New folder/(20+) … 9_02_56 AM.png` | Profile body and comment thread | SYS-17, SYS-04 |
| S24 | `New folder/(20+) … 9_03_06 AM.png` | Home feed, hide-post feedback, stories tray | SYS-02, SYS-05, SYS-25 |
| S25 | `New folder/(20+) … 9_03_15 AM.png` | Feed with in-feed reels module | SYS-02, SYS-06 |
| S26 | `New folder/… 11_13_23 AM.png` | Pages hub | SYS-10 |
| S27 | `New folder/… 3_06_10 AM.png` | Business planner month view (acting as Page) | SYS-24, SYS-29 |
| S28 | `New folder/… 9_02_25 AM.png` | Logged-out landing and login | SYS-28 |
| S29 | `Screenshot 2026-11-04 152313.png` | Home feed with Page hover card | SYS-01, SYS-02, SYS-10 |
| S30 | `fullpage_snapshot_… 13-10-01.png` | Own profile, All tab (professional mode) | SYS-17, SYS-04, SYS-23 |
| S31 | `fullpage_snapshot_… 13-19-29.png` | Private group, member view | SYS-09 |
| S32 | `fullpage_snapshot_… 13-21-29.png` | Public group, admin rail | SYS-09, SYS-26 |
| S33 | `fullpage_snapshot_… 13-21-50.png` | Member profile inside a group | SYS-09 |
| S34 | `fullpage_snapshot_… 13-22-06.png` | Page, "Manage Page" rail | SYS-10, SYS-29 |
| S35 | `fullpage_snapshot_… 13-22-19.png` | Page, scrolled | SYS-10 |
| S36 | `fullpage_snapshot_… 13-36-48.png` | Profile About and collections | SYS-17, SYS-18, SYS-11 |
| S37 | `fullpage_snapshot_… 13-37-41.png` | Profile Photos tab | SYS-18 |
| S38 | `fullpage_snapshot_… 13-37-51.png` | Profile Reels tab | SYS-06 |
| S39 | `إنشاء منشور _ … 3_09_01 PM.png` | Create live video hub | SYS-08 |
| S40 | `إنشاء منشور _ … 3_09_14 PM.png` | Create reel editor | SYS-06 |
| S41 | `اعمال/Facebook - … 3_32_53 PM.png` | Business portfolio settings | SYS-24, SYS-30 |
| S42 | `اعمال/Meta Business Suite - … 3_12_19 PM.png` | Portfolio / asset switcher over Monetization | SYS-24, SYS-23 |
| S43 | `اعمال/Meta Business Suite - … 3_12_34 PM.png` | Creator marketing hub | SYS-24 |
| S44 | `اعمال/fullpage_snapshot_business_… 13-11-29.png` | Business home | SYS-24, SYS-25, SYS-30 |
| S45 | `المجموعات _ … 4_09_33 PM.png` | Groups discover | SYS-09 |
| S46 | `المجموعات _ … 4_09_36 PM.png` | Your groups | SYS-09 |
| S47 | `منصة اعلانات/… الحملات الإعلانية … 3_02_50 PM.png` | Campaign table and Create modal | SYS-25, SYS-30 |
| S48 | `منصة اعلانات/… 3_03_21 PM.png` | Campaign editor (draft) | SYS-25 |
| S49 | `منصة اعلانات/… 3_03_48 PM.png` | Ad-account switcher | SYS-25 |
| S50 | `منصة اعلانات/… 3_03_55 PM.png` | Campaign table, three campaigns | SYS-25 |
| S51 | `منصة اعلانات/… 3_04_29 PM.png` | Ads account overview | SYS-25 |
| S52 | `منصة اعلانات/… 3_04_51 PM.png` | Ads reporting | SYS-25 |
| S53 | `منصة اعلانات/… الجماهير … 3_05_54 PM.png` | Ad settings (the file name says Audiences) | SYS-25, SYS-30 |
| S54 | `منصة اعلانات/… الجماهير … 3_06_03 PM.png` | Billing and payments | SYS-25 |
| S55 | `منصة اعلانات/… الجماهير … 3_06_21 PM.png` | Events manager (datasets) | SYS-25 |
| S56 | `منصة اعلانات/… الجماهير … 3_06_35 PM.png` | "All tools" drawer | SYS-25, SYS-24 |
| S57 | `منصة اعلانات/… الجماهير … 3_06_39 PM.png` | "All tools" drawer (scrolled) | SYS-25, SYS-24 |

**File-name warning 1:** six of the seven "Marketplace" files (S15-S20) do not show Marketplace. The browser tab title was simply left over from an earlier page.

**File-name warning 2:** the five "الجماهير" (Audiences) files (S53-S57) do not show an audiences list. No capture shows a custom/lookalike/saved audience table, so the audience requirements in this study are **inferred**. S53 shows only the "engaged audience" and "existing customers" shortcuts, both "Not set".

---

## S01. Home feed at narrow width (about 475 px)
- **Top bar.** Collapses to a logo and a round search icon at the start edge. The end edge keeps the app grid, chat, bell and avatar. There are no centre tabs and **no bottom navigation bar**.
- **Suggested group post.** Header reads "Group name · Join" with an inline join link. Below it:
  - author and time;
  - a bold title;
  - body text with a location line;
  - a collage of one large and two small images;
  - counts of 14.6K reactions, 1.5K comments and 823 shares;
  - `×` to hide and `…` for more.
- **Next card.** A group post written under an anonymous alias.
- Systems: [SYS-01](02-systems-catalog.md#sys-01-shell-and-navigation), [SYS-02](02-systems-catalog.md#sys-02-home-feed), [SYS-09](02-systems-catalog.md#sys-09-groups).

## S02. Chat dropdown
- **Header.** Title "Chats" with three buttons: `…` (active status, message requests, archived), expand to full view, and new message.
- **Search box** for messages.
- **Filter chips:** All, Unread, Groups, Communities.
- **Rows.** Each row shows:
  - avatar, name and time;
  - a preview with a "You:" prefix;
  - nudges such as "Reply?" or "Follow up?";
  - a seen-by mini avatar and a muted-bell icon;
  - system previews such as "voice call ended" and "sent a voice message";
  - for Marketplace threads, a shop avatar and an assistant bot.
- **Footer:** a "See all" link that opens the full chat page. Tara copy: "See all in chat".
- Systems: [SYS-13](02-systems-catalog.md#sys-13-tara-chat-messages-and-calls).

## S03. Notifications dropdown
- **Header and filters.** Title with `…` (mark all read, settings, open the full page) and the chips All and Unread.
- **Sections.** "New" (with "See all") and "Earlier".
- **Rows.** Each row shows:
  - an avatar with a type badge;
  - text with the entity names in bold;
  - the time in the brand colour;
  - an unread dot.
- **Kinds visible:**
  - "new member joined your group, invite friends" (sent to group admins);
  - "your scheduled post was published".
- **Footer:** "See previous notifications".
- **Behind the dropdown.** A feed post (a verified Page with "· Follow") whose text carries a **linked hashtag** in the brand colour. This is the hashtag evidence for SYS-03.
- Systems: [SYS-14](02-systems-catalog.md#sys-14-notifications), [SYS-03](02-systems-catalog.md#sys-03-posts-and-composer).

## S04. Account menu (emulated at 400 px)
- **Profile switcher card.** Shows the current person, then other profiles (a Page and a second profile), then "See all profiles".
- **Menu items:**
  - Business suite (external link);
  - Settings & privacy ›;
  - Help & support ›;
  - Report a problem (shortcut hint Ctrl+B);
  - Display & accessibility ›;
  - Log out;
  - footer links.
- Systems: [SYS-21](02-systems-catalog.md#sys-21-settings-privacy-and-account-center), [SYS-29](02-systems-catalog.md#sys-29-acting-identity-profile-and-page-switching), [SYS-22](02-systems-catalog.md#sys-22-help-center-and-problem-reports), [SYS-27](02-systems-catalog.md#sys-27-accessibility-display-and-i18n).

## S05. Photo theater
- **Stage.** Black, about 80% of the width.
  - Buttons: fullscreen, zoom in and zoom out.
  - Arrows for previous and next.
  - Close at the top start.
- **Side panel.** About 360 px with its own scroll. Contents in order:
  - post header (avatar, name, time, audience, `…`);
  - post text and reaction icons;
  - counts;
  - a "Most relevant ▾" comment sort.
- **Comments.** Each comment has:
  - like, **dislike**, reply and a reaction bubble;
  - optionally an **image attachment**.
- **Composer.** "Comment as {name}" with an identity switcher. Pickers for avatar sticker, GIF, camera, emoji and sticker.
- Systems: [SYS-07](02-systems-catalog.md#sys-07-video-watch-and-media-theater), [SYS-04](02-systems-catalog.md#sys-04-comments-and-reactions).

## S06. Settings & privacy home
- **Navigation.** A start-side rail with a "Search settings" box and four groups:
  - **Your account:** an accounts-center card covering password, security, personal details, ad preferences and verification.
  - **Tools & resources:** privacy checkup, family centre, default audience.
  - **Preferences:** reaction preferences, notifications, accessibility, language & region, media, dark mode, dashboards, ads in content you create.
  - **Audience & visibility:** profile details, professional mode, how people find and contact you.
- **Canvas:**
  - a search box;
  - "Most visited settings" tiles: blocking, activity log, dark mode;
  - links to the Privacy center and Help center.
- Systems: [SYS-21](02-systems-catalog.md#sys-21-settings-privacy-and-account-center).

## S07. Full-page Create post
- **Layout.** The form is on the start side. A live **preview** card sits on the end side.
- **Chips:** tag people, feeling/activity, location, **collaborator**.
- **Text area** with emoji and an "Aa" **text-background** picker.
- **Drag-and-drop media zone.**
- **Tiles:** get calls (CTA), **life event**, **GIF**.
- **Sharing section:**
  - audience picker;
  - **AI-content label** toggle;
  - **share to groups**;
  - monetization;
  - share to story;
  - **boost post** toggle.
- **Sticky footer:** drafts, Schedule, Post (disabled while the post is empty).
- **Behaviour.** Every chevron opens a sub-panel inside the same drawer.
- Systems: [SYS-03](02-systems-catalog.md#sys-03-posts-and-composer), [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S08. Friends hub
- **Rail.** Home, Friend requests ›, Suggestions ›, All friends ›, Birthdays, **Custom lists** ›, and a settings gear.
- **Canvas.** "People you may know" as a grid of five cards per row. Each card has:
  - a square photo and the name;
  - mutual-friend avatars with a count, or "followed by N";
  - **Add friend** and **Remove** buttons.
- Skeleton cards show while loading. A floating compose button is present.
- Systems: [SYS-16](02-systems-catalog.md#sys-16-friends-and-people).

## S09. Page transparency dialog
- **Page behind the dialog.** It shows:
  - a cover, avatar and **verified badge**;
  - "17M followers" and a **community chat** chip;
  - Message, Follow and Search buttons;
  - tabs: All, About, Reels, Photos, Followers, More;
  - a Links card and a **Communities (channel)** card.
- **Dialog contents:**
  - safety intro;
  - a verified block with a subscription upsell;
  - creation date;
  - "profile updated 3 minutes ago";
  - category;
  - a policy link.
- Systems: [SYS-10](02-systems-catalog.md#sys-10-pages), [SYS-26](02-systems-catalog.md#sys-26-trust-safety-moderation-and-admin), [SYS-21](02-systems-catalog.md#sys-21-settings-privacy-and-account-center) (verification).

## S10. Help center article and AI side panel
- **Category rail.** Using the platform, login & security, account, privacy & safety, policies, reporting.
- **Article column:**
  - a title and "Copy link";
  - platform tabs (computer, Android, more);
  - related-topic chips;
  - a callout box, then the body.
- **Page controls.** A vertical **Feedback** tab at the screen edge, a "Search help" box in the top bar and a language switcher.
- **AI panel.** It has:
  - history and new-chat buttons;
  - a summary of the article;
  - suggested questions;
  - an "Ask a question" box;
  - a legal note.
- Systems: [SYS-22](02-systems-catalog.md#sys-22-help-center-and-problem-reports), [SYS-30](02-systems-catalog.md#sys-30-tara-assistant-ai).

## S11. "Update picture" picker
- **Dialog.** Over the own profile. Two tabs, **Recent photos** and **Photo albums**, above a three-column grid.
- **Profile behind the dialog:**
  - Dashboard and Edit buttons;
  - Live / Photo / Reel composer shortcuts;
  - posts filters, Manage posts, and a list/grid toggle.
- Systems: [SYS-17](02-systems-catalog.md#sys-17-profile), [SYS-18](02-systems-catalog.md#sys-18-photos-and-albums).

## S12. Cover reposition mode
- **Sticky bar.** "Your cover photo is public", with Cancel and Save.
- **Hint.** "Drag or use the arrow keys" over the cover.
- **Header details, fully readable:**
  - the **alternate name** in brackets;
  - the followers/following line;
  - a bilingual bio and a website link;
  - a professional category, city and job;
  - an avatar **note bubble** ("share a thought").
- **Personal details card:** lives in, from, birthday.
- Systems: [SYS-17](02-systems-catalog.md#sys-17-profile).

## S13. Avatar crop dialog
- **Description** box. The text becomes the caption of the profile-update post.
- **Crop controls.** A circular mask and a zoom slider.
- **Buttons.** Crop and **Make temporary** (the avatar reverts after a set time).
- **Footer.** A "public" note, then Cancel and Save.
- Systems: [SYS-17](02-systems-catalog.md#sys-17-profile), [SYS-03](02-systems-catalog.md#sys-03-posts-and-composer).

## S14. Marketplace browse
- **Rail:**
  - a search box;
  - Browse all, Notifications, Inbox;
  - **Marketplace status** (seller account health);
  - Buying ›, Selling ›;
  - "+ Create new listing";
  - **location and radius** ("within 40 km");
  - categories with icons.
- **Main area:**
  - a dismissible banner: "new items in buy/sell groups you joined";
  - "Today's picks" with a location chip;
  - a seven-column grid of square cards (price or Free, title, city).
- Systems: [SYS-12](02-systems-catalog.md#sys-12-marketplace).

## S15. Creator dashboard home
- **Rail:** Home, Insights ▾, Content ▾, Monetization ▾, Engagement ▾, All tools, and a sticky split button "Create post ▾".
- **Insights card:**
  - a date range;
  - a **KPI carousel**: views (+46%), approximate earnings, engagement (+140%), follows;
  - each tile shows a **period-over-period %** and drives a daily area chart below.
- **Content card.** The latest post with four mini KPIs.
- **Planned content.** A week strip with an empty-day nudge.
- **Side cards.** A "profile status" weekly-progress ring and a feedback survey.
- Systems: [SYS-23](02-systems-catalog.md#sys-23-creator-studio).

## S16. Planner (week) with the "Add post" modal
- **Planner header.** A date range, timezone, Today, ‹ ›, a Week ▾ switch and a filter.
- **Grid.** Hourly rows. Today is highlighted.
- **"Add post" modal:**
  - three tiles: **Post**, **Reel**, **Bulk upload**;
  - "Your latest drafts", here in its empty state.
- **Rail.** Content expanded to Content library, Planner and **Playlists**.
- Systems: [SYS-23](02-systems-catalog.md#sys-23-creator-studio).

## S17. Content library
- **Banner.** "Videos are now reels."
- **Tabs.** Published, Scheduled, Drafts.
- **Toolbar:** search, + Create ▾, Filters ▾, **Columns ▾**, a date range, **Export ▾**, and a selection counter.
- **Columns:** preview, views, viewers, engagement, earnings, follows, ad impressions, comments, distribution, watch time, average watch time, 3-second views, 1-minute views.
- **Rows.** Checkbox, thumbnail with a type badge, title, status and time, `…` menu.
- Systems: [SYS-23](02-systems-catalog.md#sys-23-creator-studio).

## S18. Groups feed
- **Rail:**
  - Your feed, Discover, Your groups;
  - "+ Create new group";
  - "Groups you manage" and "Groups you've joined", each row with **last active N ago**.
- **Centre.** "Recent activity" posts:
  - group avatar, group name, author and time;
  - an inline "Comment as" box with GIF, sticker and camera pickers.
- Systems: [SYS-09](02-systems-catalog.md#sys-09-groups).

## S19. Reels viewer
- **Rail.** For you, Following, Profile.
- **Player.** A 9:16 player with mute.
- **Overlay.** Author, verified badge, "· Follow", **"♪ Original audio"** and the caption.
- **Action column.** Like, comment, share and more, with counts.
- **Paging.** Up/down buttons.
- **Content note.** The video itself is political. Only the layout was studied.
- Systems: [SYS-06](02-systems-catalog.md#sys-06-reels).

## S20. Story viewer
- **Shell.** Full-screen black.
- **Rail:**
  - Archive and Settings links;
  - a "Create story" tile;
  - "All stories" rows: a ring (unseen or seen), the name, "N new cards" and the time.
- **Viewer card:**
  - segmented progress bars;
  - a **music label**;
  - pause, mute and `…`;
  - **text blocks, an animated sticker and a mention sticker**;
  - prev/next.
- **Footer.** A reply box (goes to a DM) and seven quick reactions.
- Systems: [SYS-05](02-systems-catalog.md#sys-05-stories), [SYS-13](02-systems-catalog.md#sys-13-tara-chat-messages-and-calls).

## S21. NOT A REFERENCE: camera NVR screen
- `Live - Frigate - Google Chrome 11_4_2026 4_07_35 PM.png` shows a home-camera recorder dashboard.
- It is unrelated to the product and was excluded from the study.

## S22. Profile header, visitor view (light theme, Indonesian locale)
- **Header.** Cover with rounded bottom corners, a large avatar, the name and **alternate name**, and "3K followers · 12 following".
- **Buttons.** Following (state), Message (primary), Add friend, ▾.
- **Text.** A bilingual bio and a website link.
- **Info line.** **Category** "Digital creator", city and a social handle.
- **Tabs.** All, About, Reels, Photos, Friends, More ▾, `…`.
- **Note.** The **friend state and follow state are separate**.
- **Use.** This is the only light-theme *social* capture. Business (S41–S44) and ads (S47–S57) captures are also light. Check Tara's default light mode against S22, S44 and S53.
- Systems: [SYS-17](02-systems-catalog.md#sys-17-profile), [SYS-16](02-systems-catalog.md#sys-16-friends-and-people).

## S23. Profile body and comment thread
- **Sticky side column:**
  - Personal details (lives in, gender);
  - Links;
  - **Contact info** with typed network icons;
  - a Photos grid.
- **Posts.** A posts list with a filter. The example is the post "updated his cover photo".
- **Comments:**
  - an "author reacted 😆" badge;
  - like, **dislike**, reply and **See translation**;
  - nested replies carry an **"Author" badge** and an @mention.
- **Comment box.** Identity chevron, plus avatar sticker, emoji, camera, GIF and sticker pickers.
- Systems: [SYS-17](02-systems-catalog.md#sys-17-profile), [SYS-04](02-systems-catalog.md#sys-04-comments-and-reactions), [SYS-27](02-systems-catalog.md#sys-27-accessibility-display-and-i18n).

## S24. Home feed: hide-post feedback and stories tray
- **Start rail.** Profile, AI assistant, Friends, **Memories**, Saved, Groups, Reels, Marketplace, Feeds, Events, See more, "Your shortcuts" (games), footer.
- **Composer.** Live, Photo and Feeling.
- **Stories tray.** A Create card and story cards with a next arrow.
- **Hidden-post card:**
  - "Why aren't you interested?" with reason chips;
  - snooze 30 days, unfollow, report;
  - undo.
- **Sponsored post.** Carries a **"state-controlled media"** label.
- **End rail.** Sponsored units, then Birthdays.
- Systems: [SYS-02](02-systems-catalog.md#sys-02-home-feed), [SYS-05](02-systems-catalog.md#sys-05-stories), [SYS-25](02-systems-catalog.md#sys-25-tara-ads), [SYS-20](02-systems-catalog.md#sys-20-memories).

## S25. Feed with an in-feed Reels module
- **Reels module.** A horizontal carousel of 9:16 cards with ⋮ menus and a next arrow.
- **Normal posts.** Each has `…` and ×.
- Systems: [SYS-02](02-systems-catalog.md#sys-02-home-feed), [SYS-06](02-systems-catalog.md#sys-06-reels).

## S26. Pages hub
- **Rail:**
  - "+ Create page";
  - external links: business suite, inbox, insights;
  - Discover, Followed Pages, **Invites (New: 307)**.
- **"Pages you manage" cards.** Each card has:
  - a story ring;
  - **unread notification and message counts**;
  - Create post, **Promote** and `…`.
- **Side card.** "**Deactivated and deleted Pages**", each with Reactivate.
- Systems: [SYS-10](02-systems-catalog.md#sys-10-pages), [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S27. Business planner month view, acting as a Page
- **Page mode.** The avatar is the Page logo. The centre tabs become Home, Pages, Insights and Ads.
- **Rail.** "Business dashboard" with Content › Planner.
- **Month grid:**
  - post chips with a thumbnail and time;
  - a published chip with "22 views";
  - "More than 2 posts…" overflow;
  - next-month days greyed out.
- Systems: [SYS-24](02-systems-catalog.md#sys-24-tara-business), [SYS-29](02-systems-catalog.md#sys-29-acting-identity-profile-and-page-switching), [SYS-23](02-systems-catalog.md#sys-23-creator-studio).

## S28. Logged-out landing and login
- **Hero.** A collage of product cards and a tagline.
- **Login form.** Email or phone, password, "Forgot password?" and "Create new account".
- **Footer.** Language links.
- Systems: [SYS-28](02-systems-catalog.md#sys-28-auth-landing-and-onboarding), [SYS-27](02-systems-catalog.md#sys-27-accessibility-display-and-i18n).

## S29. Home feed with a Page hover card
- **Start rail:**
  - profile, AI assistant, Friends, creator dashboard, Saved, Events, Pages;
  - See more;
  - "Your shortcuts" (groups and Pages);
  - footer.
- **End rail.** Birthdays.
- **Feed.** A suggested Page post with "· Follow", `…` and ×.
- **Hover card:**
  - avatar ring, name and "Page · Hotel";
  - bio and phone;
  - followers count;
  - Message, Follow and `…`.
- Systems: [SYS-01](02-systems-catalog.md#sys-01-shell-and-navigation), [SYS-02](02-systems-catalog.md#sys-02-home-feed), [SYS-10](02-systems-catalog.md#sys-10-pages).

## S30. Own profile, All tab (professional mode)
- **Header:**
  - cover with Edit and an avatar **note bubble**;
  - the two-script name;
  - followers and following counts;
  - bio, website and a meta line (category, city, job, handle).
- **Header buttons.** **Dashboard** (primary), Edit and ▾.
- **Composer.** Live, Photo/video and Reel.
- **Posts header.** Filters, **Manage posts** (bulk) and a list/grid toggle.
- **Post cards:**
  - system stories such as "updated cover photo";
  - owner-only "**See insights**" and "**Create ad**" (boost);
  - comments with like/dislike, reply and **owner hide**;
  - an **author badge** on replies;
  - "comment as".
- **Side column.** Personal details, links, a nine-friend grid, a nine-photo grid and the footer.
- Systems: [SYS-17](02-systems-catalog.md#sys-17-profile), [SYS-04](02-systems-catalog.md#sys-04-comments-and-reactions), [SYS-23](02-systems-catalog.md#sys-23-creator-studio), [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S31. Private group, member view (Discussion tab)
- **Header:**
  - cover with a "**managed by a Page**" banner;
  - "Private group · 358.9K members" and a facepile;
  - Invite, Share and "Joined ▾".
- **Tabs.** About, Discussion, **Guides**, Featured, **Open questions**, Members, Events, Media, **Files**, plus search.
- **Composer.** Feeling, check-in, poll.
- **Featured card.** "**6 new items**".
- **Sort.** "Recent activity ▾".
- **Posts:**
  - **anonymous aliases** with cartoon avatars;
  - "**Top contributor**" badges;
  - a **post title**;
  - **coloured-background text**;
  - "+2" collages;
  - nested threaded replies with an "edited" marker.
- **Side card.** About (private and visible facts) and recent media.
- Systems: [SYS-09](02-systems-catalog.md#sys-09-groups), [SYS-03](02-systems-catalog.md#sys-03-posts-and-composer).

## S32. Public group with the admin rail
- **Admin rail:**
  - community home and overview;
  - **Admin tools:** Admin assist (auto rules), pending posts, potential spam, scheduled posts, admin activity log, rules, member-reported content, moderation alerts, group status, community roles;
  - **Settings:** group settings, add features.
- **Main area:**
  - Invite and Share;
  - an **anonymous post** composer option;
  - a Featured card with a **setup carousel**.
- Systems: [SYS-09](02-systems-catalog.md#sys-09-groups), [SYS-26](02-systems-catalog.md#sys-26-trust-safety-moderation-and-admin).

## S33. Member profile inside a group
- **Header.** Cover, role "Admin", Message, View profile and a single "Group posts" tab.
- **Posts and Comments sub-tabs.**
- **Post cards.** An "**AI content**" label and a "you are commenting as …" notice.
- **Side cards:**
  - "Admin since";
  - "**Member summary**", visible only to admins and moderators: 90-day moderation actions, a 30-day **participation chart** (posts and comments) and **badges**.
- Systems: [SYS-09](02-systems-catalog.md#sys-09-groups), [SYS-26](02-systems-catalog.md#sys-26-trust-safety-moderation-and-admin).

## S34. Page with the "Manage Page" rail
- **Rail:**
  - a Page switcher;
  - creator dashboard, insights, planner, **monetization**, ad centre, create ads, settings;
  - "More tools": verification, **leads centre**, business suite;
  - a "**Switch to this Page**" card;
  - a sticky **Promote** button.
- **Main area:**
  - Following, Message and Search;
  - tabs: All, About, Followers, Photos, **Mentions**, More;
  - a "switch to manage" banner;
  - a details card with **rating "no reviews yet"**.
- Systems: [SYS-10](02-systems-catalog.md#sys-10-pages), [SYS-29](02-systems-catalog.md#sys-29-acting-identity-profile-and-page-switching), [SYS-23](02-systems-catalog.md#sys-23-creator-studio).

## S35. Page, scrolled
- **Banner.** The switch banner is sticky.
- **Post.** Carries the AI-content label, a "See more" truncation, "See insights" and "Create ad", and a "commenting as" warning.
- **Side cards.** Details (rating, location), Links, **Contact info**, Photos.
- Systems: [SYS-10](02-systems-catalog.md#sys-10-pages).

## S36. Profile About tab and stacked collections
- **About navigation** (14 sections): intro, **category**, personal details, links, **communities**, offers, work, education, **hobbies**, **interests**, **travel**, contact, privacy & legal, **other names**.
- **About content.** A bio with an audience control and **pinned details**.
- **Collections below:**
  - Reels (yours / saved);
  - Photos (of you / yours / **albums**);
  - Groups;
  - Events (past / upcoming);
  - Friends (all, **recently added**, **birthdays**, **current city**, followers, following);
  - **Places visited**;
  - **Reviews**.
- Systems: [SYS-17](02-systems-catalog.md#sys-17-profile), [SYS-18](02-systems-catalog.md#sys-18-photos-and-albums), [SYS-11](02-systems-catalog.md#sys-11-events), [SYS-09](02-systems-catalog.md#sys-09-groups).

## S37. Profile Photos tab
- **Grid.** Six columns with edit pencils.
- **Tabs.** Of you / yours / albums.
- **Controls.** Search and add.
- **Loading.** Infinite scroll.
- Systems: [SYS-18](02-systems-catalog.md#sys-18-photos-and-albums).

## S38. Profile Reels tab
- **Grid.** 9:16 tiles with view counts, plus a skeleton loading state.
- **Tabs.** Yours / saved, plus "Create reel".
- Systems: [SYS-06](02-systems-catalog.md#sys-06-reels).

## S39. Create live video hub
- **Rail:**
  - Home and Saved settings;
  - host identity;
  - destination picker ("post on your profile");
  - Report a problem.
- **Cards.** **Go live** (camera or streaming software) and **Create live video ad**.
- **Tabs.** Past lives, Live now, Scheduled lives. All show an empty state.
- Systems: [SYS-08](02-systems-catalog.md#sys-08-live-video), [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S40. Create reel editor
- **Wizard.** Two steps: Edit › Settings.
- **Chips.** People, feeling, location, collaborator.
- **Fields.** Description, uploaded clip with a Cover badge and progress, replace media.
- **Edit tools.** **Audio**, crop, **closed captions**, **audio descriptions**, **transcripts**.
- **Preview player:**
  - an upload percentage;
  - a **timeline** with a ruler, filmstrip and **trim handles**;
  - mute, loop, and an "+ Add music" lane.
- Systems: [SYS-06](02-systems-catalog.md#sys-06-reels), [SYS-27](02-systems-catalog.md#sys-27-accessibility-display-and-i18n).

## S41. Business portfolio settings (verification upsell)
- **Settings tree:**
  - business info;
  - **Users:** people, partners, system users;
  - **Accounts:** Pages, ad accounts, asset groups, apps, messaging accounts;
  - data sources, requests, brand safety, integrations, billing.
- **Main panel.** A verified-subscription waitlist with a badge and perks (impersonation protection, support).
- **Theme and chrome.** Light, with the floating assistant button at the bottom end corner.
- Systems: [SYS-24](02-systems-catalog.md#sys-24-tara-business), [SYS-21](02-systems-catalog.md#sys-21-settings-privacy-and-account-center).

## S42. Portfolio and asset switcher over Monetization
- **Popover, first pane.** Business portfolios, each with "N assets", plus "Create portfolio".
- **Popover, second pane.** The selected portfolio's assets with radio selection, "Add ▾", an overview link, settings and a search box.
- **Behind the popover.** Monetization eligibility: 500 followers, 30 days of activity, policies, country.
- Systems: [SYS-24](02-systems-catalog.md#sys-24-tara-business), [SYS-23](02-systems-catalog.md#sys-23-creator-studio).

## S43. Creator marketing hub
- **Sub-navigation:**
  - Home;
  - Creators: discover, view, permissions, campaigns, messages;
  - Content: browse, lists.
- **Cards:**
  - "Manage partner content" (empty; "authorize content with an ad code");
  - "Top recommendations" (eligible 3 days after publishing);
  - active partnerships;
  - help links.
- Systems: [SYS-24](02-systems-catalog.md#sys-24-tara-business), [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S44. Business home
- **Sidebar.** An asset switcher, then:
  - Home, Notifications, Ads manager, **Inbox**, Content, Creator marketing, Planner, Ads, Insights, Monetization, All tools;
  - Search (Ctrl+K), Settings, Help.
- **Hero.** Cover, avatar cluster, followers counters. The second counter is the sister photo app's follower count: **out of scope** (Tara has no sister app; see the out-of-scope list in 02). Tara shows only its own followers count.
- **Action row.** Create post / ad / reel / story.
- **To-do list.** Unread messages and comments.
- **Content tabs.** Planner, Posts & Reels, Stories. Each card has **Boost** and "View insights".
  - **Boost-eligibility state.** Some cards show a **disabled "Promote unavailable"** button instead of Boost. The capture gives no reason on the card, so Tara defines its own eligibility rule and must show the reason in a tooltip (03 #16, #68).
- **Other cards:**
  - Recent ads (empty state, "Create ad"). The card lists new, active and completed ads from the **last 60 days** only;
  - "Grow" tips (dismissible);
  - a **follower goal ring** with "Invite friends".
- **Theme and chrome.** Light gradient background. A round **floating assistant button** sits at the bottom end corner (left in RTL).
- Systems: [SYS-24](02-systems-catalog.md#sys-24-tara-business), [SYS-25](02-systems-catalog.md#sys-25-tara-ads), [SYS-30](02-systems-catalog.md#sys-30-tara-assistant-ai).

## S45. Groups discover
- **Rail.** Your feed, Discover, Your groups, Create, managed list and joined list (each with last active).
- **"Friends' groups" carousel.** Each card has a cover, ×, name, "68K members · **60 posts a day**", friend avatars with "X and 338 friends are members", and Join.
- **"More suggestions".** A six-column grid in the same card format.
- Systems: [SYS-09](02-systems-catalog.md#sys-09-groups).

## S46. Your groups
- **Header.** "All groups you've joined (542)" with **Sort** (date added / last visited).
- **Card grid.** Each card shows "You last visited 7 h ago", View group, and a `…` menu (leave, unfollow, notifications, **pin**).
- Systems: [SYS-09](02-systems-catalog.md#sys-09-groups).

## S47. Ads: campaign table and Create modal
- **View chips.** All ads, Active, Delivered, Actions, more.
- **Search.** A natural-language filter.
- **Level tabs.** **Campaigns | Ad sets | Ads**.
- **Toolbar:**
  - Create, Duplicate, Edit, **Analyze**, **A/B test**, More;
  - a date range;
  - **Columns ▾**, **Breakdown ▾** and a third **grouping ▾** dropdown (labelled "Groups"), then Export, a chart toggle and "Create view".
- **Columns.** Toggle, delivery, attribution, results, cost per result, budget, spent, impressions, reach, end date, bid strategy.
- **Drafts.** Draft rows are tinted. "**Review and publish (N)**" and "Discard drafts".
- **Delivery status per row.** One row shows "Draft"; another shows **"Account disabled"**, so delivery status reflects the ad-account state, not only the campaign state.
- **Create modal.** Two **tabs**: "New campaign" and "**New ad or ad set in an existing campaign**". The first tab has Buying type (Auction) and the objective, one of **Awareness, Traffic, Engagement, Leads, App promotion, Sales**, each with an icon and a side explanation. "Continue" stays disabled until an objective is chosen.
- **Theme and chrome.** Light. A round **floating assistant button** at the bottom end corner.
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads), [SYS-30](02-systems-catalog.md#sys-30-tara-assistant-ai).

## S48. Ads: campaign editor (draft)
- **Panes.** A tree pane (Campaign › Ad set › Ad) and a breadcrumb.
- **Cards:**
  - name and "Create template";
  - details: buying type and objective;
  - **Budget strategy**: campaign budget vs ad-set budget;
  - daily budget $200 with projections (max daily, weekly cap);
  - **bid strategy**.
- **Aside:**
  - a **campaign score ring (100)** with recommendations;
  - an "Account disabled" error card.
- **Footer.** Close and Next.
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S49. Ads: ad-account switcher
- **Popover.** Portfolios with their ad accounts, "Your account", and the ad account ID with a status ring.
- **Table behind.** Attribution "7-day click" and results per lead.
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads), [SYS-24](02-systems-catalog.md#sys-24-tara-business).

## S50. Ads: campaign table with three campaigns
- **Order.** The new draft sits at the top. The table is sorted by delivery.
- **Footer.** "Results from 3 campaigns".
- **What it shows.** Unpublished drafts appear in the table before publishing (a draft-first workflow).
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S51. Ads: account overview
- **Header.** "Spent in last 7 days" and "% spent in learning phase".
- **Alerts card.** "Ads paused, verify business location".
- **Opportunity score.** A gauge plus "auto-apply". The score is unavailable while the account is restricted.
- **Top campaigns card.** Shown in its empty state.
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S52. Ads: reporting
- **Sub-navigation.** Reports and Exports.
- **Reports table.** Columns: name, last accessed, modified, created. Shown empty.
- **Buttons.** "+ Create report" and "Export history".
- **Templates.** Suggested templates: ROI snapshot, reach & frequency, overall performance, leads summary.
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S53. Ads: ad settings (the file name says Audiences)
- **Header.** Title "Ad settings" with a lead line, an **ad-account selector** (name and ID), an **"Ad account settings"** button and a **"Billing & payments"** link.
- **Shortcuts card** (dismissible with ×). Audience controls, placement controls, **engaged audience**, **existing customers**. All are "Not set".
- **Audience evidence.** This is the only audience evidence in the captures. There is no audience list or audience-builder screen, so every audience requirement in 02 and 03 (#135–#137) is **inferred**.
- **Business section.** Account controls and **value rules**.
- **Create-ads section:**
  - creative features;
  - **audience segments**;
  - verification and **beneficiary/payer** transparency;
  - **datasets & pixels** (Tara: data sources / tracking tag);
  - third-party reports;
  - **naming templates**.
- **Theme and chrome.** Light gradient background. A round **floating assistant button** at the bottom end corner.
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads), [SYS-30](02-systems-catalog.md#sys-30-tara-assistant-ai).

## S54. Ads: billing and payments
- **Sub-navigation.** Payment settings and payment activity.
- **Notices.** Account disabled, verify location, permissions required.
- **Current balance** with "Pay now".
- **Threshold billing.** You pay when the balance reaches $10 or on a set date.
- **Daily spending limit.** $5,000.
- **Payment method.** Automatic payments.
- **Help.** A "Take a tour" coach mark.
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S55. Ads: events manager
- **Sub-navigation.** Connect data, Overview, Datasets, Custom conversions, Integrations.
- **Dataset tiles.** Each has an ID, a total-events sparkline and "no integrations".
- **Promo cards.** Conversion measurement and "create web & app events".
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads).

## S56. "All tools" drawer
- **Shell.** The expanded ads sidebar.
- **Drawer.** A searchable site map grouped as:
  - Most used;
  - Business products;
  - Advertise: automated rules, reach planner, creative hub, instant forms;
  - Manage: media library, brand safety, payouts;
  - Engage: planner, inbox, sound collection, live dashboard, fundraisers;
  - Analyze: experiments, creative reports;
  - Sell: appointments, commerce manager, monetization.
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads), [SYS-24](02-systems-catalog.md#sys-24-tara-business).

## S57. "All tools" drawer, scrolled
- The same drawer as S56, scrolled to the lower groups (Engage, Analyze, Sell).
- It confirms that the site map is one flat, keyword-searchable list grouped by intent.
- Systems: [SYS-25](02-systems-catalog.md#sys-25-tara-ads), [SYS-24](02-systems-catalog.md#sys-24-tara-business).
