#!/usr/bin/env python3
"""
Export MedBridge Go workout(s) to minimal JSON for the static site.

Usage:
  Set MB_USER, MB_PASS in .env.
  Either:
    - MB_TOKENS=name1:code1,name2:code2  (multiple programs in one run)
    - or MB_TOKEN=code and optional MB_TOKEN_NAME=name (single program)
  Run from repo root: python scripts/export_workout.py

Output:
  scripts/out/workout_<name>.json per program, or workout.json if single and no name.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


BASE = "https://www.medbridgego.com"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"
EPISODE_URL = f"{BASE}/api/v4/plus/episode/episode_with_video_urls"
EPISODES_LIST_URL = f"{BASE}/api/v4/plus/episodes/"


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
    action = urljoin(BASE, form.get("action") or "/sign_in")
    inputs = {inp["name"]: inp.get("value", "") for inp in form.find_all("input", {"name": True})}
    inputs["patient[username]"] = user
    inputs["patient[password]"] = password
    session.post(action, data=inputs, allow_redirects=True).raise_for_status()
    return session


def logout_session(session: requests.Session) -> None:
    """Sign out so the next login gets a clean 'current program' state (matches real-life flow)."""
    r = session.get(f"{BASE}/sign_out", timeout=10)
    # 200 or 302 both mean we're logged out; don't require 200
    if r.status_code not in (200, 302):
        r.raise_for_status()


def re_login(session: requests.Session, user: str, password: str) -> None:
    """Log in again into the same session (after logout, so server clears current program)."""
    r = session.get(f"{BASE}/sign_in", params={"set_sign_in": "true"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", {"id": "patient-signin-form"}) or soup.find("form", action=re.compile(r"sign_in|session"))
    if not form:
        raise RuntimeError("Could not find login form on /sign_in")
    action = urljoin(BASE, form.get("action") or "/sign_in")
    inputs = {inp["name"]: inp.get("value", "") for inp in form.find_all("input", {"name": True})}
    inputs["patient[username]"] = user
    inputs["patient[password]"] = password
    session.post(action, data=inputs, allow_redirects=True).raise_for_status()


def submit_access_code(session: requests.Session, access_code: str) -> tuple[str, int | None]:
    """Submit access code; return (final_url, episode_id from response if any)."""
    r = session.get(f"{BASE}/access_token")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", {"id": "program-access-token"})
    if not form:
        raise RuntimeError("Could not find access code form on /access_token")
    action = urljoin(BASE, form.get("action") or "/register_token")
    inputs = {inp["name"]: inp.get("value", "") for inp in form.find_all("input", {"name": True})}
    inputs["token"] = access_code
    inputs.setdefault("verify_access_code", "Verify Access Code")
    r = session.post(action, data=inputs, allow_redirects=False)
    r.raise_for_status()
    episode_id: int | None = None

    def _int_id(val: object) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    # Response body might be JSON with the activated episode/program id
    ct = (r.headers.get("Content-Type") or "").lower()
    if "json" in ct and r.text.strip():
        try:
            data = r.json()
            if isinstance(data, dict):
                episode_id = _int_id(data.get("episode_id"))
                if episode_id is None:
                    ep = data.get("episode")
                    episode_id = _int_id(ep.get("id") if isinstance(ep, dict) else None)
                if episode_id is None:
                    episode_id = _int_id(data.get("program_id"))
                if episode_id is None:
                    prog = data.get("program")
                    episode_id = _int_id(prog.get("id") if isinstance(prog, dict) else None)
        except (ValueError, TypeError):
            pass
    # Redirect Location might include episode_id in query or fragment
    if episode_id is None and r.status_code in (301, 302, 303, 307, 308):
        loc = r.headers.get("Location") or ""
        if loc:
            parsed = urlparse(loc)
            for part in (parse_qs(parsed.query), parse_qs(parsed.fragment or "")):
                for key in ("episode_id", "episode_id[]", "id"):
                    if key in part and part[key]:
                        episode_id = _int_id(part[key][0])
                        if episode_id is not None:
                            break
                if episode_id is not None:
                    break
    # HTML body might embed episode id (e.g. SPA bootstrap)
    if episode_id is None and r.text.strip().startswith("<"):
        for pattern in (
            re.compile(r'["\']?episode_?id["\']?\s*[:=]\s*["\']?(\d+)'),
            re.compile(r'data-episode-?id=["\'](\d+)["\']'),
        ):
            m = pattern.search(r.text)
            if m:
                episode_id = _int_id(m.group(1))
                break
    # Follow redirects to get final URL
    while r.status_code in (301, 302, 303, 307, 308):
        loc = r.headers.get("Location")
        if not loc:
            break
        next_url = urljoin(r.url, loc)
        r = session.get(next_url, allow_redirects=False, timeout=15)
        r.raise_for_status()
    return (r.url, episode_id)


def _normalize_exercise(pe: dict) -> dict:
    """Build a minimal exercise object: name, description, sets, reps, hold, and raw attributes."""
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


def get_current_episode_id(session: requests.Session) -> int | None:
    """Episodes list returns the current program's episode. Use its id when exactly one (for single-token flow)."""
    r = session.get(EPISODES_LIST_URL, headers={"Accept": "application/json"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    episodes = data.get("episodes") if isinstance(data, dict) else None
    if isinstance(episodes, list) and len(episodes) == 1:
        ep = episodes[0]
        if isinstance(ep, dict) and ep.get("id") is not None:
            return ep["id"]
    return None


def fetch_workout_json(session: requests.Session, episode_id: int | None = None) -> dict:
    url = EPISODE_URL
    if episode_id is not None:
        url = f"{EPISODE_URL}?{urlencode({'episode_id': episode_id})}"
    r = session.get(url, headers={"Accept": "application/json"}, timeout=20)
    r.raise_for_status()
    return r.json()


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


def build_export_payload(api_payload: dict, program_name_override: str | None = None) -> dict:
    """Convert API response to minimal JSON for static site."""
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


def main() -> None:
    env_path = REPO_ROOT / ".env"
    load_dotenv(env_path, override=True)
    if not env_path.exists():
        load_dotenv()  # fallback: cwd
    user = os.getenv("MB_USER")
    password = os.getenv("MB_PASS")
    mb_tokens_raw = os.getenv("MB_TOKENS")
    single_token = os.getenv("MB_TOKEN")
    name_override = os.getenv("MB_TOKEN_NAME")
    out_path_override = os.getenv("WORKOUT_JSON_PATH")

    # Fallback: dotenv can miss MB_TOKENS (e.g. encoding/parsing); read .env directly
    if not mb_tokens_raw and env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip().strip("\r")
                if line.startswith("MB_TOKENS="):
                    mb_tokens_raw = line.split("=", 1)[1].strip().strip('"\'')
                    os.environ["MB_TOKENS"] = mb_tokens_raw
                    break

    # When invoked as subprocess with MB_TOKEN/MB_TOKEN_NAME, force single-token path (ignore MB_TOKENS from .env)
    if single_token:
        mb_tokens_raw = None
        os.environ.pop("MB_TOKENS", None)

    # DEBUG: remove once multi-program export is confirmed working
    print(
        f"DEBUG: .env path={env_path!s} exists={env_path.exists()}, "
        f"MB_TOKENS={'set' if mb_tokens_raw else 'unset'}"
        + (f" ({len(mb_tokens_raw)} chars)" if mb_tokens_raw else ""),
        file=sys.stderr,
    )

    if not user or not password:
        print("Set MB_USER and MB_PASS in .env (see .env.example)", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if mb_tokens_raw:
        # Multiple programs: run one subprocess per token so each has a truly isolated session (MedBridge returns first/default program otherwise)
        pairs = _parse_mb_tokens(mb_tokens_raw)
        if not pairs:
            print("MB_TOKENS is set but no valid name:code pairs found (e.g. knee:CODE1,elbow:CODE2)", file=sys.stderr)
            sys.exit(1)
        script_path = Path(__file__).resolve()
        for i, (name, code) in enumerate(pairs):
            print(f"[{i + 1}/{len(pairs)}] {name!r}...")
            child_env = {**os.environ, "MB_TOKEN": code, "MB_TOKEN_NAME": name}
            child_env.pop("MB_TOKENS", None)
            result = subprocess.run(
                [sys.executable, str(script_path)],
                env=child_env,
                cwd=str(REPO_ROOT),
            )
            if result.returncode != 0:
                print(f"  Subprocess for {name!r} exited with {result.returncode}", file=sys.stderr)
                sys.exit(result.returncode)
            print(f"  Wrote workout_{_slug(name)}.json")
        return

    # Single program (legacy)
    if out_path_override:
        out_path = Path(out_path_override)
    else:
        if name_override:
            out_path = OUT_DIR / f"workout_{_slug(name_override)}.json"
        else:
            out_path = OUT_DIR / "workout.json"

    print("Logging in...")
    session = login_session(user, password)

    if single_token:
        print("Submitting access code...")
        final_url, episode_id_from_token = submit_access_code(session, single_token)
        session.get(final_url, timeout=15).raise_for_status()
        # Prefer episode id from register_token response so we get this program, not account default
        episode_id = episode_id_from_token or get_current_episode_id(session)
        if episode_id_from_token is not None:
            print(f"  Using episode_id={episode_id_from_token} from token response", file=sys.stderr)
    else:
        print("MB_TOKEN not set; using current session program (if any).")
        episode_id = None

    print("Fetching workout (episode_with_video_urls)...")
    api_payload = fetch_workout_json(session, episode_id=episode_id)
    export = build_export_payload(api_payload, program_name_override=name_override)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    print(f"Wrote {export['exercise_count']} exercises to {out_path}")
    print(f"  program_name: {export['program_name']!r}")


if __name__ == "__main__":
    main()
