# FeedLite Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the actionable authentication, browser injection, SSRF, prompt-integrity, and resource-exhaustion paths identified by the partial security scan without changing FeedLite's successful API contracts.

**Architecture:** Add small security boundaries for configuration, outbound HTTP, DOM rendering, and bounded AI work, then route existing call sites through them. Each task starts with a focused failing regression test, makes the narrowest production change, runs the focused and full suites, and commits only its own files.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy asyncio, requests, feedparser, standard-library `asyncio`, `ipaddress`, `socket`, `html.parser`, browser JavaScript, `unittest`.

## Global Constraints

- Preserve current FastAPI routes and successful response shapes.
- Preserve the single-administrator and separately keyed RAG authorization model.
- Preserve current uncommitted UI changes in `static/app.js`, `static/index.html`, and `static/style.css`.
- Do not print, log, commit, or include generated secret values in handoff text.
- Do not add an external cache, database, proxy, or hosted service.
- Keep `.env` ignored and set its mode to `0600` after rotation.
- Run `python -m unittest discover -s tests -p 'test_*.py' -v` after every task.

---

### Task 1: Fail-Closed Authentication Configuration and Local Secret Rotation

**Files:**
- Create: `app/security_config.py`
- Create: `tests/test_auth_security.py`
- Modify: `app/main.py:9-30`
- Modify: `app/auth_deps.py:1-53`
- Modify: `app/routers/auth.py:1-45`
- Modify: `.env.example:5-13,41-43`
- Modify locally, never stage: `.env`

**Interfaces:**
- Produces: `validate_security_config(environ: Mapping[str, str] | None = None) -> None`
- Produces: `configured_secret(name: str) -> str`
- Produces: `credentials_match(provided: str, expected: str) -> bool`
- Consumes: FastAPI lifespan startup and existing auth dependencies.

- [ ] **Step 1: Write failing configuration tests**

```python
class SecurityConfigTestCase(unittest.TestCase):
    def test_rejects_repository_known_password_and_jwt_secret(self):
        env = {
            "ADMIN_PASSWORD": "change-this-password",
            "JWT_SECRET": "replace-with-a-unique-random-secret",
        }
        with self.assertRaisesRegex(ValueError, "ADMIN_PASSWORD"):
            validate_security_config(env)

    def test_accepts_strong_secrets_with_rag_disabled(self):
        validate_security_config({
            "ADMIN_PASSWORD": "correct-horse-battery-staple-2026",
            "JWT_SECRET": "a" * 64,
            "RAG_API_KEY": "",
        })

    def test_constant_time_helper_matches_exact_values(self):
        self.assertTrue(credentials_match("secret-value", "secret-value"))
        self.assertFalse(credentials_match("secret-value", "different-value"))
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_auth_security -v`

Expected: import failure because `app.security_config` does not exist.

- [ ] **Step 3: Implement configuration validation and constant-time comparison**

```python
PUBLIC_VALUES = {
    "ADMIN_PASSWORD": {"admin", "change-this-password"},
    "JWT_SECRET": {
        "replace-with-a-unique-random-secret",
        "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7",
    },
    "RAG_API_KEY": {"replace-with-private-rag-api-key"},
}

MIN_LENGTHS = {"ADMIN_PASSWORD": 16, "JWT_SECRET": 32, "RAG_API_KEY": 32}

def validate_security_config(environ=None):
    values = os.environ if environ is None else environ
    for name in ("ADMIN_PASSWORD", "JWT_SECRET"):
        _validate_secret(name, values.get(name, ""), required=True)
    _validate_secret("RAG_API_KEY", values.get("RAG_API_KEY", ""), required=False)

def credentials_match(provided, expected):
    return hmac.compare_digest(str(provided), str(expected))
```

Call `validate_security_config()` at the start of `lifespan`, remove JWT and administrator credential fallbacks, and read secrets through `configured_secret`. Use `credentials_match` for password and RAG key checks.

- [ ] **Step 4: Run focused and full tests and verify GREEN**

