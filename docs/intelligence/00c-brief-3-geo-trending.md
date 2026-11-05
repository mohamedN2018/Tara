# Brief 3: geo-trending, viral discovery and content delivery (owner, 2026-11-05)

The owner sent this brief, in Arabic, after [Brief 2](00b-brief-2-intelligent-feed.md). It is condensed into English here; every requirement is kept. **Rules from the owner:** do not write random code; audit first, then architecture, plan, development, testing and a final report. Never claim a feature works before it is built and tested. Never show numbers or percentages that are not in the database.

## 1. Geo-Trending Engine
- **Levels:**
  - city;
  - governorate or province;
  - country;
  - geographic region (for example MENA);
  - global;
  - inside a community, a group or an interest area.
- **Example:** a user in Egypt sees Egypt's trends, their governorate or city when there is enough data, MENA and global. A user in Saudi Arabia sees Saudi and regional trends, and can explore Egyptian and global ones.
- **Where the location comes from:**
  - the country, region and city the user chooses;
  - the location settings in the account;
  - precise location only with explicit permission;
  - a separate setting for the country or region whose trends the user wants to follow.

  Precise location is never required. A user's precise location is never shown or tied publicly to their posts without permission.
- **Trending Score.** Not just total likes or views. The signals:
  1. growth velocity of views;
  2. growth velocity of interactions;
  3. shares and reposts;
  4. real comments and discussion;
  5. growth of topic interest over time;
  6. freshness;
  7. interactions per impression;
  8. number of distinct users who interacted;
  9. how far it has spread within the region;
  10. interest moving from one region to another;
  11. quality and credibility;
  12. negative signals, reports and manipulation.
- **Time windows:** rising now, the last hours, daily, multi-day, and topics that started in one region and then spread. The engine must tell content that is already popular apart from content that is rising fast.
- **Trending / Explore UI sections:**
  - Trending Near You;
  - Trending in Your Country;
  - Trending in Your Region;
  - Global Trending;
  - Rising Now;
  - Popular Hashtags;
  - Popular Topics;
  - Viral Videos;
  - Trending Reels;
  - Trending Posts;
  - Trending Creators.

  The sections are easy to switch between. Each trend gets a reason: growing in your region, among today's most discussed, gaining fast, or liked by people with similar interests. No fabricated numbers.

## 2. Viral content discovery
- **Applies to:** text, images, videos, Reels, educational, entertainment and news content, pages, groups and creators.
- **Lifecycle:**
  1. The content is published.
  2. It is tested on a suitable initial audience sample.
  3. Real engagement quality is measured.
  4. Spread velocity and retention are assessed.
  5. It is compared with similar content.
  6. The audience grows gradually if the results are good.
  7. Spread quality is monitored after the expansion.
  8. Distribution drops when strong negative signals appear.
- **Fairness:** content does not spread because its author is famous or has many followers. Good content from new accounts gets a fair chance.
- **Protection against:**
  - fake accounts;
  - artificial engagement;
  - like-exchange rings;
  - bought views;
  - bot comments;
  - repeated reposting of the same content;
  - trend manipulation through many accounts.

## 3. Location-aware recommendation
- **Example:** someone in Cairo who likes technology gets a mix of:
  - technology trending in Cairo;
  - technology trending in Egypt;
  - global technology;
  - posts from people and pages they follow;
  - new content from suitable creators.
- **Balance:** location never controls the feed on its own. It is weighed against personal interests, geographic relevance, social connections, quality, trend velocity, freshness, discovery and feedback.
- **Manual control:** the user can change their region by hand and explore other countries' trends.

## 4. Advanced feed delivery (very important)
- **Opening the page:**
  - Never load all posts, videos or Reels. Fetch a small, highly relevant first batch.
  - Show skeletons while waiting, and render progressively without freezing.
  - The first post never waits for all media.
  - The first batch size lives in configuration, not in code.
- **Infinite scroll:**
  1. Watch the scroll position.
  2. Prepare the next batch before the user reaches the end.
  3. Request it from the server.
  4. Append it without a page reload.
  5. Keep the scroll position.
  6. Do not show again what was already seen in the same session, except under a deliberate policy.
  7. Handle the end of content clearly.
  8. Handle errors with retry.

  Use IntersectionObserver or the stack's equivalent.
- **Cursor-based pagination, never page numbers.** It must cope with:
  - a changing order;
  - new posts arriving during browsing;
  - deletions and hides;
  - no duplicates between batches;
  - no lost posts.

  The order stays stable within a viewing session, with smart refresh when appropriate.
- **Frontend performance:**
  - lazy-loaded images and videos;
  - screen-sized responsive images;
  - progressive media;
  - a poster before playback;
  - no autoplay of everything: play near the viewport under a clear policy, and pause videos that are off-screen;
  - virtualization when needed;
  - caching of data and media;
  - limited, smart prefetch;
  - no repeated requests for the same item.

## 5. Feed session management
- **Distinguish between:**
  - a first visit;
  - a page refresh;
  - continuing the same session;
  - a short return;
  - a return after hours or days;
  - moving between Feed, Videos, Reels and Explore;
  - switching devices, when the data exists.
