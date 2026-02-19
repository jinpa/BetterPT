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
