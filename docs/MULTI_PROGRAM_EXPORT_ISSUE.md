# Multi-program export issue (requests/cookie approach)

Summary of the problem and attempted fixes so we don’t lose context. Use this when drafting a PRD for a Playwright-based export.

---

## Symptom

When exporting multiple programs in one run (`MB_TOKENS=knee:CODE1,neck:CODE2,elbow:CODE3`), **every program gets the same workout content** (the knee workout). The build step correctly produces `knee.html`, `neck.html`, `elbow.html` with different titles, but the exercise list is identical (e.g. 14 knee exercises in all three). Neck and elbow have fewer exercises in real life, so “14 exercises” is a clear sign we’re reusing the wrong program.

---

## Current stack

- **Auth:** Cookie-based. Login via `GET /sign_in` → POST credentials. Access code via `GET /access_token` → `POST /register_token` with token + CSRF.
- **Data:** `GET /api/v4/plus/episode/episode_with_video_urls` returns JSON: `program`, `program.program_exercises`, `episode`. No query params in our current calls; we rely on “current” program for the session.
- **List API:** `GET /api/v4/plus/episodes/` returns an `episodes` array but only **one** episode (the account’s default/current), not all programs.

Project rule: “Cookie auth; no Playwright.” Scripts: `requests`, BeautifulSoup, no browser.

---

## What we know

1. **Same IDs for all programs**  
   Exported JSON for knee, neck, and elbow all had the same `program_id` (129203793) and `episode_id` (137434732). Only `program_name` differed because we overwrite it from the `MB_TOKENS` label.

2. **“Current” program is effectively fixed per account**  
   Changing the order of tokens in `.env` (e.g. neck first) did **not** change the result; we still got knee content for all. So the server is not “stuck on first token”—it returns a single default program (knee) for the account regardless of which token we submit or in what order.

3. **One session vs many doesn’t fix it**  
   We tried: single session with logout + re-login between tokens; new session per token in one process; **subprocess per token** (each run only submits one code). In every case the API still returned the same (knee) program. So the limitation is not “session reuse” but how the server decides which program to return.

4. **Episodes list is no help for “which program did this token activate?”**  
   After submitting the neck token, `GET /api/v4/plus/episodes/` still returned a single episode with id 137434732 (knee). So we never get a distinct episode id for neck/elbow from that endpoint.

5. **Token response doesn’t give us an episode id**  
   We inspected the `register_token` response (no redirect follow): body, redirect `Location` query/fragment, and HTML patterns. We didn’t find an episode or program id for the newly activated program. So we can’t call `episode_with_video_urls?episode_id=X` with the right id per program.

6. **Real-world behavior**  
   The user has to “log out and log back in” between programs in the MedBridge UI to switch. That suggests the live SPA or server state is what actually switches “current” program, and our cookie/API-only flow doesn’t replicate that.

---

## What we tried (concise)

- Logout (`GET /sign_out`) + re-login between tokens in one session.
- New `requests.Session()` per token (no shared cookies).
- One subprocess per token so each process only ever submits one code.
- Parsing `register_token` response (JSON, Location, HTML) for `episode_id` / `program_id`.
- Calling `episode_with_video_urls?episode_id=...` using the only id we have (137434732); that always returns knee.
- Using the first episode from the episodes list when it had multiple (still only one in practice).
- Safeguard: error if the same `(program_id, episode_id)` is written for two different token names.

None of this produced different workout content per program.

---

## Root cause (working assumption)

MedBridge’s API treats “current program” as an account-level (or otherwise persistent) default that we cannot change in a reliable way with cookie auth and the endpoints we’re using. The SPA in a real browser may set or read this state in a way we don’t replicate (e.g. full app load, storage, or different API usage). So with requests + cookies we only ever get one program’s data (knee), and we have no way to obtain or pass the correct episode/program id for the others.

---

## Decision / next step

We’re documenting this and **moving to a Playwright-based approach** for the export (or at least for debugging and then possibly for the main flow). Goals:

1. **Visibility:** See exactly what the real browser does (network, redirects, responses) when logging in and submitting different tokens, so we know how “current program” is set and which request returns each program’s workout.
2. **Correctness:** Either replicate that in requests (if we find the right API/params) or run the export in a real browser so we get the right workout per program.

A separate PRD will define the Playwright-based solution (e.g. debug script first, then optional full Playwright export), and may relax the “no Playwright” rule in project context.

---

## References

- Export script: `scripts/export_workout.py`
- Build script: `scripts/build_site.py` (reads `scripts/out/workout_*.json`, writes `dist/`)
- Auth/API notes: `docs/PROJECT_NOTES.md`
- Project context: `.cursor/rules/project-context.mdc`
- Current product plan: `prd.md`
