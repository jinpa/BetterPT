#!/usr/bin/env python3
"""
Exploratory: probe APIs that might list all workouts after login.

GET /api/v4/plus/episodes/ returns JSON with an episodes array, but in practice
it does not return all workouts (e.g. user may have multiple PT programs but
only one episode appears). Export flow uses access codes (MB_TOKENS) instead.

Run from repo root: python scripts/check_list_workouts_api.py
Uses .env for credentials; does not write secrets to disk.
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

# Endpoints that might return a list of episodes/programs for the patient
CANDIDATES = [
    "/api/v4/lite/episodes/",
    "/api/v4/plus/episodes/",
    "/api/v4/patientsession/session_info",  # sometimes has episode list
    "/api/v3/patients/account",
]


def login_session(user: str, password: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BetterPT-POC/1.0 (read-only aggregation)",
            "Accept": "application/json,text/html,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    r = session.get(f"{BASE}/sign_in", params={"set_sign_in": "true"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", {"id": "patient-signin-form"}) or soup.find("form", action=re.compile(r"sign_in|session"))
    if not form:
        raise RuntimeError("Could not find login form")
    action = urljoin(BASE, form.get("action") or "/sign_in")
    inputs = {inp["name"]: inp.get("value", "") for inp in form.find_all("input", {"name": True})}
    inputs["patient[username]"] = user
    inputs["patient[password]"] = password
    session.post(action, data=inputs, allow_redirects=True).raise_for_status()
    return session


def main() -> None:
    load_dotenv()
    user = os.getenv("MB_USER")
    password = os.getenv("MB_PASS")
    if not user or not password:
        print("Set MB_USER and MB_PASS in .env", file=sys.stderr)
        sys.exit(1)

    print("Logging in...")
    session = login_session(user, password)
    print("Probing list-style endpoints...\n")

    for path in CANDIDATES:
        url = BASE + path
        try:
            r = session.get(url, timeout=15)
            ct = r.headers.get("Content-Type") or ""
            print(f"{r.status_code} {path} [{ct[:40]}]")
            body = r.text
            if "json" in ct:
                try:
                    data = r.json()
                    if isinstance(data, list):
                        print(f"  -> list of {len(data)} item(s)")
                        if data and isinstance(data[0], dict):
                            print(f"  -> first keys: {list(data[0].keys())[:12]}")
                    elif isinstance(data, dict):
                        keys = list(data.keys())
                        print(f"  -> keys: {keys[:20]}")
                        # Hint at episodes/programs
                        for k in ("episodes", "programs", "episode", "program", "account", "patient"):
                            if k in data:
                                v = data[k]
                                if isinstance(v, list):
                                    print(f"  -> {k}: list len {len(v)}")
                                elif isinstance(v, dict):
                                    print(f"  -> {k}: dict keys {list(v.keys())[:10]}")
                except json.JSONDecodeError:
                    print(f"  -> (invalid JSON)")
            # Try to parse as JSON anyway (server may send JSON with wrong Content-Type)
            if r.status_code == 200 and len(body) < 5000:
                try:
                    data = json.loads(body)
                    if isinstance(data, list):
                        print(f"  -> JSON list of {len(data)} item(s)")
                        if data and isinstance(data[0], dict):
                            print(f"  -> first keys: {list(data[0].keys())[:12]}")
                    elif isinstance(data, dict):
                        print(f"  -> JSON keys: {list(data.keys())[:16]}")
                        for k in ("episodes", "programs", "episode", "program"):
                            if k in data:
                                v = data[k]
                                if isinstance(v, list):
                                    print(f"  -> {k}: list len {len(v)}")
                except json.JSONDecodeError:
                    if body.strip().startswith("<"):
                        print(f"  -> HTML response (first 120 chars): {body[:120].replace(chr(10), ' ')}...")
                    else:
                        print(f"  -> body preview: {body[:200]}...")
            # If we found episodes, show first episode keys (no PII)
            if r.status_code == 200:
                try:
                    data = json.loads(body)
                    episodes = data.get("episodes") if isinstance(data, dict) else None
                    if isinstance(episodes, list) and episodes:
                        print(f"  -> First episode keys: {list(episodes[0].keys())}")
                except (json.JSONDecodeError, TypeError):
                    pass
            print()
        except Exception as e:
            print(f"  error: {e}\n")


if __name__ == "__main__":
    main()
