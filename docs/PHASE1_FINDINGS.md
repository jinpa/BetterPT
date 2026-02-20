# Phase 1 findings: how "current program" is set

Filled from a run of `scripts/phase1_debug_network.py` with tokens (neck, elbow, knee) and inspection of `scripts/out/phase1_*`. See [playwright-prd.md](../playwright-prd.md) for context.

---

## How current program is set

- **Server-side session, not per-request.** The SPA calls `GET /api/v4/plus/episode/episode_with_video_urls?episode_id=137434732&old_versions=1`. In the Phase 1 run, **the same `episode_id=137434732` (and same program id 129203793) was used for every call** — after login and after submitting each of the three tokens (neck, elbow, knee) in sequence. So “current program” is whatever the server associates with the session (cookie) and does **not** reliably switch when we POST to `/register_token` with a different token in the same session.
- **Login:** POST `/sign_in` → 302 to `/plus/resources`. Then the SPA fetches `session_info` (episode null) and then `episode_with_video_urls?episode_id=137434732` — so the SPA gets that default episode id from somewhere (likely server session or a prior API).
- **After each token:** POST `/register_token` → 302 to `/lite/resources`. The SPA then calls `episode_with_video_urls` again but still with **the same** `episode_id=137434732`. So submitting multiple access codes in one session does not change which episode the app requests; the session keeps returning the same (e.g. account default) program.
- **Redirects:** For the third token (knee), the chain was `register_token` → `sign_in`, so the server sent the user back to sign-in (possible session/limit behavior when switching tokens repeatedly).

---

## Relevant requests / params

- **`GET /api/v4/plus/episode/episode_with_video_urls?episode_id=<id>&old_versions=1`** — Returns workout JSON (program, program_exercises, episode). The `episode_id` query param is what selects the program. In our run the SPA always sent the same id (137434732); we never saw different ids per token.
- **`POST /register_token`** — Form body: `token=<code>` plus CSRF. Response: 302, `Location: https://www.medbridgego.com/lite/resources`. Response body is HTML (redirect), not JSON — so we do **not** get an `episode_id` or `program_id` in the token response to use for a subsequent API call.
- **`GET /api/v4/patientsession/session_info`** — Returned `episode: null` after login; does not expose a list of episode ids per token.

---

## Storage / cookie changes

- **Cookies:** Redacted in the Phase 1 output; session is cookie-based. “Current program” is almost certainly keyed by server-side session (cookies), not by a param we can override per request without a fresh session.
- **localStorage:** Only analytics/jwplayer keys (e.g. `_pendo_*`, `jwplayerLocalId`). No key that obviously stores `episode_id` or “current program”; the SPA appears to rely on server session (or in-memory state derived from the first API response) for which episode to request.

---

## Recommendations for Phase 2

- **One browser context (or login) per program.** To get a different workout per token, Phase 2 should use a **separate browser context** (or at least a fresh login/session) per `(name, token)`: log in, submit that token only, wait for the SPA to load, then capture the `episode_with_video_urls` response (or call the API from that context). Do not submit multiple tokens in the same session and expect different episode ids.
- **Optional:** After submitting a single token, inspect the first `episode_with_video_urls` request from the SPA to see if the server ever returns a different `episode_id` for that session; if so, we could call the same API with that id. The Phase 1 run suggests the server keeps one “current” episode per session, so one-context-per-token is the reliable approach.
- Keep using the same workout JSON schema so `build_site.py` is unchanged.

---

## Phase 2 outcome (confirmed limitation)

We tried: one context per token; token in URL path (`/access_token/CODE`); login-first vs token-URL-first; calling the API with no `episode_id`; headed browser. **In all cases the Playwright session showed the knee workout** (account default). Visiting `https://medbridgego.com/access_token/<neck_code>` in a normal browser can show the neck program, so the server applies the token in that flow (e.g. when the token is in the URL before or during login). In our automation, the session’s “current program” is set at login and does not change when we later visit `/access_token/CODE`.

**Concrete evidence:** When we load `/access_token/<neck_code>` in the script, the server returns the "Verify your access code" page with **provider name "Agile Physical Therapy"** (the knee PT) embedded in the page. The neck program's provider is different; the server is returning account-default (knee) context for that URL in our flow.

**Practical workaround:** Phase 2 writes one `workout_<slug>.json` per token but all contain the same (default) program data. For distinct programs you’d need to either (1) run the export once per program after manually opening that program’s URL in a real browser and copying session/cookies (not implemented), or (2) use a single token and accept one program per export run.
