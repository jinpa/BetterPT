# BetterPT — discovery log and reference

Notes and decisions from building the project. No need to load this every time; use when you need auth/API details or script behavior.

**Full plan:** [prd.md](../prd.md). **Concise context (load every time):** [.cursor/rules/project-context.mdc](../.cursor/rules/project-context.mdc).

---

## Auth and MedBridge flow

- **Login:** `GET /sign_in` → form posts to `/sign_in` with `patient[username]`, `patient[password]`. Cookie-based session.
- **Access code:** `GET /access_token` returns a form with hidden `X-CSRF-Token`; `POST /register_token` with `token=<code>` and that CSRF value. Each code switches the “current” program for the session.
- **Workout data:** `GET /api/v4/plus/episode/episode_with_video_urls` (same-origin, session cookies) returns JSON: `program`, `program.program_exercises` (name, description HTML, sets, reps, hold, note, etc.), `episode`. No HTML scraping of the SPA for content.
- **List API:** `GET /api/v4/plus/episodes/` returns `episodes` but does **not** return all workouts (user may have multiple PT programs but only one episode in the list). We do not use it for export; use access codes (MB_TOKENS) instead.

## Scripts (detailed)

| Script | Purpose |
|--------|---------|
| `scripts/simple_scrape.py` | POC: login, optional register_token, save HTML to `scripts/out/` (01_sign_in … 05_home_after_token). Redacts JWT/CSRF in saved HTML. |
| `scripts/discover_api.py` | Login, optional token, fetch JS bundle, probe endpoints, call episode_with_video_urls; write `api_discovery.txt` and high-signal summary. |
| `scripts/export_workout.py` | Login; with `MB_TOKENS=name1:code1,name2:code2` exports each to `workout_<name>.json` in one run; else single `MB_TOKEN`/`MB_TOKEN_NAME` → `workout.json` or `workout_<name>.json`. |
| `scripts/build_site.py` | Read all `scripts/out/workout*.json`, generate `dist/index.html`, `dist/<slug>.html`, `dist/style.css`. |
| `scripts/check_list_workouts_api.py` | Exploratory: probe list-style APIs after login. Episodes list does not return all workouts; kept for reference only. |

## Other

- Saved HTML in `scripts/out/` redacts `window.jwt` and `X-CSRF-Token` values before writing to disk.
- Run scripts from repo root; use `.venv/bin/python` or `source .venv/bin/activate` so Cursor’s terminal doesn’t depend on system PATH.