- **Track the item states:** fetched, actually displayed, viewed, engaged, skipped quickly, prefetched, not yet delivered. Never mix up impression, view and engagement. An impression is recorded by clear rules, never on fetch.
- **Repetition control:**
  - seen-content history;
  - recent-content cache;
  - duplicate detection;
  - repeated-author control;
  - repeated-topic control;
  - repeated-media detection when needed.
- The system knows a post was seen even without interaction. It never suppresses an item permanently after one exposure: the item can come back after a suitable time, or after a worthwhile update or new engagement.

## 6. Dynamic feed composition
- **An example mix (not a fixed order):** a friend's post, an interest video, a followed page, a Reel, a local trend, an educational post, a group post, a discovery post from a new account, an important global topic, a professional post. The mix depends on the user, the session and the feed type.
- **Avoid:**
  - long runs of videos;
  - the same author again and again;
  - locking the user into one topic;
  - ads crowding out organic content;
  - giving up quality for the sake of diversity.

## 7. Feed refresh intelligence
- **Triggers:** a manual refresh, a return to the site, time elapsed, important new content, a new trend in the user's region, interests shifting during the session.
- Opening the site at a new time never shows the same content in the same order.
- The user's position is never lost.
- A "New posts" (محتوى جديد) pill lets the user choose to load new items, instead of a sudden reorder while browsing.

## 8. Feed experiences
1. For You.
2. Following.
3. Friends.
4. Trending (by location and interest).
5. Videos.
6. Reels.
7. Groups.
8. Professional.
9. Explore.

Each has its own rules, on shared core services.

## 9. Ranking pipeline
- **Pipeline:** candidate generation → filtering → feature extraction → ranking → diversity → policy checks → delivery → feedback collection.
- **Candidate sources:** friends, follows, pages, groups, local, national, global trends, creators, new content, suggested content.
- **Ranking signals:** interest, session context, relationship, freshness, quality, viral velocity, geography, probability of a view, of completion and of a meaningful interaction, diversity, seen history, negative signals.
- **Weights:** evolvable and testable, never fixed numbers treated as the best for everyone.
- **Feedback loop:**
  - a full watch, a skip;
  - a hide, a Not Interested;
  - a follow, an unfollow;
  - a share, a save;
  - a search;
  - engagement with a local trend.

## 10. UX and visual design
- Learn from the Facebook Feed, Instagram, TikTok For You, YouTube Home and Shorts without copying them.
- **Cover:**
  - post cards, media layout and text size;
  - author info and action buttons;
  - view and engagement counts;
  - trend cards;
  - switching between modes;
  - loading, empty and error states;
  - mobile and desktop.
- Progressive loading feels smooth, with no stalls and no page rebuild on each request.

## 11. Trending dashboard and analytics (admin)
- **Shows:**
  - top topics by country, and by city when there is data;
  - rising trends and their growth rate;
  - the most viral posts, most-viewed videos and most viral Reels;
  - trends moving between regions;
  - abnormal-engagement indicators;
  - content excluded from trends, with the reason.
- **Moderation:** staff can review trends and act on violating content.

## 12. Backend, database and infrastructure
- **Services:** Trending Engine, Geographic Interest Engine, Content Discovery, Feed Candidate, Feed Ranking, Feed Session, Seen Content, Impression Tracking, Recommendation Feedback, Analytics.
- **To consider:** Redis (cache, sessions), background jobs for trends, queues for events, indexes, aggregation windows, event tracking, cursor pagination, a CDN for media, rate limiting.
- Reuse the Django architecture: no duplicated apps or tables, and no technology without a stated need, benefit, cost and fit.

## 13. Security, privacy and abuse
- **Location privacy:** never expose a user's location, and never use precise location without consent.
- **Content rules:**
  - respect post privacy;
  - keep private-group content out of public trends;
  - exclude deleted and banned content.
- **Abuse:** limit view and engagement manipulation, resist spam, prevent trend manipulation, apply moderation and reports.

## 14. Testing and performance
- **Scenarios:**
  1. first open;
  2. first batch only;
  3. scroll to the next batch;
  4. no duplicates between batches;
  5. refresh;
  6. return after a while;
  7. new content arriving during the session;
  8. trends differing between countries;
  9. trends differing between regions;
  10. a rising local trend;
  11. global trends;
  12. a new user with no history;
  13. a heavy-history user;
  14. a weak network;
  15. many concurrent users.
- **Measure:**
  - time to first content;
  - feed latency;
  - query count;
  - memory;
  - bytes transferred;
  - media request count;
  - order stability;
  - trend-detection accuracy;
  - diversity and repetition quality.

## 15. Required order of work and final report
- **Order:** audit → architecture → small-phase plan with the affected files → development without breaking anything → test each part and fix before moving on → final report.
- **The final report answers:**
  - what existed and what was built;
  - the files modified and the services and tables added;
  - how geo-trending works;
  - how progressive loading works;
  - how repetition is prevented;
  - how the ranking is computed;
  - which tests passed;
  - what is not built yet.
- **The goal:** not a chronological feed, but personal intelligence, geographic trends, viral discovery, continuous renewal, progressive loading, diversity and high performance.
