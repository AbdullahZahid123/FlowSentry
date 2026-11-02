# Release coverage

This is an implementation and verification record, not a claim that all future PRD phases are complete.

## Implemented monitoring MVP

- First-owner setup, login/logout, hashed sessions and revocation, reset tokens with SMTP, workspace creation/switching, roles and invitations.
- n8n connection creation, encrypted credentials, connectivity checks, sync cursors, source health, ingress token rotation, pause/resume, and capability display.
- Durable webhook acceptance, two n8n Error Workflow shapes, redaction, idempotent execution normalization, polling reconciliation, and leased outbox processing.
- Workflow health/configuration, monitoring pause, environment/criticality/expected interval, and real grouped topology for API connections.
- Execution search/filter/cursor lists, detail, source events, safe source links, and CSV export.
- Incident fingerprint grouping, severity, acknowledge/investigate/resolve/reopen, assignment, comments, timeline, and linked executions.
- Email/Telegram/webhook channels, alert rules, cooldowns, bounded delivery retries, visible attempt history, and test delivery.
- Overview and analytics, workspace timezone, audit history, team/account/session settings.
- Responsive UI, light/dark themes, shadcn controls, automatic looping sample with reduced-motion support, and explicitly labeled sample data.
- Compose services, persistent PostgreSQL, versioned migrations, readiness/heartbeat checks, retention, configuration generator, and backup/restore tooling.

## Deliberate differences from the proposed documents

PostgreSQL outbox rows and row leases replace Redis queues. This keeps accepted events and processing state in one transaction and removes a second persistence dependency. Native retry/replay and AI diagnosis remain disabled as permitted by the implementation plan's MVP boundary. High-level workflow grouping uses deterministic topology, not AI. The supplied checklist's user interviews, external repository protections, production hosting, and third-party account provisioning cannot be completed by local source changes.

## Verification record — 2026-11-03

- 33 backend tests passed, including the opt-in public API contract test against local n8n 2.45.7. Regression tests use isolated real PostgreSQL databases. Coverage includes workspace isolation, auth/CSRF, deduplication, incident/notification behavior, cursor ties, pagination, destination safety, topology, monitoring pause, timezone validation, and retention.
- Final frontend TypeScript checks and production Docker frontend/backend builds passed. The production npm audit reported zero vulnerabilities.
- Fresh Compose install and one-shot migration succeeded. API, worker, scheduler, PostgreSQL, and web health checks passed.
- Browser checks covered the nine principal application routes at 320 and 768 pixels and desktop light-theme checks at 1440 pixels. Public and detail screens were checked separately at phone widths, including 390 pixels. Incident detail overflow was fixed and rechecked at 320 pixels. Theme persistence, mobile navigation, keyboard Escape/focus return, sample filtering, and workflow node inspection were exercised.
- Actual local n8n success/failure executions, workflow discovery, cursor pagination, topology, and a published Error Workflow were exercised. Repeated failures grouped into one incident; acknowledge, investigate, comment, and resolve actions were verified. Notification email was captured by local Mailpit.
- A webhook accepted while workers were stopped survived an API restart. Redelivery returned the original event and subsequent processing produced one execution.
- A custom-format database backup was restored into a separate empty PostgreSQL project and its migration revision and retained records were checked.

## Outstanding release gates

Local n8n and SMTP capture tests do not certify the operator's production instance or intended production network. A real Telegram message has not been sent: no bot token/chat destination was supplied. Production SMTP password reset/delivery needs the operator's configured mail service. Recovery steps are explicitly unavailable. Independent security/load review, live TLS deployment, operational alerting, off-host backup scheduling, and target-user validation remain deployment/release work.

## Future phases

Maintenance window management, dead-letter replay UI, SLA/escalation policy, automatic recovery, advanced custom rules, advisory AI, multiple providers, SSO, billing, and public status pages are not represented as finished features. Some supporting schema exists for later phases. Read the original implementation plan's MVP/V1 boundaries before extending them.
