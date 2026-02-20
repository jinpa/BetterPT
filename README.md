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

### Export workout(s) to JSON (Phase 2 — recommended)

For **multiple programs** with correct workout per program, use the Playwright export (one browser context per token):

```bash
pip install -r requirements.txt
playwright install   # one-time
# In .env: MB_USER, MB_PASS, MB_TOKENS=knee:CODE1,neck:CODE2,elbow:CODE3
python scripts/phase2_export_playwright.py   # optional: --headed or PHASE2_HEADED=1
```

Output: `scripts/out/workout_<slug>.json` per program. Then run `python scripts/build_site.py`.

**Legacy (single program or same workout for all):** `scripts/export_workout.py` with `MB_TOKEN` and optional `MB_TOKEN_NAME`, or `MB_TOKENS=name1:code1,...` (requests-based; multi-program returns same workout in practice).

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
