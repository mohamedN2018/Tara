# Brief 2: Advanced intelligent feed, discovery and recommendation (owner, 2026-11-05)

The owner sent this brief while Tara Intelligence phases 2–4 were already being built. It extends [00-master-spec.md](00-master-spec.md). This file is a condensed record of the brief: it keeps every requirement.

## The problems the owner reports
- People see the same posts again when they reopen the site.
- The homepage has too few recommendations.
- There are not enough suggested posts, videos and Reels.
- Discovery is weak: people do not keep finding new creators, pages, groups and topics.
- The homepage feels static and does not adapt to behaviour.

Do not assume the current implementation is correct. Find the actual causes.

## Part 1: inspect first
Inspect:
- the architecture, home and feed;
- the models and relationships (posts, videos, Reels, pages, groups, profiles, follows);
- the APIs, queries, serializers, views, services and frontend;
- auth and sessions, caching, pagination and loading;
- any existing ranking;
- duplicated logic and bottlenecks;
- **why users see the same content again**.

The audit lists:
- existing and missing functionality;
- technical problems;
- database, frontend and performance limitations;
- the recommended architecture.

Improve what works rather than rebuilding it.

## Part 2: engines
1. **User Interest Engine.**
   - Signals: views, watches, Reel completions, watch time, rewatches, reactions, comments, shares, saves, follows, searches, profile and page visits, groups joined, topics explored, hides, not-interested.
   - Interest tiers: long-, medium- and short-term, emerging, explicit, negative.
   - Interests evolve with behaviour, and the user can inspect and edit them.
2. **Session Intelligence Engine (critical).**
   - Inputs: current activity, recently viewed items, current searches, topics getting attention, videos watched in the session, skips, repeated interactions, format preferences, and changes in behaviour.
   - Example: a technology viewer who starts watching cooking gets more cooking, gradually.
   - Lifecycle: create, track, expire, history, session-level interest updates, session-aware feed.
   - It must tell a refresh apart from a new visit, a returning visit and an ongoing session.
3. **Candidate Retrieval Engine.**
   - Sources: friends, follows, pages, groups, public communities, recommended creators, trending, public posts, videos, Reels, educational, professional and local content, new and emerging creators.
   - Retrieval must be efficient, never a scan of the whole content table.
4. **Ranking Engine.**
   - Signals: interest relevance, session relevance, relationship strength, freshness, predicted watch time and completion, meaningful interaction, content and creator quality and trust, past feedback, diversity, repeated exposure, negative feedback, eligibility and safety.
   - Never rank by likes alone.
   - Weigh candidate generation, collaborative filtering, content-based and hybrid approaches, learning-to-rank, two-tower and sequence-aware models, and contextual and multi-objective ranking. Choose what fits Tara's scale.
   - No heavy ML without a measurable benefit. Start with an explainable baseline that is ready for ML.

## Part 3: feeds
For You, Following (chronological plus an optional relevance sort), Friends, Groups, Video, Reels, Professional (business, career, education) and Explore. They share infrastructure, but each has its own strategy.

## Part 4: Reels and video engine
- Signals: watch time, completion, rewatches, skips, category, audio and topic metadata, creator history, engagement quality, interest similarity, freshness, negative feedback.
- Features to build:
  - personalized ranking;
  - new-creator discovery;
  - topic-based recommendations;
  - diversity;
  - suppression of videos already seen;
  - injection of fresh videos;
  - quality and safety filtering;
  - updates from feedback.
- Not the post ranker reused: it has its own features and objectives.

## Part 5: dynamic refresh and rotation
1. **Refresh on return.**
   - Check for new eligible content and recompute or fetch an updated feed.
   - Bring in new content without repeating the same sequence.
   - Keep relevant items that have not been consumed.
   - Rotate by relevance, never by random shuffle.
2. **Pull-to-refresh.** New content without duplicating visible items, and the browsing position is kept.
3. **Infinite scroll.**
   - Cursor-based, with no duplicates and no repeats from earlier batches.
   - Works on slow connections, with loading and error states.
   - Scrolling stays stable.
4. **Freshness.** Fresh content gets a fair chance, but freshness never overrides relevance and quality.
5. **Seen-content management.**
   - Separate states: retrieved, displayed, viewed, meaningfully consumed, skipped.
   - Fetching an item is not seeing it. Content is never suppressed permanently.

## Part 6: diversity and exploration
- Avoid:
  - too much from one creator;
  - too many videos in a row;
  - too much from one category;
  - one format repeated;
  - too many ads;
  - near-identical topics.
