#!/usr/bin/env python3
"""
Discover which API endpoints the MedBridge Go Patient Portal SPA calls.

This script:
1) Logs in using MB_USER / MB_PASS from .env
2) Optionally submits MB_TOKEN (access code) via /access_token -> POST /register_token
3) Fetches the Home Program SPA shell (GET /) and extracts:
   - JWT (kept in-memory only; never written to disk)
   - main JS bundle URL (main-es2015*.js)
4) Downloads the main bundle and extracts any hard-coded API URLs.
5) Probes a small set of candidate endpoints with Authorization: Bearer <jwt>

Outputs:
- scripts/out/api_discovery.txt
- scripts/out/main_bundle.js (ignored by git via scripts/out/)
"""

from __future__ import annotations

import os
import re
import sys
import time
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


BASE = "https://www.medbridgego.com"
OUT_DIR = Path(__file__).resolve().parent / "out"

JWT_RE = re.compile(r'window\.jwt\s*=\s*"([^"]+)"')
MAIN_BUNDLE_RE = re.compile(r"https?://[^\"']+/patient-portal/[^\"']+/main-es2015\.[^\"']+\.js")
MB_CONFIG_RE = re.compile(r"window\.mb_config\s*=\s*({.*?});", re.DOTALL)
QUOTED_PATH_RE = re.compile(r"['\"](\/[A-Za-z0-9][^'\"]{1,180})['\"]")


def extract_mb_config(home_html: str) -> dict:
    m = MB_CONFIG_RE.search(home_html)
    if not m:
        raise RuntimeError("Could not find window.mb_config in home HTML.")
    raw = m.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse mb_config JSON: {e}") from e


def extract_base_urls(mb_config: dict) -> list[str]:
    urls = mb_config.get("env", {}).get("urls", {})
    if not isinstance(urls, dict):
        return [BASE]
    base_urls: list[str] = [BASE]
    for v in urls.values():
        if isinstance(v, str) and v.startswith("http"):
            base_urls.append(v)
    # de-dupe, stable-ish
    seen: set[str] = set()
    out: list[str] = []
    for u in base_urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def extract_candidate_paths(bundle_text: str) -> list[str]:
    paths = [m.group(1) for m in QUOTED_PATH_RE.finditer(bundle_text)]
    # Filter obvious noise
    keep_keywords = ("api", "patient", "portal", "program", "home", "exercise", "workout", "assign", "plan")
    out: list[str] = []
    for p in paths:
        p_l = p.lower()
        if any(p_l.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".js", ".ico", ".woff", ".woff2", ".ttf")):
            continue
        if len(p) < 4:
            continue
        if any(k in p_l for k in keep_keywords):
            out.append(p)
    return sorted(set(out))


@dataclass(frozen=True)
class ProbeResult:
    url: str
    status: int | None
    content_type: str | None
    note: str


