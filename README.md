# BetterPT

Aggregate MedBridge Go workouts from multiple PTs into one browsable static site. See [prd.md](prd.md) for the plan.

## Quick start (simple scrape)

Use a virtual environment so `pip` doesn’t hit the system “externally-managed-environment” restriction:

```bash
cd BetterPT
python3 -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set MB_USER and MB_PASS
python scripts/simple_scrape.py
```

Inspect the saved pages under `scripts/out/`.

### Export current workout to JSON

To export the current program (after logging in and optionally submitting an access code) to a minimal JSON file for the static site:

```bash
# Optional: set MB_TOKEN and MB_TOKEN_NAME in .env (e.g. MB_TOKEN_NAME=knee)
python scripts/export_workout.py
```

Output: `scripts/out/workout.json` (program name, exercise list with name, description, sets, reps, hold, note). Override path with `WORKOUT_JSON_PATH`.

### Build static site

After exporting one or more workouts (run `export_workout.py` once per access code; set `MB_TOKEN` and `MB_TOKEN_NAME` in `.env` for each run so outputs go to `workout_<name>.json`), generate the static site:

```bash
python scripts/build_site.py
```

Output: `dist/index.html` (list of programs), `dist/<slug>.html` (one page per program with exercises and instructions), and `dist/style.css`. Open `dist/index.html` in a browser or deploy `dist/` to GitHub Pages.
