# Owner decisions (2026-11-05)

On 2026-11-05 the owner answered "اعمل المناسب" ("do what is appropriate"). Every open decision in `README.ar.md` §4 therefore takes the recommended option below, and each one stays changeable through configuration later.

| # | Decision | Taken |
|---|---|---|
| 1 | Colours | Keep the shipped purple brand. No theme change now; the owner said the look is not a priority. |
| 2 | LLM provider | No LLM in production: the rule-based parser only. Local Ollama (`qwen3:8b`) for development experiments. |
| 3 | Retention | Raw signals: 30 days. Per-user-item engagement aggregates: 30 days. Aggregated metrics: 400 days. |
| 4 | Discovery ratio | A/B test with three arms (0% / 15% / 30%). Results are not conclusive below about 1,600 users per arm. |
| 5 | Home default mode | "Most Recent" until the phase-4 experiments show "For You" is better. |
| 6 | Save as an event | Allowed: ids only, consumed by feed only, behind `POST_EMIT_SAVE_EVENTS`. |
| 7 | Search history as interest | Not used without explicit opt-in. |
| 8 | Personalization consent | A "turn off personalization" switch in My Algorithm now. Formal consent depends on the target market. |
| 9 | Minors | (a) As viewers: no people suggestions and limited discovery. (b) As authors: not shown in adults' discovery or people suggestions, but still visible to their friends and followers. |
| 10 | Dashboard access | The `analyst` role reads; `admin` edits. |
| 11 | Topic picker at sign-up | Optional, with "Skip". |
| 12 | Sensitive topics | Inferred only after explicit opt-in, which is off by default. Never used for ads, never shown to staff. |
| 13 | Third-party LLM | Not allowed: `INTEL_LLM_THIRD_PARTY_APPROVED=false`. |
| 14 | Ad density | One slot (`ads.slots = [4]`), as today. |
| 15 | Ads targeting, auction and ad quality | Out of Tara Intelligence scope. The payment (`billing_status`) check is still done in phase 4. |
| 16 | Group posts in "Most Recent" | Not included. They show in "For You" and the Groups tab. |
| 17 | Explaining a user's ranking to support | The user's consent (24 h) by default; a second staff approver for investigations. The reason is always logged. |
| 18 | `reinstate` moderation action | Add it (WP 3.3b). |

## Later decisions (2026-11-05, after briefs 2 and 3)

| # | Decision | Taken |
|---|---|---|
| 19 | Trending architecture | **Trending is an independent engine, not a tab of top-engagement posts.** It computes spread *velocity* locally (city, governorate, country, macro-region) and globally, separates "rising" from "popular", and **publishes its results to the recommendation engine as a candidate source and a ranking feature**. A rising post can then reach users who do not follow its author, subject to eligibility, privacy and manipulation guards. The Trending/Explore UI is one consumer of the engine, not the engine itself. |
| 20 | Weights and parameters | The owner delegates every weight, threshold, ratio and window to the engineering team ("take all needed weights"). Every value lives in the versioned central config with a change log, starts from a documented, justified default, and can be tuned by A/B test. None are hard-coded. |
| 21 | Engineering suggestions | The owner asked the team to add any improvements it judges valuable beyond the briefs. Each one is evaluated (value, cost, risk) before it is built, and recorded in the roadmap. |
| 22 | Definition of done for this round | Finish everything planned, run a thorough review of **old and new** code, fix what it finds, push, and confirm the production site works. The round then stops. |
| 23 | Recommended share before an experiment is powered | Under decision 20 (weights delegated), the team uses the A/B arms from decision 4. The 0% arm stays the control until each arm has the users it needs. Below that, the default is a **small, capped 10% share** of recommended items, applied only when the viewer's connection inventory is thin (scenario E). An empty or stale home is worse than a small recommended share. |
| 24 | Visit timestamps when personalization is off | Not stored. Nothing is collected under `personalization_off`, beyond what security and abuse protection already keep. |
| 25 | Default Home mode | **"For You" once phase 4b (rotation, exposure ledger, new-since) ships and passes its acceptance tests.** Until then, "Most Recent". The owner's main complaint is a static, repetitive home, so decision 5 is updated. Users can switch and the choice is remembered. |
| 37 | Author age class | Approved, minimal: store one class per author (adult / minor / unknown) taken from the author's own token claims, in feed and graph. Never store the date of birth. |
| — | Read-only measurements on production | Not needed now. Production has just launched and holds almost no data. The dev and seed measurements stand in, re-run once real traffic exists. |
| 26–36, 38–42 | Brief-3 decisions (location, trends, minors, consent retention, end of round) | Every one takes the default recommended in `README.ar.md` §7 and `08-brief-3-addendum.md`, under decision 20 (choices delegated to the team). In short: <br>• the GPS button is opt-in only, with a `Permissions-Policy` change; <br>• the Cloudflare country is a suggestion only; <br>• location is used for recommendations only after the user picks a place; <br>• k-anonymity thresholds apply, and below country level only hashtags and topics are counted; <br>• minors and unknown-age accounts count at country level and above; <br>• sensitive topics are never published as trends; <br>• only an admin (not a moderator) can suppress a trend; <br>• consent records are kept 2 years after deletion under a hashed id, pending counsel; <br>• the round ends without R8 (ML and LLM) and without experiment conclusions. |
