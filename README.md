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

### Export workout(s) to JSON

Export one or more programs to minimal JSON for the static site.

**Multiple programs in one run:** set in `.env`:
```bash
MB_TOKENS=knee:ACCESS_CODE_1,elbow:ACCESS_CODE_2
```
Then run `python scripts/export_workout.py`. Each program is written to `scripts/out/workout_<name>.json`.

**Single program:** set `MB_TOKEN` and optionally `MB_TOKEN_NAME` in `.env`, then run `python scripts/export_workout.py`. Output: `workout.json` or `workout_<name>.json`. Override path with `WORKOUT_JSON_PATH`.

### Build static site

After exporting (one or more `workout*.json` files in `scripts/out/`), generate the static site:

```bash
python scripts/build_site.py
```

Output: `dist/index.html` (list of programs), `dist/<slug>.html` (one page per program with exercises and instructions), and `dist/style.css`. Open `dist/index.html` in a browser or deploy `dist/` to GitHub Pages.

### Phase 1 debug (Playwright)

To run the Phase 1 debug script (login + token(s), record network/redirects/storage to discover how “current program” is set):

```bash
pip install -r requirements.txt
playwright install   # one-time: install browser binaries
python scripts/phase1_debug_network.py   # optional: --headed or PHASE1_HEADED=1 to show browser
```

Outputs go to `scripts/out/phase1_*`. See [docs/PHASE1_FINDINGS.md](docs/PHASE1_FINDINGS.md) and [playwright-prd.md](playwright-prd.md).
