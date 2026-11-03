# TARA – Complete Social Platform Experience (owner's specification)

Received from the owner on 2026-11-03. It extends the master project instruction.
Reference screenshots (Facebook layouts: profile, feed, menu, Business Suite planner,
login, Pages manager) are kept outside the repo because they show third parties; the
layout notes below summarise them.

## Layout notes from the reference screenshots
- **Top bar:** logo and search on the start side; centre icon tabs (Home, Video/Reels, Marketplace, Groups, Gaming) with an underline on the active tab; on the end side: apps grid (main menu), Messenger, notifications with a counter badge, avatar with a chevron.
- **Profile:** wide cover photo; a large round avatar overlapping the cover's bottom edge; name with an alternative-script name; follower/following counts; action buttons (Following, Send message, Add friend, more); bio with a link on the end side; a metadata line (category, city, social handle); tabs (All, About, Reels, Photos, Friends, More) and a "…" button.
- **Profile body:** a left column with a "Personal details" card (city, gender), links, contact info with social icons, and a photos grid with "See all photos"; a right column with a posts header, a Filter button and the post cards.
- **Post card:** an inline comment thread under the post (author badge, reply indented, reactions summary on the end side), a comment composer with emoji, camera, GIF and sticker icons.
- **Home:**
  - **Left sidebar:** the profile shortcut, then Friends, Memories, Saved, Groups, Reels, Marketplace, Feeds, Events, "See more", then a "Your shortcuts" section and a footer with links.
  - **Centre:** a composer ("What's on your mind, <name>?") with live-video, photo and feeling icons; a stories rail with a "Create story" card and a next arrow; posts; an inline "Why don't you want to see this?" feedback card after hiding a post (reasons: not interested, spam, sexual, annoying, don't like the creator, other; plus snooze 30 days, unfollow, report photo, undo); a Reels rail in the feed.
  - **Right column:** Sponsored (clearly labelled), then Birthdays.
- **Business Suite planner:** a dark dashboard with a right side nav (Home, Insights, Content → Content library, Planner, Engagement, All tools, "Create post") and a month calendar of scheduled posts with times, today highlighted, the time zone shown, and Today, prev, next and Month controls.
- **Login:** logo top-left; a large headline with a coloured accent word; a collage of illustrations; a login card on the end side (email or phone, password, Log in, Forgotten password?, Create new account outline button); a languages row in the footer.
- **Pages manager:** a side nav (Create page, Business Suite, Inbox, Insights, Explore, Followed pages, Invitations with a count). Under "Pages you manage", cards with avatar, name, notification and message counts, and Create post, Promote and "…" buttons. A "Deactivated pages" panel with Activate buttons.

**Rule:** follow these layouts and interaction patterns, but with TARA's own brand identity, logo, colours and wording. Never reuse Facebook's name, logo or assets.

---

## Specification (verbatim from the owner)

You are working as the Principal Product Architect and Senior Full-Stack Engineering Team for TARA.
Your task is to build a complete, professional, production-ready social networking experience inspired by Facebook, Instagram, LinkedIn, TikTok, and modern social platforms.

IMPORTANT: This instruction extends the previous TARA MASTER PROJECT INSTRUCTION. Do not create a separate application. Do not create a disconnected frontend. Preserve existing functionality, database records, authentication, APIs, and working components. The goal is to make TARA feel like a complete international social networking platform.

VERY IMPORTANT: The default homepage for visitors who are NOT authenticated must be a professional LOGIN AND REGISTRATION LANDING PAGE. Do NOT show the internal social feed to unauthenticated visitors. Create a landing experience inspired by Facebook's login experience but with the unique TARA brand identity.

LANDING PAGE DESIGN. Left side: TARA logo; strong brand headline; short description of the platform; highlight the social ecosystem; modern illustrations or subtle branding graphics. Right side: login card; email or username input; password input; show/hide password; remember me; forgot password; login button; create new account button.

REGISTRATION. Build a complete registration experience. Fields: first name; last name; username; email; phone number where appropriate; password; confirm password; date of birth; optional profile picture; terms and privacy agreement. Include: username availability validation; email validation; password strength indicator; duplicate account protection; email verification; secure password reset; account activation; login error handling; session management.

SOCIAL AUTHENTICATION: prepare integration for supported social login providers where appropriate.

AUTHENTICATED REDIRECTION: after successful login, redirect users to /home. The authenticated home page must display the TARA social feed. Unauthenticated users accessing protected pages must be redirected to the login page. Implement proper route guards on both frontend and backend.

Create a consistent global navigation system across the platform.

DESKTOP NAVIGATION. Top bar: TARA logo; global search; Home; Friends; Video; Marketplace; Groups; Messages; Notifications; account avatar; main menu.

LEFT SIDEBAR: an intelligent navigation sidebar containing: 1. My Profile 2. Friends 3. Memories 4. Saved Items 5. Groups 6. Pages 7. Marketplace 8. Reels 9. Videos 10. Live 11. Events 12. Gaming, if supported 13. Creator Studio 14. Professional 15. Ads Manager 16. Business Center 17. Settings 18. Help and Support. Include a "See More" and "See Less" mechanism. Allow navigation customization where appropriate.

MOBILE NAVIGATION: a dedicated responsive mobile navigation. Include: Home; Friends; Create; Video/Reels; Notifications; Menu. Do not simply shrink the desktop sidebar. Create a mobile-first navigation experience.

Create a professional expandable main menu similar to Facebook's menu. Organize all platform services into categories.
- YOUR ACCOUNT: Profile; Friends; Saved; Memories; Activity Log.
- SOCIAL: Home Feed; Stories; Reels; Videos; Groups; Events; Live.
- COMMERCIAL: Marketplace; My Listings; Business Center; Ads Manager.
- CREATOR: Creator Studio; Content Library; Analytics; Monetization readiness.
- PROFESSIONAL: Professional Profile; Companies; Jobs; Applications.
- COMMUNICATION: Messenger; Message Requests; Archived Conversations.
- MANAGEMENT: My Pages; My Groups; Page Management; Group Management.
- SYSTEM: Settings; Privacy Center; Security Center; Help Center; Support.
The menu must adapt to the user's permissions and account type.

Build a complete notification system. Create a notification dropdown and a full notification center.
NOTIFICATION TYPES: friend requests; friend request accepted; new followers; likes; reactions; comments; comment replies; mentions; post shares; new messages; group invitations; group posts; page activity; marketplace activity; product inquiries; professional opportunities; advertising campaign updates; administrative notifications.
FUNCTIONALITY: mark as read; mark all as read; delete notification; notification filtering; notification categories; notification preferences; notification timestamps; unread notification counter; real-time notifications. Use WebSockets or an appropriate real-time architecture. Avoid duplicate notifications. Respect user privacy and notification preferences.

Build a complete professional messaging experience.
MAIN INBOX: all messages; unread messages; archived messages; message requests; spam requests; group conversations; business conversations.
CHAT FEATURES: one-to-one chat; group chat; real-time messaging; text messages; voice messages; images; videos; documents; file attachments; message replies; message reactions; message forwarding; message editing; message deletion; message search; typing indicators; online status; last active status; read receipts; delivered status; pinned messages; conversation mute; conversation archive; block and report.
CHAT UI: a three-panel desktop experience. Left: conversation list and search. Center: active chat. Right: conversation details and shared media. On mobile, use a dedicated conversation navigation experience. Prepare architecture for voice and video calls. Apply proper authorization to every conversation and attachment.

Create a complete and customizable user profile.
PROFILE HEADER: cover photo; profile picture; full name; username; bio; verification status where applicable; location if publicly shared; website; followers; following; friends; profile action buttons.
PROFILE TABS: 1. Posts 2. About 3. Friends 4. Photos 5. Videos 6. Reels 7. Check-ins 8. Likes where privacy permits 9. Marketplace listings 10. Professional information.
PROFILE ACTIONS: add friend; accept request; follow; unfollow; message; share profile; copy profile link; block; report; manage profile.
ABOUT SECTION: basic information; work; education; skills; interests; websites; contact information according to privacy settings.
ACTIVITY: create a personal activity log showing the user's activities and interactions according to permissions. Allow users to control profile visibility.

Create TARA CREATOR STUDIO as an independent professional dashboard. This is a major feature.
DASHBOARD: total followers; follower growth; total views; total reach; engagement; content performance; top-performing posts; top-performing videos; Reels performance; audience overview.
CONTENT MANAGEMENT: create posts; upload videos; upload Reels; schedule content; edit content; delete content; save drafts; manage published content; content calendar; manage comments.
ANALYTICS: views; reach; likes; comments; shares; saves; watch time; audience growth; engagement rate.
MONETIZATION: prepare a future-ready monetization architecture. Do not display fake earnings or enable payments without actual payment infrastructure. Allow users to access Creator Studio according to eligibility and permissions.

Build a centralized SAVED CENTER. Users must be able to save: posts; videos; Reels; products; marketplace listings; pages; groups; events.
SAVED ORGANIZATION: all saved items; saved posts; saved videos; saved products; saved Reels; custom collections.
FUNCTIONALITY: save item; remove saved item; create collection; rename collection; delete collection; move items between collections; add notes; search saved items; filter by type; sort by date. Ensure users can only access their own private saved items.

Build a complete Pages Management Center. VERY IMPORTANT: ANY AUTHENTICATED USER SHOULD BE ABLE TO CREATE A PAGE, subject to platform policies and anti-abuse protections. Do not restrict page creation exclusively to business accounts.
PAGE CREATION: allow users to create business pages; brand pages; public figure pages; creator pages; community pages; organization pages; educational pages; entertainment pages; local service pages.
PAGE CREATION FIELDS: page name; username / URL; category; description; profile image; cover image; website; contact details; location where appropriate; action button; privacy and visibility configuration.
PAGE MANAGEMENT DASHBOARD: overview; page posts; followers; audience insights; messages; notifications; media; reviews; events; settings; admin roles; moderation; advertising; performance analytics.
PAGE ROLES: owner; administrator; editor; moderator; analyst; advertiser. Implement proper granular permissions.
PAGE ACTIONS: publish posts; upload images; upload videos; create Reels; schedule posts; respond to comments; respond to messages; invite followers; manage reviews; promote posts; manage advertising campaigns. Allow multiple administrators to manage the same page. Every page must have a public URL and a professional public profile.

VERY IMPORTANT: ANY AUTHENTICATED USER SHOULD BE ABLE TO CREATE A GROUP.
GROUP TYPES: public groups; private groups; hidden groups.
GROUP CREATION: group name; description; cover image; category; rules; privacy type; membership approval; group URL.
GROUP FEATURES: group feed; group posts; group comments; group media; group events; group announcements; member invitations; member requests; member management; group search; group recommendations; group notifications; group moderation.
GROUP ROLES: owner; administrator; moderator; member.
GROUP ADMINISTRATION: approve membership requests; remove members; ban members; manage posts; pin announcements; create rules; manage permissions; review reported content. Create a professional Group Management Dashboard.

Build a complete settings center. Organize settings into separate sections.
- A. ACCOUNT SETTINGS: name; username; email; phone number; password; account status; account deactivation; account deletion; login sessions.
- B. PRIVACY SETTINGS: who can see my posts?; who can see my friends?; who can send friend requests?; who can follow me?; who can message me?; who can comment on my posts?; who can tag me?; profile visibility; search engine visibility; online status visibility.
- C. SECURITY SETTINGS: change password; two-factor authentication; login alerts; active sessions; recognized devices; login history; account recovery; suspicious activity alerts.
- D. NOTIFICATION SETTINGS: push notifications; email notifications; in-app notifications; likes; comments; friend requests; messages; groups; pages; marketplace; ads.
- E. CONTENT PREFERENCES: feed preferences; favorite accounts; hidden accounts; muted accounts; blocked accounts; restricted accounts; sensitive content preferences; autoplay settings.
- F. LANGUAGE AND ACCESSIBILITY: language; time zone; date format; text size; reduced motion; accessibility preferences.
- G. APPEARANCE: dark mode; light mode; system mode; theme preferences.
- H. ACCOUNT CENTER: a centralized place to manage the user's connected Tara identities, personal profile, business identities, and page access.
Implement secure confirmation flows for sensitive actions.

Create a powerful unified search system. Search must be accessible from the main navigation on every authenticated page.
SEARCH UI: large modern search field; search icon; search suggestions; recent searches; trending searches; autocomplete; keyboard navigation; search history; clear search history.
SEARCH CATEGORIES: 1. All 2. People 3. Posts 4. Photos 5. Videos 6. Reels 7. Pages 8. Groups 9. Marketplace 10. Products 11. Companies 12. Jobs 13. Events 14. Hashtags.
SEARCH BEHAVIOR: when users enter a query, show relevant suggestions instantly where appropriate. Examples:
- Searching for a person's name: show matching profiles; profile picture; name; username; mutual connections if available and permitted; Follow or Add Friend actions.
- Searching for a page: show matching pages; page category; page image; follower count where public; Follow button.
- Searching for a product: product images; price; seller; category; location where appropriate.
- Searching for content: matching posts; videos; Reels; hashtags.
SEARCH FILTERS: date; category; location; content type; relevance; most recent.
SEARCH RESULTS PAGE: a dedicated search results page with category tabs and contextual filters.
SEARCH ENGINE REQUIREMENTS: use database indexing; implement pagination; prevent duplicate results; apply access permissions; exclude private or blocked content; optimize query performance; support Arabic and English; support partial matching; handle Arabic search normalization appropriately; handle spelling variations where possible; use PostgreSQL full-text search or an appropriate search engine if justified by the existing architecture. Do not show private posts, private groups, or protected user information in search results to unauthorized users.

Create a unified Create button available throughout the platform. When clicked, show a professional creation menu.
OPTIONS: create post; add story; upload video; create Reel; go Live; create group; create page; list marketplace product; create event; publish professional post.
POST CREATION: text editor; image uploads; video uploads; multiple media; tag people; add location; add hashtags; select audience; comment permissions; schedule publication; save draft. Provide a consistent content composer throughout the ecosystem.

After successful login, the user must land on the Home Feed. Build a rich, modern social feed.
DESKTOP LAYOUT:
- LEFT COLUMN: profile shortcut; navigation; friends; saved; groups; pages; marketplace; Creator Studio.
- CENTER COLUMN: stories; create post; feed; post cards; suggested posts.
- RIGHT COLUMN: contacts; suggested friends; trending topics; recommended groups; recommended pages; events.
FEED FEATURES: personalized ranking; latest posts; friends posts; followed pages; group content; recommended content; sponsored content with clear labeling. Feed preferences: most relevant; most recent; favorites; following. Create a beautiful empty state for new accounts. Do not use hardcoded fake users in production.

All modules must support desktop, laptop, tablet and mobile. Build dedicated mobile layouts where needed. Mobile requirements: touch-friendly navigation; bottom navigation; mobile messaging; full-screen Reels; responsive Marketplace; responsive profile pages; mobile notifications; mobile settings. Avoid horizontal overflow.

Every feature must be connected to the actual backend. Implement: models; database migrations; serializers; API endpoints; views; permissions; business logic; notifications; background tasks where needed; real-time events where needed. Avoid duplicate models. Reuse existing user models and authentication systems. Ensure proper relationships among users, profiles, posts, pages, groups, followers, friends, messages, notifications, saved items, marketplace listings and creator content. Use proper indexing and pagination.

Implement role-based access control. Differentiate between regular users, page owners, page administrators, group owners, group moderators, business owners, advertisers, content creators, platform moderators and super administrators. A user's permissions must be checked on the backend, not just hidden in the frontend. Users must only manage resources they own or are authorized to manage.

Use the official TARA brand identity: PRIMARY #6A00F4, SECONDARY #A855F7, ACCENT #FF4ED8, DARK #0B0B1F, LIGHT #E8E6FF. Create modern layouts; premium cards; elegant sidebars; professional dropdowns; consistent buttons; modern dialogs; loading skeletons; empty states; error states; success messages; toast notifications; smooth transitions. The design should feel like a premium international social platform. Avoid generic dashboard templates.

Before implementation: 1. Inspect existing Tara architecture. 2. Inspect QTech for reusable functionality. 3. Review previous implementation progress. 4. Identify missing systems. 5. Prepare an integration plan.

During implementation: work module by module; preserve existing data; use safe migrations; keep backward compatibility; connect real APIs; do not use mock functionality; document changes.

TEST: registration; login; logout; authentication; search; feed; posts; comments; messaging; notifications; settings; profile; pages; groups; saved items; Creator Studio; permissions; responsive layouts. Fix all critical issues before marking a module complete.

TARA must become a complete social platform where users can: create accounts; connect with people; share content; create pages; create groups; manage businesses; send messages; publish videos; create Reels; sell products; advertise; build professional identities; manage their content; track analytics; control their privacy and security. The entire ecosystem must use ONE account system, ONE coherent design language, and integrated navigation.

START BY AUDITING THE EXISTING PROJECT. Then prepare a detailed implementation checklist and proceed module by module. Never claim a feature is complete unless it is actually implemented, connected to the backend, permission-protected, and tested.

The owner added: follow the Facebook design idea exactly (layouts and page ideas shown in the screenshots), in addition to the specification above.
