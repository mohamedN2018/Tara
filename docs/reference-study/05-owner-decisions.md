# Reference study: owner decisions (2026-11-05)

On 2026-11-05 the owner gave this standing direction for the reference-study round:

> «شوف انت المناسب واعمله، وأي قرارات خدها انت. أي حاجة محتاجة عوامل خارجية ابنيها وخليها مخفية، وحاول تعمل كله داخلي، وأي دفع أجّله دلوقتي. احنا عاوزين نبني كل حاجة الأول ونتيست كل حاجة ويبقى نظام قوي جدًا، وبعد كده نشوف أي حاجة خارجية.»

In English: "Decide what's appropriate and do it; take any decisions yourself. Anything that needs an outside service, build it and keep it hidden. Try to do everything in-house, and postpone anything to do with payments for now. We want to build and test everything first so the system is very solid; outside services come later."

It applies to the D1 to D14 decisions in [README.ar.md](README.ar.md), and to every decision of the same kind that comes up later.

## Rules for external dependencies

1. **Build it, but keep it dark.** A feature that needs an outside party (payment provider, email or SMS provider, GIF provider, cloud LLM, push relay, CDN, map tiles, live-streaming hardware) is still built end to end: models, APIs, UI and tests. It sits behind:
   - a feature flag that is **off by default**;
   - a provider interface;
   - an in-house or fake provider used in development and tests.

   With the flag off, the feature does not appear in the product UI. Admins see it only as "disabled".
2. **In-house first.** Wherever an in-house implementation is reasonable, it is the default: local stickers, haversine distance, a prepaid credit ledger, a rules-based assistant over the help articles.
3. **No real money.** Nothing charges, settles or pays out until the owner enables a payment provider. Ad spend runs against an internal prepaid credit balance that only admins can top up, through an audited admin action, never through a card. The ads billing check (`billing_status`) and the serving guard stay in force.
4. **Test everything.** Every dark feature has tests that run through the fake provider, so that when it is switched on, only the provider adapter is new.

## Decisions

| # | Topic | Decision |
|---|---|---|
| D1 | Mobile bottom bar | Keep the bottom bar on phones, and match the reference top bar on desktop. Revisit after usability data. |
| D2 | Assistant | An **in-house** rules and retrieval assistant over Tara's own help-centre articles: no cloud LLM. An optional local Ollama adapter sits behind a flag that is off. It reads help articles only, never user data. |
| D3 | Tara Business | It lives inside the `profile` service (business portfolio, members, assets, per-asset roles). It is split out only if load or ownership demands it. |
| D4 | Marketplace location search | Haversine distance on indexed latitude and longitude buckets, with no PostGIS. Users choose a city or region, and coordinates are coarse. This is consistent with the location privacy model in `docs/intelligence/08-brief-3-addendum.md`. |
| D5 | GIFs | In-house sticker and GIF packs, uploaded by admins, stored in MinIO. The external provider adapter is built behind a flag that is off. |
| D6 | Verification | Free, request-based verification with criteria and admin review. There is no paid subscription. |
| D7 | Digits | Western digits (0–9) in the UI by default, in both languages. An opt-in display setting enables Arabic-Indic digits. Money uses the locale formatter. |
| D8 | Live video | The full flow is built (go live, viewers, comments, reactions, end, replay) on the existing LiveKit integration, behind a flag that is **off**. Ingress and egress (RTMP, recording) wait for a server capacity check. |
| D9 | Ad payments | **Deferred.** An internal prepaid credit ledger is used, topped up by admins with an audit log. The provider interface (Stripe, Paymob, Fawry) is built behind a flag that is off, with no real charges. |
| D10 | Comment dislike, state-media labels, family centre | Deferred (P3). Not built in this round. |
| D11 | Email notifications | The email channel and per-kind preferences are built with a console or Mailpit transport in development. Production stays dark (no SMTP) until the owner adds a provider. In-app and push are the active channels. |
| D12 | Profile lock, "who can post on your profile" | Built: both are privacy settings enforced by the server. |
| D13 | Small cells in reports | Cells under 50 people or 100 impressions are hidden. When exactly one cell would be hidden, the next smallest is hidden too. |
| D14 | Boost eligibility | A post is eligible when it is public, published, not anonymous, and not a share of someone else's post. Otherwise the button shows as disabled with the reason. Boost spends prepaid credit only (see D9). |
