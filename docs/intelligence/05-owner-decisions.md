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
