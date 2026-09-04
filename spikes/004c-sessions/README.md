# Spike 004c — Sessions (cookie persistence across scrape calls)

## TL;DR

**Verdict: PARTIAL** — a scrapex `Session` class is *safe enough* and
*useful enough* to be worth shipping as an optional API, but it does **not**
clearly beat `httpx.AsyncClient(cookies=...)` for users who already know
what they're doing. Recommend shipping it as a thin convenience layer with
two small extra guarantees (the sensitive-name guard and the
value-free `.list()` snapshot), but do not make it the default.

## What the spec asked for

A `scrapex.Session` that:
- persists cookies across `scrape()` calls,
- exposes the cookie jar for inspection,
- clears via `.clear()`,
- never logs cookies,
- never encrypts cookies.

## Survey — what to copy from each

### httpx.AsyncClient(cookies=...)
- **Copy:** the underlying `Cookies` object is dict-like, persists inside
  the client, and is the inspection surface (`client.cookies[name]`).
  No reason to reinvent; we wrap the same `httpx.Cookies`.
- **Copy:** `.extract_cookies(response)` and `.set_cookie_header(request)`
  are the primitive hooks. Not exposed to users.
- **Improve on:** httpx's `repr(cookies)` shows values; we add
  `Session.list()` which returns `_CookieView`s (no value) for safe logging.

### requests.Session
- **Copy:** `requests.cookies.RequestsCookieJar.get_dict(domain=...)` —
  filtering by domain is genuinely useful for debugging multi-site
  scraping. We mirror it as `Session.list(domain=...)`.
- **Copy:** the `RequestsCookieJar` `clear_session_cookies()` vs `clear()`
  split. We keep just `clear()` for now; revisit if per-domain clear
  becomes a real ask.
- **Improve on:** `requests` has had CVEs around cookie handling
  (CVE-2024-35195 sessions-cookies). We avoid the jar entirely — we use
  httpx's `Cookies`, which is simpler and less surface area.

### curl_cffi
- **Copy:** the focus on TLS / impersonation fingerprint is orthogonal to
  cookies. curl_cffi delegates the cookie model to its own jar; nothing
  to lift specifically.
- **Improve on:** curl_cffi's `Session.cookies` is mutable and prints
  values on repr — same exposure as requests. We add the sensitive-name
  guard.

## Design — what's in `Session` vs what's not

