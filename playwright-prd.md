# MedBridge Go export – Playwright-based PRD

**Goal**  
One place to see all current workouts from multiple PTs: authenticate as you, use one or more pasted access tokens (each with a label like "knee", "elbow"), load each program’s workout from MedBridge Go, and produce a single browsable static site deployable to GitHub Pages.

This PRD defines the **Playwright-based export** that replaces the previous requests/cookie approach. The change is driven by the multi-program export issue: with requests and cookies, every program received the same workout content. See [docs/MULTI_PROGRAM_EXPORT_ISSUE.md](docs/MULTI_PROGRAM_EXPORT_ISSUE.md) for the full problem summary and evidence.

---

## 1. Why Playwright

**Problem**  
When exporting multiple programs in one run (e.g. `MB_TOKENS=knee:CODE1,neck:CODE2,elbow:CODE3`), every program got the same workout content (e.g. the knee workout). The build step produced distinct `knee.html`, `neck.html`, `elbow.html` with correct titles, but the exercise lists were identical. With requests + cookies we have no reliable way to get a different program’s data per token.

**Root cause (working assumption)**  
MedBridge treats “current program” as an account-level (or otherwise persistent) default. The cookie/API-only flow cannot reliably switch it. The SPA in a real browser likely sets or reads this state in a way we don’t replicate (full app load, storage, or different API usage). So with requests we only ever get one program’s data, and we could not obtain or pass the correct episode/program id for the others.

**Decision**  
Use Playwright for:

1. **Visibility** – See exactly what the real browser does (network, redirects, responses) when logging in and submitting different tokens, so we know how “current program” is set and which request returns each program’s workout.
2. **Correctness** – Run the export in a real browser so each (name, token) gets the correct workout data, or replicate the discovered flow in requests if Phase 1 shows that’s feasible.

---

## 2. Phased approach

### Phase 1 – Debug / visibility

A Playwright script that:

- Logs in with credentials from env.
- Submits one token, or multiple tokens in sequence.
- Records network traffic (e.g. XHR to `episode_with_video_urls` or equivalent), redirects, and any storage/cookies that change.

**Goal:** Identify exactly which request or state yields each program’s data, so we can either replicate in requests (if possible) or lock the Playwright flow for Phase 2.

**Deliverable:** Script plus short documentation of “how current program is set” (URLs, request params, storage, or DOM cues).

### Phase 2 – Playwright export

A script that, for each `(name, token)` in config:

- Runs in a real browser (or clean browser context per program).
- Logs in, submits that token, and waits for “current program” to reflect that program (e.g. via URL, DOM, or API response).
- Either (i) calls the same API we use today from the browser context and captures the correct JSON, or (ii) scrapes the SPA.
- Writes `workout_<name>.json` under `scripts/out/` in the **same schema** as today so `scripts/build_site.py` needs no changes.

**Optional:** Keep the requests-based `scripts/export_workout.py` as a fallback or remove it once the Playwright export is stable.

---

## 3. Scope and out of scope

**In scope**

- Same as the original product plan: current workouts only, manual refresh, GitHub Pages, credentials via env for now (UI later).
- Browser automation (Playwright) for the export step.
- Optional headless vs headed mode for debugging.

**Out of scope (unchanged)**

- Scheduled/automatic refresh (manual only).
- History, progress, or media (videos/PDFs) in v1.
- Editing workouts on MedBridge (read-only aggregation).

---

## 4. Technical choices

- **Stack:** Python 3 + Playwright (e.g. `playwright` package). Existing `scripts/build_site.py` and `dist/` output unchanged. Env and conventions (`.env`, `MB_USER`, `MB_PASS`, `MB_TOKENS` or `MB_TOKEN`/`MB_TOKEN_NAME`) preserved.
- **Output contract:** The Playwright export must produce `scripts/out/workout_<slug>.json` in the same schema as the current export so [scripts/build_site.py](scripts/build_site.py) continues to work without modification.
- **Where to run:** Local first; later CI if desired. Browser may be headless by default with an option for headed mode when debugging.

---

## 5. Success criteria

- **Phase 1:** The debug script runs and produces a clear picture of how “current program” is set (e.g. which request or navigation differs per token). Findings are documented.
- **Phase 2:** Running the Playwright export with `MB_TOKENS=knee:CODE1,neck:CODE2,elbow:CODE3` produces three distinct `workout_*.json` files with correct exercise counts and content per program. `build_site.py` then produces correct `knee.html`, `neck.html`, and `elbow.html`.

---

## 6. Risks and mitigations

- **ToS:** Scraping may conflict with MedBridge’s terms; you assume responsibility; we keep usage minimal and read-only. (Same as original PRD.)
- **Anti-scraping:** Playwright uses a real browser, which may be more robust; add conservative delays if needed.
- **Playwright dependency:** Requires installing browser binaries (`playwright install`); document in README and setup.
- **Fragility:** If MedBridge changes DOM or URLs, the export may break. Prefer API calls from the browser context when Phase 1 shows they are sufficient, to reduce reliance on DOM selectors.

---

## 7. Project context update

Project rules (e.g. [.cursor/rules/project-context.mdc](.cursor/rules/project-context.mdc)) should be updated to:

- Allow Playwright for the export (relax or scope the “no Playwright” rule to “POC originally used requests; production export uses Playwright”).
- Point to this PRD for the export strategy.

[docs/PROJECT_NOTES.md](docs/PROJECT_NOTES.md) should reference this PRD and the new script(s) once they exist.

---

## 8. Next steps

1. **Implement Phase 1** – Build the debug script, run it against real tokens, and document how “current program” is set.
2. **Implement Phase 2** – Build the Playwright export script, validate multi-program output, then deprecate or replace the requests-based `export_workout.py` as appropriate.
3. **Update project context** – Adjust `.cursor/rules/project-context.mdc` and `docs/PROJECT_NOTES.md` to reference `playwright-prd.md` and the new export approach.

---

## References

- Problem and evidence: [docs/MULTI_PROGRAM_EXPORT_ISSUE.md](docs/MULTI_PROGRAM_EXPORT_ISSUE.md)
- Original product plan: [prd.md](prd.md)
- Current export script: [scripts/export_workout.py](scripts/export_workout.py)
- Build script: [scripts/build_site.py](scripts/build_site.py)
- Auth/API notes: [docs/PROJECT_NOTES.md](docs/PROJECT_NOTES.md)
