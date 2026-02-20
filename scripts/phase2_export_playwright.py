#!/usr/bin/env python3
"""
Phase 2 Playwright export: one workout JSON per program using a fresh browser context per token.

Uses one context (session) per (name, token) so the server's "current program" is that token's
program. Captures the episode_with_video_urls API response and writes workout_<slug>.json in the
same schema as scripts/export_workout.py so build_site.py needs no changes.

Usage:
  Set MB_USER, MB_PASS in .env.
  Either MB_TOKENS=name1:code1,name2:code2 or MB_TOKEN=code and optional MB_TOKEN_NAME=name.
  Run from repo root: python scripts/phase2_export_playwright.py
  Optional: --headed or PHASE2_HEADED=1 to show the browser.
  Optional: --debug or PHASE2_DEBUG=1 to log program_id/episode_id per captured response.
  Optional: --only NAME to export just one program (e.g. --only neck).

Output: scripts/out/workout_<slug>.json per program.

Known limitation: MedBridge may return the account's default program (same for all tokens)
when accessed via API; if so, all workout_*.json will have the same exercises. Try --headed
in case the server behaves differently with a visible browser.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"
BASE = "https://www.medbridgego.com"
EPISODE_API_SUBSTR = "episode_with_video_urls"


def _slug(name: str) -> str:
    """URL-safe slug from program name for filenames."""
    safe = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[-\s]+", "-", safe).strip("-") or "workout"


def _parse_mb_tokens(value: str) -> list[tuple[str, str]]:
    """Parse MB_TOKENS env: 'name1:code1,name2:code2' -> [(name1, code1), (name2, code2)]."""
    pairs: list[tuple[str, str]] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        idx = part.find(":")
        if idx <= 0:
            continue
        name, code = part[:idx].strip(), part[idx + 1 :].strip()
        if name and code:
            pairs.append((name, code))
    return pairs


def _normalize_exercise(pe: dict) -> dict:
    """Build a minimal exercise object matching export_workout.py schema."""
    attrs = pe.get("program_exercise_attributes") or []
    attr_map = {a.get("type"): a.get("value") for a in attrs if isinstance(a, dict) and a.get("type")}
    return {
        "name": pe.get("name") or "",
        "description": (pe.get("description") or "").strip(),
        "min_sets": pe.get("min_sets"),
        "max_sets": pe.get("max_sets"),
        "min_reps": pe.get("min_reps"),
        "max_reps": pe.get("max_reps"),
        "sets": attr_map.get("sets"),
        "reps": attr_map.get("reps"),
        "hold": attr_map.get("hold"),
        "frequency": attr_map.get("frequency"),
        "note": (pe.get("note") or "").strip(),
        "priority": pe.get("priority"),
    }


def build_export_payload(api_payload: dict, program_name_override: str | None = None) -> dict:
    """Convert API response to minimal JSON for build_site.py (same schema as export_workout.py)."""
    episode = api_payload.get("episode") or {}
    program = api_payload.get("program") or {}
    program_name = program_name_override or episode.get("name") or "Workout"
    exercises_raw = program.get("program_exercises") or []
    exercises = [_normalize_exercise(pe) for pe in exercises_raw if isinstance(pe, dict)]
    return {
        "program_name": program_name,
        "program_id": program.get("id"),
        "episode_id": episode.get("id"),
        "exercise_count": len(exercises),
        "exercises": exercises,
    }


# Patterns to find episode_id or program_id in page source or URL (SPA bootstrap, script tags, query params).
_EPISODE_ID_PATTERNS = [
    re.compile(r'"episode_id"\s*:\s*(\d+)'),
    re.compile(r"'episode_id'\s*:\s*(\d+)"),
    re.compile(r"episode_id[\"']?\s*[:=]\s*[\"']?(\d+)"),
    re.compile(r'"episodeId"\s*:\s*(\d+)'),
    re.compile(r'data-episode-id=["\'](\d+)["\']'),
    re.compile(r"episode_with_video_urls\?[^\"']*episode_id=(\d+)"),
    re.compile(r"[?&]episode_id=(\d+)"),
]
_PROGRAM_ID_PATTERNS = [
    re.compile(r'"program_id"\s*:\s*(\d+)'),
    re.compile(r"'program_id'\s*:\s*(\d+)"),
    re.compile(r'"programId"\s*:\s*(\d+)'),
]


def _scrape_id_from_page(html: str, page_url: str = "") -> tuple[int | None, str]:
    """Search page source (and optional page URL) for episode_id or program_id. Returns (id, 'episode'|'program') or (None, '')."""
    text = html + "\n" + page_url
    for pat in _EPISODE_ID_PATTERNS:
        m = pat.search(text)
        if m:
            return (int(m.group(1)), "episode")
    for pat in _PROGRAM_ID_PATTERNS:
        m = pat.search(text)
        if m:
            return (int(m.group(1)), "program")
    return (None, "")


def _debug_payload(label: str, data: dict) -> None:
    """Log program_id, episode_id, name, exercise count for debugging."""
    prog = data.get("program") or {}
    ep = data.get("episode") or {}
    n = len((prog.get("program_exercises") or []) if isinstance(prog, dict) else [])
    print(
        f"  [DEBUG] {label}: program_id={prog.get('id')!r} episode_id={ep.get('id')!r} "
        f"name={ep.get('name') or prog.get('name')!r} exercises={n}",
        file=sys.stderr,
    )


def run_one_program(
    context_factory,
    user: str,
    password: str,
    name: str,
    token: str,
    debug: bool = False,
) -> dict | None:
    """
    Use a fresh browser context: login, submit this token only, capture episode_with_video_urls
    response, return the API payload dict or None on failure.
    """
    context = context_factory()
    captured: list[dict] = []

    def on_response(response):
        try:
            url = response.url
            if EPISODE_API_SUBSTR in url and response.status == 200:
                body = response.body()
                if body:
                    data = json.loads(body.decode("utf-8", errors="replace"))
                    if isinstance(data, dict) and (data.get("program") or data.get("episode")):
                        captured.append(data)
                        if debug:
                            _debug_payload(f"captured #{len(captured)} ({name})", data)
        except Exception:
            pass

    context.on("response", on_response)
    page = context.new_page()

    try:
        # Hit the program URL first so the server ties the session to this token when we log in.
        # If we log in first, the session gets a default program (knee) and /access_token/CODE doesn't switch it.
        token_safe = quote(token, safe="")
        page.goto(f"{BASE}/access_token/{token_safe}", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_load_state("networkidle", timeout=20000)
        # If we were sent to sign-in, log in then hit the token URL again so server binds session to this program.
        if "sign_in" in page.url or page.locator('input[name="patient[username]"]').count() > 0:
            page.fill('input[name="patient[username]"]', user)
            page.fill('input[name="patient[password]"]', password)
            page.click(
                'form#patient-signin-form button[type="submit"], form[action*="sign_in"] button[type="submit"], input[type="submit"]'
            )
            page.wait_for_load_state("networkidle", timeout=20000)
            # Re-visit token URL so the server associates this session with this program.
            page.goto(f"{BASE}/access_token/{token_safe}", wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(2000)

        # Try scraping page source for episode_id or program_id; if found, fetch API with that id.
        html = page.content()
        scraped_id, id_kind = _scrape_id_from_page(html, page.url)
        if scraped_id and id_kind:
            if debug:
                print(f"  [DEBUG] ({name}) scraped {id_kind}_id={scraped_id} from page source", file=sys.stderr)
            param = "episode_id" if id_kind == "episode" else "program_id"
            fetch_with_id = f"{BASE}/api/v4/plus/episode/episode_with_video_urls?{param}={scraped_id}&old_versions=1"
            try:
                chosen = page.evaluate(
                    """async (url) => {
                        const r = await fetch(url, { credentials: 'same-origin' });
                        if (!r.ok) return null;
                        return await r.json();
                    }""",
                    fetch_with_id,
                )
                if chosen and isinstance(chosen, dict) and (chosen.get("program") or chosen.get("episode")):
                    if debug:
                        _debug_payload(f"fetch with scraped {param} ({name})", chosen)
                    return chosen
            except Exception as e:
                if debug:
                    print(f"  [DEBUG] ({name}) fetch with scraped id failed: {e}", file=sys.stderr)

        # No scraped id or fetch failed: try without episode_id (session "current" program).
        fetch_url = f"{BASE}/api/v4/plus/episode/episode_with_video_urls?old_versions=1"
        try:
            chosen = page.evaluate(
                """async (url) => {
                    const r = await fetch(url, { credentials: 'same-origin' });
                    if (!r.ok) return null;
                    return await r.json();
                }""",
                fetch_url,
            )
        except Exception as e:
            if debug:
                print(f"  [DEBUG] ({name}) fetch failed: {e}", file=sys.stderr)
            chosen = None
        if chosen and isinstance(chosen, dict) and (chosen.get("program") or chosen.get("episode")):
            if debug:
                _debug_payload(f"fetch no episode_id ({name})", chosen)
            return chosen
        # Fallback: use last intercepted response (may still be wrong program).
        if captured:
            chosen = captured[-1]
            if debug:
                _debug_payload(f"fallback last captured ({name})", chosen)
            return chosen
        # Token-URL-first may leave us on a page that never loads the app (e.g. not logged in).
        # Fall back to login first, then token URL, so we at least get a workout (often account default).
        if debug:
            print(f"  [DEBUG] ({name}) no payload, trying login-first then token URL", file=sys.stderr)
        captured.clear()
        page.goto(f"{BASE}/sign_in", wait_until="domcontentloaded", timeout=20000)
        page.fill('input[name="patient[username]"]', user)
        page.fill('input[name="patient[password]"]', password)
        page.click(
            'form#patient-signin-form button[type="submit"], form[action*="sign_in"] button[type="submit"], input[type="submit"]'
        )
        page.wait_for_load_state("networkidle", timeout=20000)
        page.goto(f"{BASE}/access_token/{token_safe}", wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(2000)
        if debug:
            print(f"  [DEBUG] ({name}) fallback: current URL = {page.url}", file=sys.stderr)
            # Save page HTML so we can inspect for episode_id / program_id patterns.
            (OUT_DIR / f"phase2_debug_page_{_slug(name)}.html").write_text(page.content(), encoding="utf-8")
            print(f"  [DEBUG] ({name}) wrote phase2_debug_page_{_slug(name)}.html to scripts/out/", file=sys.stderr)
        chosen = None
        html = page.content()
        scraped_id, id_kind = _scrape_id_from_page(html, page.url)
        if scraped_id and id_kind:
            if debug:
                print(f"  [DEBUG] ({name}) fallback scraped {id_kind}_id={scraped_id}", file=sys.stderr)
            param = "episode_id" if id_kind == "episode" else "program_id"
            fetch_with_id = f"{BASE}/api/v4/plus/episode/episode_with_video_urls?{param}={scraped_id}&old_versions=1"
            try:
                chosen = page.evaluate(
                    """async (url) => {
                        const r = await fetch(url, { credentials: 'same-origin' });
                        if (!r.ok) return null;
                        return await r.json();
                    }""",
                    fetch_with_id,
                )
                if chosen and isinstance(chosen, dict) and (chosen.get("program") or chosen.get("episode")):
                    if debug:
                        _debug_payload(f"fallback fetch with scraped {param} ({name})", chosen)
                    return chosen
            except Exception as e:
                if debug:
                    print(f"  [DEBUG] ({name}) fallback fetch with id failed: {e}", file=sys.stderr)
        if chosen is None:
            try:
                chosen = page.evaluate(
                    """async (url) => {
                        const r = await fetch(url, { credentials: 'same-origin' });
                        if (!r.ok) return null;
                        return await r.json();
                    }""",
                    fetch_url,
                )
            except Exception as e:
                if debug:
                    print(f"  [DEBUG] ({name}) fallback fetch failed: {e}", file=sys.stderr)
        if chosen and isinstance(chosen, dict) and (chosen.get("program") or chosen.get("episode")):
            if debug:
                _debug_payload(f"fallback fetch ({name})", chosen)
            return chosen
        if captured:
            if debug:
                _debug_payload(f"fallback captured ({name})", captured[-1])
            return captured[-1]
        if debug:
            print(f"  [DEBUG] ({name}) no payload, failing", file=sys.stderr)
        return None
    finally:
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 2: export one workout JSON per program via Playwright (one context per token)."
    )
    parser.add_argument("--headed", action="store_true", help="Show browser window (default: headless)")
    parser.add_argument("--debug", action="store_true", help="Log program_id/episode_id per captured response")
    parser.add_argument(
        "--only",
        metavar="NAME",
        help="Only export this program (e.g. --only neck). Matches by slug/name.",
    )
    args = parser.parse_args()
    headed = args.headed or os.getenv("PHASE2_HEADED", "").strip().lower() in ("1", "true", "yes")
    debug = args.debug or os.getenv("PHASE2_DEBUG", "").strip().lower() in ("1", "true", "yes")

    env_path = REPO_ROOT / ".env"
    load_dotenv(env_path, override=True)
    if not env_path.exists():
        load_dotenv()

    user = os.getenv("MB_USER")
    password = os.getenv("MB_PASS")
    mb_tokens_raw = os.getenv("MB_TOKENS")
    single_token = os.getenv("MB_TOKEN")
    name_override = os.getenv("MB_TOKEN_NAME")

    if not mb_tokens_raw and env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip().strip("\r")
                if line.startswith("MB_TOKENS="):
                    mb_tokens_raw = line.split("=", 1)[1].strip().strip('"\'')
                    os.environ["MB_TOKENS"] = mb_tokens_raw
                    break

    if single_token:
        mb_tokens_raw = None
        os.environ.pop("MB_TOKENS", None)

    if not user or not password:
        print("Set MB_USER and MB_PASS in .env (see .env.example)", file=sys.stderr)
        sys.exit(1)

    if mb_tokens_raw:
        token_pairs = _parse_mb_tokens(mb_tokens_raw)
        if not token_pairs:
            print(
                "MB_TOKENS is set but no valid name:code pairs found (e.g. knee:CODE1,elbow:CODE2).",
                file=sys.stderr,
            )
            sys.exit(1)
    elif single_token:
        token_pairs = [(name_override or "workout", single_token)]
    else:
        print("Set MB_TOKENS or MB_TOKEN in .env.", file=sys.stderr)
        sys.exit(1)

    if args.only:
        only_slug = _slug(args.only)
        token_pairs = [(n, c) for n, c in token_pairs if _slug(n) == only_slug]
        if not token_pairs:
            print(f"No program matching --only {args.only!r} (slug: {only_slug!r}).", file=sys.stderr)
            sys.exit(1)
        if debug:
            print(f"[DEBUG] Filtered to --only {args.only!r}: {token_pairs}", file=sys.stderr)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Install Playwright: pip install -r requirements.txt && playwright install",
            file=sys.stderr,
        )
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        try:
            for i, (name, code) in enumerate(token_pairs):
                slug = _slug(name)
                print(f"[{i + 1}/{len(token_pairs)}] {name!r}...")
                api_payload = run_one_program(
                    browser.new_context, user, password, name, code, debug=debug
                )
                if not api_payload:
                    print(f"  Failed to capture workout for {name!r}", file=sys.stderr)
                    sys.exit(1)
                export = build_export_payload(api_payload, program_name_override=name)
                out_path = OUT_DIR / f"workout_{slug}.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(export, f, indent=2, ensure_ascii=False)
                print(f"  Wrote {export['exercise_count']} exercises to {out_path}")
        finally:
            browser.close()

    print("Done. Run python scripts/build_site.py to generate the static site.")


if __name__ == "__main__":
    main()