### In
- One `httpx.AsyncClient` (we don't reinvent the HTTP layer).
- `.cookies` — the raw `httpx.Cookies` for direct inspection.
- `.list()` — a value-free snapshot for safe logging.
- `.set(name, value, *, sensitive=False)` — programmatic cookie set,
  with a sensitive-name guard that warns but never echoes the value.
- `.clear()` — wipe the jar.
- `async with Session() as s:` — async context manager.
- `await s.scrape(req)` — runs the public extraction pipeline on top
  of the session's fetch path (so Set-Cookie lands in our jar).

### Out (explicit non-goals)
- **No disk persistence.** No SQLite, no JSON file, no default cache dir.
  Cookies are memory-only. The user can persist manually if they want;
  every persisted cookie jar is a security liability.
- **No cookie encryption.** Spec rule: out of scope. Users wrap
  `session.cookies` themselves.
- **No `__repr__` redaction.** Adding magic to `__repr__` would be a lie
  (other code paths still see values). Instead, `.list()` is the
  *intended* logging surface.
- **No automatic log-cookie scrubbing.** We don't log. Scrapex's logging
  is at the user's discretion.
- **No browser-side cookies.** Playwright owns its own cookie context;
  `Session` covers the HTTP fetcher path only.

## Security check — can a user accidentally leak a cookie?

Three tested paths:

1. **Normal logging path** — calling `print(session.cookies)` will print
   the raw `httpx.Cookies` repr, which DOES include values. We don't
   hide this. Users who want safe logging must use `session.list()`.
   This is a deliberate trade — false-redaction is worse than honest
   exposure.
2. **Sensitive-name guard** — calling `session.set("auth_token", "...")`
   without `sensitive=True` raises `UserWarning`. Verified: warning
   message contains the name but never the value.
3. **Traceback / error path** — verified: raising a `FetchError` (4xx)
   does NOT include cookie values. Verified: raising an arbitrary error
   with a cookie value in scope only leaks if the user's own message
   string included it (i.e. it's the user's choice, not scrapex's).

**Can a user accidentally leak?** Yes, by printing `session.cookies`
directly. We make this less likely by:
- providing `session.list()` (value-free) as the obvious introspection,
- warning when a sensitive name is set programmatically.

We don't pretend to make printing the jar safe. That would be a worse
failure mode.

## Usefulness check — does it beat `httpx.AsyncClient(cookies=...)`?

Honest answer: **for the same task, it's a wash.**

The minimal "5 sequential cookies stick" case is one line with raw httpx:

```python
async with httpx.AsyncClient(cookies={}) as client:
    r1 = await client.get(url1)   # sets cookies
    r2 = await client.get(url2)   # cookies persist
```

…versus our Session, which wraps that and adds the extraction pipeline.
The wins scrapex's `Session` has over raw httpx are *not* cookie-related:

1. **Extraction is included.** You get `ScrapeResult`, not just `httpx.Response`.
2. **Sensitive-name guard.** httpx does not warn.
3. **`list()` value-free snapshot.** httpx doesn't have this.
4. **One consistent surface across the rest of scrapex.** You use the
   same `ScrapeRequest` you already know.

For a user who only wants cookies and already has extraction elsewhere,
raw httpx is simpler. **For a scrapex user, Session keeps everything
in the same vocabulary** — and that's the real value proposition. Not
the cookies themselves.

## Verdict

**PARTIAL.**

- All three spec conditions (persist / inspect / not-logged) pass the
  probe.
- Session does NOT meaningfully beat httpx for cookie behavior alone.
- It DOES add genuine value as the integration point for scrapex's
  extraction pipeline, with the sensitive-name guard as a small but
  real safety improvement.

### Recommendation

Ship `Session` as an optional public API in `scrapex/__init__.py` with
this surface:

```python
from scrapex import Session, scrape
async with Session() as s:
    await s.scrape(req1)
    await s.scrape(req2)   # cookies persist
    s.list()               # safe-to-log
    s.clear()              # wipe
```

Keep `scrape()` (the no-session one) as the default — sessions are
opt-in. Document explicitly: "cookies live in memory only; nothing on
disk."

Do **not** build a default session behind the user's back. Default
state = no jar = no leak surface.

## What to deliver next

1. Move `Session` to `scrapex/sessions.py` (not a spike anymore).
2. Wire `Session.scrape()` to call scrapex's existing
   `scrapex.scrape.scrape()` by passing the session's client into
   `HttpFetcher` (small refactor: make `HttpFetcher` accept a
   pre-built `httpx.AsyncClient`).
3. Add a `--session` flag to the CLI for parity.
4. Tests in `tests/test_sessions.py` mirroring the probe assertions.

## Probe output (last run)

```
=== test server up at http://127.0.0.1:58532 ===
[1] login (server sets 3 cookies)
[2] /whoami — expect all 3 cookies back
    echoed cookies: ['csrf', 'session', 'tracking']
[3] /a (CSS extraction)
[4] /b (CSS extraction)
[5] /c (CSS extraction) — confirm session still alive

[inspection] session.cookies (raw httpx.Cookies)
  len: 3
  list (value-free): [cookie(name='session', sensitive=True), cookie(name='csrf', sensitive=True), cookie(name='tracking', sensitive=False)]

[security] sensitive-name guard
  warning raised without leaking value: ["setting a cookie whose name looks sensitive; if this is intentional, pass sensitive=True. cookie(name='auth_token', sensitive=True)"]

[security] explicit sensitive=True suppresses warning

[security] raise an error with cookie value in scope
  traceback length: 285 chars
  FetchError traceback does NOT contain cookie value ✓

[inspection] session.clear() wipes the jar
  len after clear: 0
  /whoami after clear: {}

=== probe summary ===
PASS — session persists cookies, jar is inspectable, no value leaked via warnings or FetchError traceback
```

Existing test suite (`pytest tests/ -q`): **255 passed**.
