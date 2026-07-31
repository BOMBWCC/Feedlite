# FeedLite Security Hardening Design

## Goal

Remediate the actionable findings preserved by the partial `codex-security`
scan while retaining FeedLite's single-user deployment model, existing API
shapes, and current browser workflows.

## Scope

The work covers five independently testable stages, ordered by risk:

1. Authentication and secret validation.
2. Browser rendering and URL safety.
3. RSS outbound request validation and ingestion bounds.
4. Async-service availability and resource limits.
5. AI pipeline integrity, login throttling, and deployment guidance.

The local `.env` will be rotated as part of stage 1. Existing administrator
JWTs and RAG client credentials will stop working. Secret values must never be
printed in tests, command output, logs, commits, or the final handoff.

## Constraints

- Preserve the current FastAPI routes and successful response shapes.
- Preserve the single-administrator and separately keyed RAG authorization
  model.
- Preserve current uncommitted UI work in `static/app.js`,
  `static/index.html`, and `static/style.css`.
- Do not require an external cache, database, reverse proxy, or hosted service
  for application-level protections.
- Add no dependency unless the standard library and existing dependencies
  cannot provide a safe, maintainable implementation.
- Use regression tests for each production behavior change.

## Stage 1: Authentication and Secrets

Application startup will validate security-sensitive configuration before the
API begins serving requests. `ADMIN_PASSWORD` and `JWT_SECRET` must be set,
must not equal repository-known defaults or placeholders, and must meet minimum
length requirements. `RAG_API_KEY` remains optional so the RAG API can stay
disabled, but if configured it must not equal a public placeholder and must
meet the same secret-strength floor. `ADMIN_USERNAME` may remain `admin`; the
password, not the public identifier, is the authentication secret.

Login credential comparison and RAG key comparison will use constant-time
comparison. JWT verification will continue to require HS256 and expiration.
Production startup will fail closed instead of silently accepting fallback
credentials.

The local `.env` will receive newly generated administrator, JWT, and RAG
secrets. Its filesystem mode will be restricted to owner read/write. The
administrator username remains unchanged. The generated administrator password
will remain only in `.env`; the handoff will tell the operator where to read it
without reproducing it in conversation output.

## Stage 2: Browser Rendering and URL Safety

Remote and stored values will be treated as data at the DOM boundary. Rendering
will use DOM node creation and `textContent` for RSS preview items and
subscription rows. Where the existing article template remains, every dynamic
attribute will be escaped and article links will be normalized through a
single helper that permits only absolute `http:` and `https:` URLs. Unsafe or
malformed links will render as inert controls rather than clickable anchors.

Existing theme, modal, Popover API, and toast behavior will be preserved.
Regression tests will exercise markup in titles, attribute-breaking links, and
non-web schemes such as `javascript:`.

## Stage 3: RSS Outbound Safety and Ingestion Bounds

A focused RSS HTTP helper will own URL validation, redirects, download limits,
and timeouts. Before each connection it will:

- require `http` or `https`;
- reject embedded credentials and missing hostnames;
- resolve the hostname and reject loopback, private, link-local, multicast,
  reserved, unspecified, and site-local addresses;
- validate every redirect target before following it; and
- cap redirect depth.

The helper will stream responses and stop once the configured byte ceiling is
exceeded. Preview and recurring fetches will share this path. Feed parsing will
also cap accepted entry count, title length, description length, body length,
and link length before persistence, indexing, chunking, or AI processing.

DNS rebinding cannot be completely eliminated with high-level `requests`
alone because validation and connection are separate operations. The design
therefore validates resolved addresses immediately before each request and
disables automatic redirects. Deployment-level egress filtering remains the
recommended defense-in-depth control.

## Stage 4: Availability and Resource Control

Blocking RSS and AI HTTP work will execute outside the asyncio event-loop
thread. Each operation will have a total coroutine deadline in addition to
connect/read timeouts. Responses will be streamed with a strict byte limit
before JSON or feed parsing.

Search normalization will replace the quadratic tag-stripping expression with
a linear parser or linear scan. RAG search queries will have a maximum length,
and context requests will cap and deduplicate chunk IDs before database work.
Chunk generation and pending scoring/translation selection will have explicit
per-article, per-run, and per-batch bounds.

Translation batch splitting will carry a shared request budget. Exhausting the
budget will fail the remaining batch without further fan-out. Retry behavior
will distinguish retryable transport failures from malformed or rejected
content and will not retry indefinitely.

## Stage 5: AI Integrity, Login Throttling, and Deployment

AI prompts will clearly delimit untrusted feed content, state that embedded
instructions are data, and use server-generated opaque batch positions instead
of trusting IDs or framing from article text. Provider results will be accepted
only for identifiers present exactly once in the submitted batch. Duplicate,
unknown, or malformed entries will be ignored without updating other records.

Profile generation will keep remote article text in a delimited data section
and prevent it from being promoted verbatim into a higher-priority scoring
instruction. The resulting profile remains model-derived data and will be
length- and structure-validated before persistence.

The login endpoint will receive an in-process, bounded throttling mechanism
suitable for the documented single-process deployment. It will limit repeated
failures by client address without introducing an external service. The
documentation will state that multi-process or horizontally scaled deployments
need proxy-level or shared-store rate limiting.

Deployment documentation will require TLS termination for remote access,
recommend binding the application to loopback behind a reverse proxy, document
secret rotation and file permissions, and describe outbound egress filtering.

## Error Handling

- Invalid startup secrets produce a clear configuration error naming only the
  variable, never its value.
- Blocked RSS destinations return a generic validation failure; internal IPs
  and DNS details are not reflected to clients.
- Oversized RSS or AI responses fail with a bounded application error and do
  not persist partial articles or provider output.
- A timeout or provider failure affects the current operation or batch and does
  not block unrelated API requests.
- Invalid browser links remain visible as text where useful but are inert.

## Verification

Every stage follows red-green-refactor testing. Tests will cover:

- startup rejection of missing, default, placeholder, and short secrets;
- acceptance of strong settings and optional disabled RAG configuration;
- XSS payloads in previews, subscription metadata, and article links;
- blocked private/loopback destinations and blocked redirect targets;
- bounded response, entry, field, query, chunk-ID, chunk-count, and retry work;
- event-loop responsiveness while RSS and AI calls are delayed;
- strict AI result-to-batch association; and
- login throttling and recovery after the configured window.

After each stage, its focused tests and the full `unittest` suite will run.
Frontend behavior will also receive a static or browser-level regression check
appropriate to the existing no-build JavaScript setup.

## Rollout and Recovery

Stage 1 intentionally invalidates current tokens and integrations. The operator
must read the new administrator password and RAG key directly from the local
`.env`, log in again, and update RAG clients. If an immediate production rollout
is not possible, code changes can be deployed only after the production secrets
are replaced with values that pass startup validation.

The stages remain separate enough to review and revert individually. Existing
database content and schemas are not destructively migrated by this work.