Run: `python -m unittest tests.test_auth_security -v`

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`

Expected: all tests pass; exception messages contain variable names but no values.

- [ ] **Step 5: Rotate local secrets without exposing them**

Generate a 24-byte URL-safe administrator password and 32-byte URL-safe JWT/RAG secrets using `openssl rand`. Replace only the three values in `.env`, preserve all unrelated settings, set `.env` mode to `0600`, and verify classifications without printing values.

Run: `git check-ignore -q .env`

Expected: exit 0.

- [ ] **Step 6: Commit Task 1**

```bash
git add app/security_config.py app/main.py app/auth_deps.py app/routers/auth.py .env.example tests/test_auth_security.py
git commit -m "fix: fail closed on insecure auth secrets"
```

---

### Task 2: Eliminate Browser Injection Sinks

**Files:**
- Create: `tests/test_static_security.py`
- Modify carefully: `static/app.js:222-230,373-400,625-661`
- Modify carefully: `static/index.html` only if a CSP/meta change is testable without breaking current CDN loading.

**Interfaces:**
- Produces: `safeExternalUrl(value: unknown) -> string | null` inside `static/app.js`
- Produces: `appendPreviewItems(container: Element, items: Array) -> void`
- Produces: `appendSubscriptionRows(container: Element, feeds: Array) -> void`
- Consumes: existing preview, subscription, and article rendering paths.

- [ ] **Step 1: Write failing static regression tests**

```python
class StaticSecurityTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("static/app.js").read_text(encoding="utf-8")

    def test_preview_does_not_interpolate_remote_title_into_inner_html(self):
        block = self.source[self.source.index("const renderPreview"):self.source.index("document.addEventListener('click'", self.source.index("const renderPreview"))]
        self.assertIn("textContent", block)
        self.assertNotIn("${item.title}", block)

    def test_article_links_pass_through_http_url_allowlist(self):
        self.assertIn("safeExternalUrl(article.link)", self.source)
        self.assertNotIn('href="${article.link}"', self.source)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_static_security -v`

Expected: failures identify the existing template interpolations.

- [ ] **Step 3: Replace remote-data templates with safe DOM operations**

```javascript
const safeExternalUrl = (value) => {
    try {
        const parsed = new URL(String(value));
        return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
    } catch {
        return null;
    }
};

const appendTextElement = (parent, tagName, className, value) => {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = value == null ? '' : String(value);
    parent.appendChild(element);
    return element;
};
```

Use node creation for preview and subscription rows. In article rendering, compute `const safeLink = safeExternalUrl(article.link)` and emit an anchor only when non-null; otherwise emit an inert button/span. Escape all remaining dynamic attribute values, including category labels.

- [ ] **Step 4: Run focused tests and browser smoke verification**

Run: `python -m unittest tests.test_static_security -v`

Then load the app locally and verify subscription modal, preview, article menu, theme, Popover, and Toast behavior with the payload `<img src=x onerror="window.__feedliteXss=1">` and the URL `https://example.com/" onmouseover="window.__feedliteXss=1`. Confirm no script runs and unsafe links are inert.

- [ ] **Step 5: Run the full suite and preserve the dirty frontend files**

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`

Do not stage or commit `static/app.js`, `static/index.html`, or
`static/style.css`, because they contained user-authored uncommitted work before
this plan began. Keep the security changes in the working tree and report them
explicitly in the final handoff. Do not commit `tests/test_static_security.py`
separately because that would leave the committed tree failing until the user
chooses how to integrate the frontend work.

---

### Task 3: Add SSRF-Safe, Bounded RSS Fetching

**Files:**
- Create: `app/services/safe_http.py`
- Create: `tests/test_safe_http.py`
- Modify: `app/services/rss_fetcher.py:27-156,220-239`
- Modify: `app/routers/sources.py:89-123`
- Modify: `app/models.py:29-35`
- Modify: `app/database.py` article-identity migration section
- Modify: `data/schemas.sql:30-53`
- Expand: `tests/test_rss_fetcher.py`

**Interfaces:**
- Produces: `validate_public_http_url(url: str, resolver=socket.getaddrinfo) -> str`
- Produces: `fetch_public_bytes(url: str, *, max_bytes: int, timeout: tuple[float, float], max_redirects: int = 3, session: requests.Session | None = None) -> bytes`
- Produces: `async_fetch_public_bytes(url: str, *, max_bytes: int, timeout: tuple[float, float], total_timeout: float, max_redirects: int = 3, session: requests.Session | None = None) -> bytes`
- Produces: `migrate_article_identity(db: aiosqlite.Connection) -> None`
- Consumes: preview and recurring RSS fetch paths.

- [ ] **Step 1: Write failing URL and redirect tests**

```python
def test_rejects_loopback_resolution(self):
    resolver = lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
    with self.assertRaises(PublicUrlError):
        validate_public_http_url("http://example.test/feed", resolver=resolver)