def login_session(user: str, password: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BetterPT-POC/1.0 (read-only aggregation)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    r = session.get(f"{BASE}/sign_in", params={"set_sign_in": "true"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", {"id": "patient-signin-form"}) or soup.find("form", action=re.compile(r"sign_in|session"))
    if not form:
        raise RuntimeError("Could not find login form on /sign_in")

    action = form.get("action") or "/sign_in"
    action_url = urljoin(BASE, action)

    inputs = {inp["name"]: inp.get("value", "") for inp in form.find_all("input", {"name": True})}
    # Confirmed field names
    inputs["patient[username]"] = user
    inputs["patient[password]"] = password

    r2 = session.post(action_url, data=inputs, allow_redirects=True)
    r2.raise_for_status()
    return session


def submit_access_code(session: requests.Session, access_code: str) -> None:
    r = session.get(f"{BASE}/access_token")
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", {"id": "program-access-token"})
    if not form:
        raise RuntimeError("Could not find access code form on /access_token")

    action = form.get("action") or "/register_token"
    action_url = urljoin(BASE, action)

    inputs = {inp["name"]: inp.get("value", "") for inp in form.find_all("input", {"name": True})}
    inputs["token"] = access_code
    # keep submit name if present
    inputs.setdefault("verify_access_code", "Verify Access Code")

    r2 = session.post(action_url, data=inputs, allow_redirects=True)
    r2.raise_for_status()


def fetch_home_html(session: requests.Session) -> str:
    r = session.get(f"{BASE}/")
    r.raise_for_status()
    return r.text


def extract_jwt(home_html: str) -> str:
    m = JWT_RE.search(home_html)
    if not m:
        raise RuntimeError("Could not find window.jwt in home HTML; are you logged in?")
    return m.group(1)


def extract_main_bundle_url(home_html: str) -> str:
    # First try HTML parsing
    soup = BeautifulSoup(home_html, "html.parser")
    scripts = [s.get("src") for s in soup.find_all("script") if s.get("src")]
    for src in scripts:
        if "main-es2015" in src and src.endswith(".js"):
            return src

    # Fallback regex in raw HTML
    m = MAIN_BUNDLE_RE.search(home_html)
    if not m:
        raise RuntimeError("Could not locate main-es2015*.js URL in home HTML.")
    return m.group(0)


def download_text(url: str, session: requests.Session | None = None) -> str:
    s = session or requests.Session()
    r = s.get(url)
    r.raise_for_status()
    return r.text


def choose_probe_candidates(urls: list[str], limit: int = 15) -> list[str]:
    def score(u: str) -> int:
        u_l = u.lower()
        points = 0
        for kw, p in [
            ("patient", 5),
            ("portal", 5),
            ("program", 4),
            ("home", 3),
            ("exercise", 2),
            ("workout", 4),
            ("assignment", 3),
            ("plan", 2),
        ]:
            if kw in u_l:
                points += p
        # Prefer URLs that look like API endpoints, not static assets
        if u_l.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".js")):
            points -= 10
        return points

    ranked = sorted(set(urls), key=score, reverse=True)
    return ranked[:limit]


def probe_with_session(session: requests.Session, urls: list[str]) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "User-Agent": "BetterPT-POC/1.0 (read-only aggregation)",
    }

    for u in urls:
        try:
            r = session.get(u, headers=headers, timeout=20, allow_redirects=True)
            ct = r.headers.get("Content-Type")
            note = ""
            # keep output tiny and non-sensitive: don't dump response bodies
            if r.status_code == 401:
                note = "unauthorized"
            elif r.status_code == 403:
                note = "forbidden"
            elif r.status_code == 404:
                note = "not found"
            elif 200 <= r.status_code < 300:
                note = "ok"
            else:
                note = "unexpected"
            results.append(ProbeResult(url=u, status=r.status_code, content_type=ct, note=note))
        except Exception as e:  # noqa: BLE001 - exploratory tooling
            results.append(ProbeResult(url=u, status=None, content_type=None, note=f"error: {type(e).__name__}"))
        time.sleep(0.25)

    return results


