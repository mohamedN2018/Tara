# Tara Intelligence: master specification (owner's brief, 2026-11-05)

This is the owner's request as given. It is the input to the audit, the architecture and the phased plan in this folder.

## Mission
Design and implement **Tara Intelligence**, a personalized ranking, discovery and recommendation system, inside the existing Tara app: not a separate application, without breaking anything, with no fake or hardcoded recommendation results. It must be real, measurable and scalable.

## 1. Four-stage pipeline
1. **Inventory (candidates).**
   - Sources: friends, followed users, followed pages, joined groups, public communities, recommended users, pages and groups, public posts, videos, reels, trending and other relevant public content.
   - Multiple content types.
   - Privacy, blocking, moderation and visibility rules apply *before* ranking.
2. **Signals.**
   - **User:** follows, friendships, likes, comments, shares, saves, post clicks, profile visits, search interests, watch duration, completion, rewatch, skips, hides, reports, interested / not-interested, explicit topic preferences.
   - **Content:** publish date, type, author quality, originality, topic, hashtags, engagement quality, meaningful discussion, media quality, spam indicators, reports, visibility, language.
   - **Relationship:** past interactions with the author, follow, friendship, shared groups, mutual interests, past meaningful conversations.
3. **Predictions.**
   - Estimated quantities: P(meaningful engagement), P(like), P(comment), P(share), P(save), P(video completion), expected watch time, P(negative feedback), interest relevance.
   - Start with transparent rules, designed so ML models can replace or improve them later.
4. **Final ranking.**
   - Combines: predictions, interests, relationship strength, relevance, freshness, quality, diversity, originality, negative feedback, preferences.
   - Tara's own configurable model. Do **not** claim to copy any other network's weights.
   - All parameters live in one central configuration.

## Separate configurations per surface
| Surface | What it emphasizes |
|---|---|
| Home | friends, follows, pages, relevant groups, personalized recommendations, freshness, meaningful conversations |
| Reels | interest, watch time, completion, rewatch, shares, saves, originality, video quality, negative feedback |
| Long video | topic, expected watch, completion, quality, creator relevance, history |
| Groups | shared interests, membership, activity, discussions, quality |
| Marketplace | search relevance, category, preferences, price fit, location, seller trust, quality |
| Discovery | new creators, people, pages, communities, trending topics, public content |

## Feed modes
For You (personalized), Following, Friends, Favorites, Most Recent (chronological). The user can switch modes, and the chosen mode is remembered.

## Discovery
- Recommends from accounts the user does not follow.
- Factors: interest and topic similarity, quality, author quality, freshness, diversity, exploration, feedback.
- Recommendations are labelled.
- The ratio is configurable and A/B-testable. Starting experiment: about 60% followed and friends, 30% recommended.

## My Algorithm (Settings > Content Preferences > My Algorithm)
- **Controls:**
  - topics liked / disliked / more of / less of;
  - favourite creators and pages;
  - preferred formats;
  - recommendation frequency;
  - discovery preferences;
  - content languages.
- Simple add/remove topic management.
- **Natural-language preferences (Arabic/English):**
  - An LLM is used only when configured. It converts text into structured, validated preference updates.
  - The LLM never touches queries or security.
  - The user can review and undo the changes.

## Post menu feedback
Interested, Not Interested, Show more like this, Show less like this, Hide, Mute author, Unfollow, Block, Report, Why am I seeing this?
- Every action is stored as an event.
- Positive feedback boosts ranking, negative feedback reduces it.
- An impression is not interest; a skip is not strong negative feedback.

## Event tracking
- **Events:** feed_impression, post_open, post_like, post_comment, post_share, post_save, post_hide, post_report, video_start, video_progress, video_complete, video_rewatch, video_skip, reel_view, profile_visit, follow, unfollow, interested, not_interested.
- **Fields:** user, content id and type, event type, timestamp, session, surface, watch duration, feed position.
- **Rules:**
  - minimal personal data;
  - deduplication;
  - no fake watch time;
  - privacy-aware retention.

## Interest profile
- **Fields:** topics, interests, formats, creators, categories, explicit preferences, negative preferences, recent interests, long-term interests.
- Explicit preferences (chosen by the user) are kept separate from inferred ones (estimated from behaviour). Explicit preferences weigh strongly.
- The user can inspect and edit the profile.

## Cold start
- Optional interest picker during onboarding.
- Initial sources: selected topics, language, trending, quality content, communities.
- No unnecessary personal data.
- Personalization grows gradually as behaviour accumulates.

## Quality and integrity
- **Demote:** spam, duplicates, misleading content, engagement bait, repeated low-quality posts, manipulated interactions, reported content pending review.
- **Promote:** original, useful, meaningful, high-quality, authentic content.
- New or small creators get fair reach; quality is separate from popularity.
- Reports go to moderation and are not proof of a violation.
- **Diversity:**
  - author, topic and format diversity;
  - freshness, exploration and repetition limits.
- **User control:** recommendation intensity can be reduced; chronological access is always available.
- Do not optimize for screen time alone. Measure satisfaction and negative feedback.

## Ads
Paid ranking stays separate from organic ranking and integrates with Tara Ads Manager.
- **Covered:** eligibility, targeting, budget, bid/auction, relevance, frequency caps, ad quality, policy compliance, a clear Sponsored label.
- No payment influence on organic ranking.
- No serving without approval and payment checks.

## Stack
- Inspect what exists first.
- **Django-side candidates:** DRF, PostgreSQL, Redis, Celery, Channels where needed; scikit-learn first, PyTorch only if justified.
- No unjustified new technology.

## Modules
CandidateRetrievalService, EligibilityFilterService, UserInterestService, SignalCollectionService, PredictionService, FeedRankingService, ReelsRankingService, DiscoveryService, FeedbackService, RecommendationAnalyticsService.
- Proper APIs, caching and pagination.
- No N+1 queries; scalable.

## Internal Intelligence dashboard
- **Metrics:**
  - impressions, engagement rate, average watch time, completion rate;
  - saves, shares, hide rate, negative feedback;
  - recommendation quality, feed diversity, new-creator reach, discovery performance.
- **Tools:** ranking parameter configuration with a change log, and A/B testing.
- Private behaviour is never exposed to unauthorized administrators.

## Tests
- **Areas:** candidate retrieval, eligibility, ranking, personalization, chronological feed, preferences, negative feedback, reels, cold start, diversity, privacy filtering, blocked accounts, sponsored labelling, performance.
- Synthetic datasets, kept apart from real production analytics.
- A user never receives content they are not authorized to see.

## Phases
1. Audit.
2. Event tracking.
3. Candidates and eligibility.
4. Rule-based ranking.
5. Separate Feed and Reels configurations.
6. Interest profiles.
7. Interested / Not interested.
8. My Algorithm.
9. Discovery.
10. LLM preference interpretation.
11. ML when there is enough data.
12. Analytics and A/B testing.
13. Performance and security.

Run tests and document the results after every phase. No fake AI UI, and no claims of ML where only rules exist. Weights are configurable, not hardcoded. Existing functionality is preserved.

## Visual
- The brief names a "Tara Olive" identity: primary #64765A, background #F8F9F5.
- **Open question:** the shipped brand is purple, and changing it is the owner's decision.
