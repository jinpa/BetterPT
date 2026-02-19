#!/usr/bin/env python3
"""
Export current MedBridge Go workout to a minimal JSON file for the static site.

Usage:
  Set MB_USER, MB_PASS in .env. Optionally set MB_TOKEN (access code) and MB_TOKEN_NAME (e.g. "knee").
  Run from repo root: python scripts/export_workout.py

Output:
  scripts/out/workout.json (or path from env WORKOUT_JSON_PATH)
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
    access_code = os.getenv("MB_TOKEN")
    name_override = os.getenv("MB_TOKEN_NAME")
    out_path = os.getenv("WORKOUT_JSON_PATH") or str(OUT_DIR / "workout.json")

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
        print("MB_TOKEN not set; using current session program (if any).")

    print("Fetching workout (episode_with_video_urls)...")
    api_payload = fetch_workout_json(session)
    export = build_export_payload(api_payload, program_name_override=name_override)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    print(f"Wrote {export['exercise_count']} exercises to {out_path}")
    print(f"  program_name: {export['program_name']!r}")


if __name__ == "__main__":
    main()
