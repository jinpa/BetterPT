# MedBridge Go workout aggregator – PRD and scraping POC

## Your choices (summary)

- **Tokens**: Short code/token string you paste (we'll discover exactly where it's used in POC).
- **Data**: Current assigned workouts only: list + exercise details (name, sets, reps, instructions). No history or media for v1.
- **Refresh**: Manual only (run a command or "Regenerate" to re-scrape and rebuild).
- **Hosting**: GitHub Pages so you can open the site on phone/tablet.
- **Credentials**: POC uses env/config (e.g. `.env`); later add a simple UI that stores credentials (e.g. local storage or local DB).

---

## 1. PRD outline

**Goal**  
One place to see all current workouts from multiple PTs: authenticate as you, use one or more pasted access tokens (each with a label like "knee", "elbow"), scrape MedBridge Go, and produce a single browsable static site deployable to GitHub Pages.

**Users**  
You (and optionally other patients who use MedBridge Go the same way).

**Core flows**

- **Setup**: Enter MedBridge username, password, and one or more (token, name) pairs. Stored via config/env in POC; later via a simple UI.
- **Regenerate**: Run a process that (1) logs in as you, (2) for each token, uses it to load that PT's workout, (3) scrapes current workout list and exercise details, (4) builds a static site and (optionally) deploys to GitHub Pages.
- **Browse**: Open the static site (local or GitHub Pages), switch between named workouts (e.g. "knee", "elbow") and view exercise details.

**Out of scope for v1**

- Scheduled/automatic refresh (manual only).
- History, progress, or media (videos/PDFs) unless we add them after POC.
- Editing workouts on MedBridge (read-only aggregation).

**Success criteria**

- POC: Script can log in and, for at least one token, return a machine-readable list of current workouts (and ideally exercise fields).
- v1: Static site shows all named workouts, easy switching, deployable to GitHub Pages; credentials via config (UI can follow).

**Risks / mitigations**

- **Token usage**: We don't yet know how the pasted "code" is used (URL param, header, cookie, form field). POC must discover this (e.g. inspect network and HTML after "joining" or "entering" a token).
- **Anti-scraping**: If the site blocks or heavily rate-limits automation, we may need browser automation (e.g. Playwright) and conservative delays; POC will clarify.
- **ToS**: Scraping may conflict with MedBridge's terms; you assume responsibility; we keep usage minimal and read-only.

---

## 2. POC: prove scraping works

**Objective**  
Validate: (1) how the pasted token is used (where it's sent, in what shape), (2) that we can authenticate as you and then list current workouts (and key exercise details) for a single token.

**Approach**

- **Browser automation** (recommended): Use **Playwright** (Python or Node) to drive a real browser so we see the same behavior as you (cookies, JS, redirects). Easiest way to discover token flow and avoid missing JS-rendered content.
- **Steps**  
  1. Launch browser, go to MedBridge Go login (e.g. `medbridgego.com` or the URL you use).  
  2. Log in with credentials from env (e.g. `MB_USER`, `MB_PASS`).  
  3. Either navigate to a "enter code" / "join program" flow and paste the token, or visit a known URL that accepts the token (to be discovered).  
  4. From the resulting page(s), locate the list of current workouts and one or two exercise detail views.  
  5. Extract: workout names/IDs, exercise names, sets, reps, instructions (and optionally URLs or keys for later media).  
  6. Output: print or write to a small JSON file (e.g. `workouts.json`) so we know the schema we'll use for the static site.

**Discovery tasks in POC**

- Map login URL, form field names, and any 2FA or captcha.  
- Find where the "access token" is entered (URL param vs form vs in-app only).  
- Identify the DOM or API that provides the workout list and exercise details (if the site uses an API, we can optionally call it directly in the full app to reduce fragility).  
- Note any redirects or multi-step flows after token entry.

**Deliverable**

- Single script (e.g. `scripts/poc_scrape.py` or `scripts/poc_scrape.mjs`) runnable with credentials (and one token) in env; output = one JSON file with at least one workout and its exercises.  
- Short `README` section: "How to run the POC" and "What we learned" (token usage, URLs, selectors or API endpoints).

**If the site is mostly API-driven**  
After opening the app in the browser, inspect Network tab for XHR/fetch. If workouts are loaded via JSON (e.g. `GET /api/programs/...`), we can document those endpoints and, in the full pipeline, prefer them over HTML scraping for stability.

---

## 3. From POC to full solution (high level)

- **Scraper module**: Generalize POC to accept multiple (token, name) pairs from config; loop over each, scrape into a common structure (e.g. `{ "knee": [...], "elbow": [...] }`), then pass to the static generator.
- **Static site generator**: One HTML (or a tiny generator e.g. 11ty or a simple script) that consumes the JSON and produces:
  - An index: list of named workouts (e.g. "Knee", "Elbow") with links.
  - Per-workout pages: list of exercises with name, sets, reps, instructions.
- **Regenerate**: Single command (e.g. `npm run build` or `python run_build.py`) that (1) runs the scraper with config, (2) runs the static generator, (3) outputs to `dist/` or `out/`.
- **GitHub Pages**: Push `dist/` (or `out/`) to a `gh-pages` branch or to a `docs/` folder, or use GitHub Actions to build on push and deploy.
- **Credentials UI (later)**: Simple local UI (e.g. small React/Vite or plain HTML form) to add/edit username, password, and (token, name) pairs; store in local storage or a local SQLite/JSON file; the regenerate step reads from that store instead of env.

---

## 4. Suggested repo layout (after POC)

```
BetterPT/
├── .env.example          # MB_USER, MB_PASS, optional MB_TOKENS (JSON or comma-separated)
├── scripts/
│   └── poc_scrape.*      # POC script
├── scraper/              # (after POC) multi-token scraper
├── site/                 # static site generator input/templates
├── dist/                 # generated static site (deploy this to GitHub Pages)
├── docs/                 # optional: PRD and "What we learned" from POC
└── README.md
```

---

## 5. Next step

**Immediate**: Implement the POC (one script + README). Once it runs and we know how the token is used and what we can scrape, we can lock the PRD (e.g. exact data fields and static site structure) and implement the scraper + static site + GitHub Pages flow. If you want, the next concrete step can be a short "POC script spec" (exact env vars, output JSON schema, and discovery checklist) so implementation is straightforward.