def probe_json(jwt: str, urls: list[str]) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Accept": "application/json,text/plain,*/*",
        "User-Agent": "BetterPT-POC/1.0 (read-only aggregation)",
    }

    for u in urls:
        try:
            r = requests.get(u, headers=headers, timeout=20, allow_redirects=True)
            ct = r.headers.get("Content-Type")
            note = ""
            # keep output tiny and non-sensitive: don't dump response bodies
            if r.status_code == 401:
                note = "unauthorized (JWT not accepted or wrong service)"
            elif r.status_code == 403:
                note = "forbidden"
            elif r.status_code == 404:
                note = "not found"
            elif 200 <= r.status_code < 300:
                note = "ok"
            else:
                note = "unexpected"
            results.append(ProbeResult(url=u, status=r.status_code, content_type=ct, note=note))
        except Exception as e:  # noqa: BLE001 - exploratory tooling
            results.append(ProbeResult(url=u, status=None, content_type=None, note=f"error: {type(e).__name__}"))
        time.sleep(0.25)
    return results


def main() -> None:
    load_dotenv()
    user = os.getenv("MB_USER")
    password = os.getenv("MB_PASS")
    access_code = os.getenv("MB_TOKEN")
    if not user or not password:
        print("Set MB_USER and MB_PASS in .env (see .env.example)", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Logging in...")
    session = login_session(user, password)

    if access_code:
        print("Submitting access code...")
        submit_access_code(session, access_code)
    else:
        print("MB_TOKEN not set; skipping access code submission.")

    print("Fetching home HTML...")
    home_html = fetch_home_html(session)
    jwt = extract_jwt(home_html)
    main_bundle_url = extract_main_bundle_url(home_html)
    mb_config = extract_mb_config(home_html)
    base_urls = extract_base_urls(mb_config)

    print("Downloading main JS bundle (this can be large)...")
    bundle_text = download_text(main_bundle_url)
    (OUT_DIR / "main_bundle.js").write_text(bundle_text, encoding="utf-8")
    print(f"  -> saved main_bundle.js ({len(bundle_text)} chars)")

    candidate_paths = extract_candidate_paths(bundle_text)
    # Primary hypothesis: SPA calls same-origin endpoints authenticated via cookies.
    same_origin_candidates = [urljoin(BASE if BASE.endswith("/") else BASE + "/", p.lstrip("/")) for p in candidate_paths]
    same_origin_top = choose_probe_candidates(same_origin_candidates, limit=15)
    probe_results_cookie = probe_with_session(session, same_origin_top)

    # Secondary hypothesis: some calls hit the ambassador API with Bearer JWT.
    ambassador_base = mb_config.get("env", {}).get("urls", {}).get("ambassador", "https://api.medbridgeeducation.com/")
    bearer_candidates = [urljoin(ambassador_base if ambassador_base.endswith("/") else ambassador_base + "/", p.lstrip("/")) for p in candidate_paths]
    bearer_top = choose_probe_candidates(bearer_candidates, limit=15)
    probe_results_bearer = probe_json(jwt, bearer_top)

    # High-signal endpoint: current episode + program + program_exercises
    episode_url = f"{BASE}/api/v4/plus/episode/episode_with_video_urls"
    episode_summary: str | None = None
    try:
        r_ep = session.get(episode_url, headers={"Accept": "application/json"}, timeout=20)
        ct_ep = r_ep.headers.get("Content-Type") or ""
        if r_ep.ok and "application/json" in ct_ep:
            payload = r_ep.json()
            program = payload.get("program") if isinstance(payload, dict) else None
            exercises = program.get("program_exercises") if isinstance(program, dict) else None
            program_id = program.get("id") if isinstance(program, dict) else None
            episode_name = (payload.get("episode") or {}).get("name") if isinstance(payload, dict) else None
            exercise_count = len(exercises) if isinstance(exercises, list) else None
            episode_summary = f"status=200 program_id={program_id} exercises={exercise_count} episode_name={episode_name!r}"
        else:
            episode_summary = f"status={r_ep.status_code} ct={ct_ep}"
    except Exception as e:  # noqa: BLE001 - exploratory tooling
        episode_summary = f"error {type(e).__name__}"

    out = OUT_DIR / "api_discovery.txt"
    lines: list[str] = []
    lines.append("BetterPT API discovery (redacted)\n")
    lines.append(f"- Base site: {BASE}\n")
    lines.append(f"- Bundle: {main_bundle_url}\n")
    lines.append(f"- Found {len(candidate_paths)} candidate URL paths in bundle\n")
    lines.append(f"- Base URLs from mb_config: {len(base_urls)} (not all are API hosts)\n")
    lines.append(f"- Probing same-origin with session cookies: {BASE}\n")
    lines.append(f"- Probing bearer against ambassador base: {ambassador_base}\n")

    lines.append("\nTop candidate endpoints (same-origin, session cookies):\n")
    for pr in probe_results_cookie:
        lines.append(f"- {pr.status if pr.status is not None else 'ERR'} {pr.url} [{pr.content_type or 'no-ct'}] ({pr.note})\n")

    lines.append("\nTop candidate endpoints (Bearer JWT, ambassador base):\n")
    for pr in probe_results_bearer:
        lines.append(f"- {pr.status if pr.status is not None else 'ERR'} {pr.url} [{pr.content_type or 'no-ct'}] ({pr.note})\n")

    lines.append("\nHigh-signal payload check:\n")
    lines.append(f"- {episode_url}\n")
    if episode_summary:
        lines.append(f"  - {episode_summary}\n")
    lines.append("\nNote: JWT was used in-memory only and not written to disk.\n")
    out.write_text("".join(lines), encoding="utf-8")
    print(f"  -> wrote {out}")

    print("\nNext: open scripts/out/api_discovery.txt and we’ll pick the right endpoint(s) for workouts.")


if __name__ == "__main__":
    main()

