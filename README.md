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
