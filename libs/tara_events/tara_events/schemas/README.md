# Event JSON Schemas

One JSON Schema per `event_type` + `event_version`, e.g.
`account.registered.v1.json`. CI validates sample payloads against these, and a
breaking payload change requires a new `event_version` file (additive-only
within a version). See docs/architecture/phase-0/04-event-contracts.md §6.

Schemas are added alongside the events that introduce them, phase by phase.
