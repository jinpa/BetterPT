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
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


BASE = "https://www.medbridgego.com"
OUT_DIR = Path(__file__).resolve().parent / "out"
EPISODE_URL = f"{BASE}/api/v4/plus/episode/episode_with_video_urls"


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


def submit_access_code(session: requests.Session, access_code: str) -> None:
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
    session.post(action, data=inputs, allow_redirects=True).raise_for_status()


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


def fetch_workout_json(session: requests.Session) -> dict:
    r = session.get(EPISODE_URL, headers={"Accept": "application/json"}, timeout=20)
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
    load_dotenv()
    user = os.getenv("MB_USER")
    password = os.getenv("MB_PASS")
    mb_tokens_raw = os.getenv("MB_TOKENS")
    single_token = os.getenv("MB_TOKEN")
    name_override = os.getenv("MB_TOKEN_NAME")
    out_path_override = os.getenv("WORKOUT_JSON_PATH")

    if not user or not password:
        print("Set MB_USER and MB_PASS in .env (see .env.example)", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if mb_tokens_raw:
        # Multiple programs: name1:code1,name2:code2
        pairs = _parse_mb_tokens(mb_tokens_raw)
        if not pairs:
            print("MB_TOKENS is set but no valid name:code pairs found (e.g. knee:CODE1,elbow:CODE2)", file=sys.stderr)
            sys.exit(1)
        for i, (name, code) in enumerate(pairs):
            print(f"[{i + 1}/{len(pairs)}] {name!r}...")
            session = login_session(user, password)
            submit_access_code(session, code)
            api_payload = fetch_workout_json(session)
            export = build_export_payload(api_payload, program_name_override=name)
            out_path = OUT_DIR / f"workout_{_slug(name)}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(export, f, indent=2, ensure_ascii=False)
            print(f"  Wrote {export['exercise_count']} exercises to {out_path}")
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
        submit_access_code(session, single_token)
    else:
        print("MB_TOKEN not set; using current session program (if any).")

    print("Fetching workout (episode_with_video_urls)...")
    api_payload = fetch_workout_json(session)
    export = build_export_payload(api_payload, program_name_override=name_override)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    print(f"Wrote {export['exercise_count']} exercises to {out_path}")
    print(f"  program_name: {export['program_name']!r}")


if __name__ == "__main__":
    main()