def test_rejects_private_redirect_target(self):
    session = RedirectingFakeSession("http://169.254.169.254/latest/meta-data")
    with self.assertRaises(PublicUrlError):
        fetch_public_bytes("https://public.example/feed", max_bytes=1024, timeout=(3, 10), session=session)

def test_stops_after_response_byte_limit(self):
    session = StreamingFakeSession([b"a" * 700, b"b" * 700])
    with self.assertRaises(ResponseTooLargeError):
        fetch_public_bytes("https://public.example/feed", max_bytes=1024, timeout=(3, 10), session=session)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_safe_http -v`

Expected: import failure because the safe HTTP module does not exist.

- [ ] **Step 3: Implement public-address validation and manual redirects**

```python
def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return not any((ip.is_private, ip.is_loopback, ip.is_link_local,
                    ip.is_multicast, ip.is_reserved, ip.is_unspecified))

def validate_public_http_url(url, resolver=socket.getaddrinfo):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise PublicUrlError("RSS URL is not allowed")
    addresses = {item[4][0] for item in resolver(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    if not addresses or not all(_is_public_address(item) for item in addresses):
        raise PublicUrlError("RSS URL is not allowed")
    return url
```

Fetch with `allow_redirects=False`, validate every `Location` joined with the current URL, stream via `iter_content`, and raise before accumulated bytes exceed the limit. The async wrapper must use `asyncio.to_thread` plus `asyncio.wait_for`.

- [ ] **Step 4: Route preview and recurring fetch through the helper**

Set explicit constants: 5 MiB RSS response, 3 redirects, 3-second connect timeout, 15-second read timeout, and 25-second total coroutine deadline. Make preview async fetch bytes and parse only returned bounded bytes. Make `fetch_single_feed` await an async `fetch_and_clean` path without running `requests` on the event loop.

- [ ] **Step 5: Add and test ingestion bounds**

Use constants: 200 entries per response, 500 title characters, 2,048 link characters, 1,000 description characters, 100,000 body characters, and 200 feed-title characters. Slice before `clean_html`, indexing, persistence, chunking, or AI work. Add tests showing the 201st entry is ignored and every field respects its bound.

- [ ] **Step 6: Scope article identity to its source**

Add a test inserting the same canonical link under two different feed IDs and
assert that both rows persist, while a duplicate within one feed remains
ignored. Replace the global `link UNIQUE` rule with
`UniqueConstraint("feed_id", "link", name="uq_articles_feed_link")`. Add an
idempotent SQLite migration that rebuilds the table only when the legacy global
unique index is present, copies rows without changing IDs, recreates indexes and
FTS triggers, and rolls back the transaction on failure. Update the insert
conflict target to `("feed_id", "link")`.

- [ ] **Step 7: Run focused/full suites and commit Task 3**

Run: `python -m unittest tests.test_safe_http tests.test_rss_fetcher -v`

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`

```bash
git add app/services/safe_http.py app/services/rss_fetcher.py app/routers/sources.py app/models.py app/database.py data/schemas.sql tests/test_safe_http.py tests/test_rss_fetcher.py
git commit -m "fix: constrain RSS fetch destinations and payloads"
```

---

### Task 4: Bound Search, RAG Context, and Chunk Work

**Files:**
- Modify: `app/services/search_index.py:6-63`
- Modify: `app/routers/rag.py:41-52,142-175`
- Modify: `app/services/chunk_indexer.py:1-180`
- Modify: `app/database.py:210-351`
- Create: `tests/test_database_init.py`
- Expand: `tests/test_search_optimization.py`
- Expand: `tests/test_rag_api.py`
- Expand: `tests/test_chunk_indexer.py`

**Interfaces:**
- Produces: linear `strip_markup(text: str) -> str`
- Preserves: `normalize_search_source`, `build_search_query`, and `build_search_text` signatures.
- Adds route constants: `MAX_RAG_QUERY_LENGTH = 512`, `MAX_CONTEXT_CHUNK_IDS = 50`.
- Adds chunk constants: `MAX_CHUNKS_PER_ARTICLE = 200`, `MAX_CHUNK_SOURCE_CHARS = 100_000`.
- Produces: `_ensure_search_indexes(db: aiosqlite.Connection, batch_size: int = 500) -> None` that performs no rebuild when schema and triggers are current.

- [ ] **Step 1: Write failing boundary and complexity regression tests**

```python
def test_normalization_handles_unclosed_tag_markers_linearly(self):
    hostile = "<" * 32000
    started = time.monotonic()
    normalize_search_source(hostile)
    self.assertLess(time.monotonic() - started, 0.5)

async def test_rag_context_rejects_more_than_fifty_chunk_ids(self):
    with self.assertRaises(HTTPException) as raised:
        await get_rag_context(list(range(51)), window=1, include_filtered=False, db=self.session)
    self.assertEqual(raised.exception.status_code, 422)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_search_optimization tests.test_rag_api tests.test_chunk_indexer -v`

Expected: RAG accepts 51 IDs; hostile normalization breaches the local threshold or still uses `_TAG_RE`.

- [ ] **Step 3: Replace regex stripping with a linear HTML parser**

```python
class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)

def strip_markup(text):
    parser = _TextExtractor()
    parser.feed(text or "")
    parser.close()
    return " ".join(parser.parts)
```

Use the same helper from RSS cleaning so the vulnerable regex is not duplicated.

- [ ] **Step 4: Enforce RAG and chunk limits before expensive work**

Add `max_length=512` to `q`, reject more than 50 supplied IDs, deduplicate while preserving order, and only then issue queries. Slice article source text to 100,000 characters and stop chunk generation at 200 chunks.

- [ ] **Step 5: Make startup index maintenance incremental**

Add a database test that creates current FTS tables/triggers, inserts a sentinel
row, runs `_ensure_search_indexes`, and asserts that neither FTS table was
dropped and no full article `fetchall()` occurred. For legacy rows with empty
`search_text`, select and update in batches of 500 using `fetchmany(500)`. Only
rebuild an FTS table when its table or required triggers are missing; otherwise
leave it intact. Apply the same conditional behavior to article-chunk FTS.

- [ ] **Step 6: Run focused/full suites and commit Task 4**

Run: `python -m unittest tests.test_search_optimization tests.test_rag_api tests.test_chunk_indexer tests.test_database_init -v`

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`

```bash
git add app/services/search_index.py app/routers/rag.py app/services/chunk_indexer.py app/services/rss_fetcher.py app/database.py tests/test_search_optimization.py tests/test_rag_api.py tests/test_chunk_indexer.py tests/test_database_init.py
git commit -m "fix: bound search and chunk processing"
```

---

### Task 5: Isolate and Bound AI Provider Calls

**Files:**
- Create: `app/services/provider_http.py`
- Create: `tests/test_provider_http.py`
- Modify: `app/services/ai_scorer.py:235-355,402-484`
- Modify: `app/services/translator.py:140-275`
- Modify: `app/services/profiler.py:176-313`
- Expand: `tests/test_ai_scorer.py`
- Expand: `tests/test_profile_logic.py`

**Interfaces:**
- Produces: `post_json_bounded(url: str, *, headers: dict, payload: dict, proxies: dict | None, max_bytes: int = 2_000_000, session: requests.Session | None = None) -> BoundedJsonResponse`
- Produces: `async_post_json_bounded(url: str, *, headers: dict, payload: dict, proxies: dict | None, max_bytes: int = 2_000_000, total_timeout: float = 75.0, session: requests.Session | None = None) -> BoundedJsonResponse`
- Produces: async `_call_llm_async(messages: list[dict], config: dict) -> str` for scorer/translator.
- Produces: async `_call_profiler_async(messages: list[dict], config: dict) -> str`.

- [ ] **Step 1: Write failing byte-limit and event-loop responsiveness tests**

```python
def test_provider_response_stops_at_two_megabytes(self):
    session = StreamingFakeSession([b"x" * 1_500_000, b"y" * 1_500_000])
    with self.assertRaises(ProviderResponseTooLarge):
        post_json_bounded("https://provider.example/api", headers={}, payload={}, proxies=None, session=session)

async def test_async_provider_call_does_not_block_peer_coroutine(self):
    with patch("app.services.provider_http.post_json_bounded", side_effect=lambda *a, **k: (time.sleep(0.2), FakeResponse())[1]):
        provider_task = asyncio.create_task(async_post_json_bounded("https://provider.example/api", headers={}, payload={}, proxies=None))
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.05)
        await provider_task
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_provider_http -v`

Expected: import failure because `provider_http` does not exist.

- [ ] **Step 3: Implement streaming bounded provider responses**

Use `requests.post(url, headers=headers, json=payload, proxies=proxies, stream=True, timeout=(5, 30))`, accumulate at most 2,000,000 bytes, decode JSON only after the limit check, and expose status plus parsed data without logging URL query strings or headers. The async wrapper must call `asyncio.to_thread` inside `asyncio.wait_for(total_timeout)`.

- [ ] **Step 4: Convert scorer, translator, and profiler call chains to async**

Await the provider wrapper from `score_unscored_articles`, `prepare_articles_for_scoring`, and `generate_user_profile`. Preserve provider-specific payload and parsing behavior. Pass Gemini API credentials through the `x-goog-api-key` header instead of the URL query string.

- [ ] **Step 5: Bound pending paid work**

Add query limits of 500 pending articles per scoring run and 500 pending articles per translation run, retain configured batch sizing within `1..50`, and truncate prompt title/description values to the ingestion limits before sending.

- [ ] **Step 6: Run focused/full suites and commit Task 5**

Run: `python -m unittest tests.test_provider_http tests.test_ai_scorer tests.test_profile_logic -v`

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`

```bash
git add app/services/provider_http.py app/services/ai_scorer.py app/services/translator.py app/services/profiler.py tests/test_provider_http.py tests/test_ai_scorer.py tests/test_profile_logic.py
git commit -m "fix: isolate and bound AI provider requests"
```

---

### Task 6: Prevent Cross-Article AI Result Injection and Retry Fan-Out

**Files:**
- Modify: `app/services/ai_scorer.py:148-198,358-385,466-524`
- Modify: `app/services/translator.py:60-155,261-304`
- Modify: `app/services/profiler.py:38-125`
- Expand: `tests/test_ai_scorer.py`
- Expand: `tests/test_profile_logic.py`

**Interfaces:**
- Produces: `_batch_aliases(articles: list[dict]) -> tuple[list[dict], dict[str, int]]`
- Produces: `_parse_scores(raw_response: str, allowed_aliases: Mapping[str, int]) -> dict[int, int]`
- Produces: `_translate_articles_with_retry(articles: list[dict], config: dict, ai_config: dict, call_llm: Callable, budget: RetryBudget) -> dict[int, dict]`
- Produces: `RetryBudget.remaining: int` with `consume() -> bool`.

- [ ] **Step 1: Write failing cross-record and retry-budget tests**

```python
def test_score_parser_ignores_unknown_and_duplicate_aliases(self):
    raw = '[{"id":"item-1","score":90},{"id":"item-1","score":1},{"id":"item-999","score":100}]'
    self.assertEqual(_parse_scores(raw, {"item-1": 42}), {})

def test_translation_split_never_exceeds_shared_budget(self):
    calls = 0
    articles = [
        {"id": index, "title": f"title-{index}", "description": "body"}
        for index in range(10)
    ]
    def always_fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise ValueError("provider failed")
    result = _translate_articles_with_retry(articles, {}, {}, always_fail, RetryBudget(6))
    self.assertEqual(result, {})
    self.assertEqual(calls, 6)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_ai_scorer tests.test_profile_logic -v`

Expected: existing parser accepts real article IDs without an allowlist and recursive translation exceeds six attempts.

- [ ] **Step 3: Use opaque aliases and strict result association**

Build server-generated aliases `item-1`, `item-2`, and so on. Serialize each article as a JSON object inside explicit `<untrusted_articles>` delimiters rather than line-based `[ID:42]` framing. State in the system prompt that instructions inside the data section must be ignored. Accept a result only when its alias is allowed and appears exactly once.

- [ ] **Step 4: Add shared translation request budget**

Create one `RetryBudget(max(1, min(8, len(batch) + 1)))` per top-level translation batch and pass the same object to recursive children. Consume before every provider call; when empty, return no translations for the remaining subtree.

- [ ] **Step 5: Delimit and validate profile inputs/output**

Serialize liked/disliked articles as JSON inside `<untrusted_feedback>`. Cap persisted base prompt at 4,000 characters and active tags at 1,000 characters after structure/type validation. Never concatenate raw article text into a later scoring system message; store the model summary only.

- [ ] **Step 6: Run focused/full suites and commit Task 6**

Run: `python -m unittest tests.test_ai_scorer tests.test_profile_logic -v`

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`

```bash
git add app/services/ai_scorer.py app/services/translator.py app/services/profiler.py tests/test_ai_scorer.py tests/test_profile_logic.py
git commit -m "fix: bind AI results to submitted records"
```

---

### Task 7: Login Throttling and Production Security Guidance

**Files:**
- Create: `app/login_throttle.py`
- Expand: `tests/test_auth_security.py`
- Modify: `app/routers/auth.py:18-45`
- Modify: `README.md`
- Modify: `docker-compose.yml:5-6`

**Interfaces:**
- Produces: `LoginThrottle(max_failures: int = 5, window_seconds: int = 300, max_entries: int = 1024)`
- Produces methods: `is_blocked(key: str, now: float | None = None) -> bool`, `record_failure(key: str, now: float | None = None) -> None`, `record_success(key: str) -> None`.
- Consumes: client IP from FastAPI `Request.client.host`.

- [ ] **Step 1: Write failing throttle tests**

```python
def test_blocks_fifth_failure_until_window_expires(self):
    throttle = LoginThrottle(max_failures=5, window_seconds=300)
    for _ in range(5):
        throttle.record_failure("203.0.113.7", now=100.0)
    self.assertTrue(throttle.is_blocked("203.0.113.7", now=399.0))
    self.assertFalse(throttle.is_blocked("203.0.113.7", now=401.0))

def test_success_clears_failure_state(self):
    throttle = LoginThrottle(max_failures=5, window_seconds=300)
    throttle.record_failure("203.0.113.7", now=100.0)
    throttle.record_success("203.0.113.7")
    self.assertFalse(throttle.is_blocked("203.0.113.7", now=101.0))
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_auth_security -v`

Expected: import failure because `app.login_throttle` does not exist.

- [ ] **Step 3: Implement bounded in-memory throttling**

Use an `OrderedDict[str, deque[float]]` protected by `threading.Lock`. Prune timestamps outside the window on every access and evict the oldest key when the map exceeds 1,024 entries. Return HTTP 429 with a generic message before password comparison when blocked. Record only failures; clear on success.

- [ ] **Step 4: Harden documented deployment defaults**

Change Compose publication to loopback-only by default: `127.0.0.1:8000:8000`. Document TLS termination, reverse proxy forwarding, trusted proxy/IP considerations for rate limiting, `.env` mode `0600`, credential rotation, RAG key updates, egress filtering, and a warning that multi-worker deployments need shared or proxy-level throttling.

- [ ] **Step 5: Run focused/full suites and commit Task 7**

Run: `python -m unittest tests.test_auth_security -v`

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`

```bash
git add app/login_throttle.py app/routers/auth.py tests/test_auth_security.py README.md docker-compose.yml
git commit -m "fix: throttle login and harden deployment defaults"
```

---

### Task 8: Final Security Regression and Scan Reconciliation

**Files:**
- Modify only if verification reveals a regression: files from Tasks 1-7.
- Update: `docs/superpowers/specs/2026-07-31-security-hardening-design.md` only when final behavior differs from the approved design.

**Interfaces:**
- Consumes all security boundaries introduced above.
- Produces a verified finding-to-fix checklist in the final handoff.

- [ ] **Step 1: Run the complete automated suite**

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`

Expected: all tests pass with no warnings containing credentials or provider URLs with query-string keys.

- [ ] **Step 2: Run syntax and diff checks**

Run: `python -m compileall -q app tests`

Run: `git diff --check HEAD~7..HEAD`

Expected: both exit 0.

- [ ] **Step 3: Verify local secret posture without revealing values**

Check that `.env` is ignored, mode `0600`, all three rotated secrets are non-placeholder and meet their minimum lengths, and `DISABLE_AUTH` is false. Output only boolean/classification results.

- [ ] **Step 4: Perform browser and network-boundary smoke tests**

Verify login, feed preview, subscription listing, article opening, RAG authentication, loopback RSS rejection, oversized-response rejection, theme, Popover, and Toast behavior. Confirm current user-authored frontend changes remain present.

- [ ] **Step 5: Reconcile every scan finding**

Map the 5 high, 13 medium, and 8 low actionable candidates to a fix, documented residual risk, or explicit non-security product limitation. Do not claim the partial scan is complete.

- [ ] **Step 6: Commit verification-only corrections if needed**

If verification required code corrections, first add a failing regression test, then commit only the correction and its test:

```bash
git add app tests
git commit -m "fix: close security regression"
```

If no correction is needed, do not create an empty commit.