- An exploration engine adds new topics, creators, pages, communities and formats, plus related and unexpected-but-relevant items.
- Balance exploration against exploitation.

## Part 7: scenarios
- **A, new user:** optional interests, popular public content, topics, creators, communities, quality recent posts. The homepage is never empty.
- **B, returning after days:** what is new since the last visit, chosen interests, new creators, unseen relevant posts, changes in followed accounts.
- **C, very active user:** a bigger pool, new creators, no repeats, adapting interests, quality kept.
- **D, interest shift:** adapt without erasing older interests.
- **E, few friends:** public content, pages, communities, creators, trending.
- **F, one strong topic:** relevance plus variety and related subjects.

## Part 8: homepage UX
- Candidate sections:
  - For You, Following, Friends;
  - recommended posts, videos and Reels;
  - suggested creators, pages and groups;
  - trending topics and topics you may like;
  - Continue Watching;
  - New Since Your Last Visit;
  - Popular in Your Communities;
  - Recently Active Creators.
- Never show all of them at once. Placement is intelligent and contextual, and users can customize the homepage.
- Reasons are shown when useful, such as "because you follow this topic", "popular in your communities", "similar to videos you watched" or "new creator you may like". They never expose sensitive inferences.
- Clean and responsive on desktop and mobile, and never overwhelming.

## Part 9: feedback controls
- Actions: Not interested, Show less, Show more, Hide post, Hide creator, Mute topic, Unfollow, Block, Report, Why am I seeing this?, Reset recommendations, Manage interests.
- Every action affects future recommendations.
- The UI makes the difference between hiding content, muting a topic and blocking a creator clear.

## Part 10: data and backend
- Use the minimum new structures for:
  - interests and activity events;
  - impressions and consumption, watch history;
  - feedback;
  - feed sessions;
  - candidates and ranking metadata;
  - topic classification;
  - explanations.
- Extend existing models where that works.
- Cover: indexes, cursor pagination, background jobs, caching, event processing, result expiry, generation performance.
- Follow Django conventions and run expensive work asynchronously, never on every request.
- User-specific data stays isolated and secure.

## Part 11: analytics
- **Metrics:**
  - impressions, unique exposure, CTR;
  - watch time and completion;
  - meaningful interactions, saves and shares, negative feedback;
  - diversity, creator exposure, freshness;
  - returning-user behaviour;
  - feed load performance.
- Do not optimize for time spent alone. Optimize for satisfaction, relevance, quality, healthy discovery, meaningful interaction and user control.
- An internal analytics dashboard.

## Part 12: beyond existing platforms
Evaluate each idea: concept, how it works, complexity, benefits, risks, and whether it belongs in the initial release or later.
1. Intent-aware recommendations.
2. Contextual sessions.
3. Interest evolution.
4. Cross-format recommendations.
5. A knowledge graph.
6. Semantic discovery.
7. Explanations.
8. Fresh-content opportunities.
9. Personal content modes.
10. Adaptive feed composition.
11. User-controlled algorithms.
12. Cross-platform intelligence across the social, professional, video and commerce sections.

Do not build speculative features before they are evaluated.

## Part 13: performance, security, privacy, safety
- **Content rules:**
  - respect visibility;
  - never recommend content from blocked users;
  - respect group restrictions;
  - exclude deleted content;
  - respect moderation.
- **Protection:**
  - do not expose private activity;
  - resist manipulation and engagement spam;
  - never deliver duplicates;
  - apply rate limits;
  - protect profiles.
- **User control:** personalization the user controls, and a reset of recommendation history.
- No N+1 queries.

## Part 14: testing and implementation
- **Order of work:** present the architecture, the components to modify, the new components, the ranking strategy, the database changes and the phases, then implement.
- **Testing:**
  - migrations;
  - APIs and the frontend;
  - pagination and refresh, duplicate prevention;
  - personalization, cold start, returning users;
  - permissions and privacy;
  - performance.
- **Rules:** add automated scenario tests. Never claim something is done before it is implemented and tested. No fake or demo content in production. No random content: if there is no ML model, ship a real explainable baseline.

## Part 15: deliverables
The deliverables are:
- the audit and the architecture;
- the engine design, session design, ranking strategy, database design and API design;
- the homepage redesign, refresh and pagination, and feedback controls;
- the dashboard, tests, performance analysis and documentation;
- a status report.

For each feature, list: files created and modified, database, API and frontend changes, tests run, and remaining limitations.

**The goal:** every time a user opens Tara, the homepage feels relevant, fresh, personalized and worth exploring.
