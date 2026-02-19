#!/usr/bin/env python3
"""
Minimal scrape of MedBridge Go without Playwright: login with .env credentials,
then fetch a few pages and save the raw responses so we can see what we get.
Run from repo root: python scripts/simple_scrape.py
"""
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup

BASE = "https://www.medbridgego.com"
OUT_DIR = Path(__file__).resolve().parent / "out"

_JWT_RE = re.compile(r'(window\.jwt\s*=\s*")[^"]+(";)')
_CSRF_RE = re.compile(r"((?:name|id)=['\"]X-CSRF-Token['\"][^>]*value=['\"])[^'\"]+(['\"])")


def _redact_html_secrets(html: str) -> str:
    # Avoid writing bearer-like tokens to disk.
    html = _JWT_RE.sub(r'\1<REDACTED>\2', html)
    html = _CSRF_RE.sub(r"\1<REDACTED>\2", html)
    return html


def main() -> None:
    load_dotenv()
    user = os.getenv("MB_USER")
    password = os.getenv("MB_PASS")
    access_code = os.getenv("MB_TOKEN")
    if not user or not password:
        print("Set MB_USER and MB_PASS in .env (see .env.example)", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "BetterPT-POC/1.0 (read-only aggregation)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    # 1) GET sign-in page (cookies + discover form)
    print("GET sign_in...")
    r = session.get(f"{BASE}/sign_in", params={"set_sign_in": "true"})
    r.raise_for_status()
    (OUT_DIR / "01_sign_in.html").write_text(_redact_html_secrets(r.text), encoding="utf-8")
    print(f"  -> saved 01_sign_in.html ({len(r.text)} bytes)")

    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form", action=re.compile(r"sign_in|session"))
    if not form:
        form = soup.find("form")
    if not form:
        print("  No form found in sign_in page; login might be JS-only.")
        print("  Check 01_sign_in.html and scripts/out/ for what we got.")
        return

    action = form.get("action") or "/sign_in"
    if action.startswith("/"):
        action = BASE + action
    inputs = {inp["name"]: inp.get("value", "") for inp in form.find_all("input", {"name": True})}
    # MedBridge Go uses patient[username] and patient[password]
    key_user = next(
        (k for k in inputs if k in ("patient[username]", "user[login]", "username") or "username" in k or "login" in k),
        None,
    )
    key_pass = next((k for k in inputs if "password" in k.lower()), None)
    if not key_user or not key_pass:
        print("  Form input names:", list(inputs.keys()))
        key_user = key_user or "patient[username]"
        key_pass = key_pass or "patient[password]"
    inputs[key_user] = user
    inputs[key_pass] = password

    # 2) POST login
    print("POST login...")
    r2 = session.post(action, data=inputs, allow_redirects=True)
    (OUT_DIR / "02_after_login.html").write_text(_redact_html_secrets(r2.text), encoding="utf-8")
    print(f"  -> saved 02_after_login.html ({len(r2.text)} bytes)")

    if "sign in" in r2.text.lower() and "sign out" not in r2.text.lower():
        print("  Page still shows sign-in; login may have failed (wrong creds or JS-only auth).")
    elif "sign out" in r2.text.lower() or "Welcome" in r2.text:
        print("  Looks like we're in (sign out / Welcome present).")
    else:
        print("  Unclear; inspect 02_after_login.html")

    # 3) GET home / dashboard
    print("GET / ...")
    r3_home = session.get(f"{BASE}/")
    r3_home.raise_for_status()
    (OUT_DIR / "03_home.html").write_text(_redact_html_secrets(r3_home.text), encoding="utf-8")
    print(f"  -> saved 03_home.html ({len(r3_home.text)} bytes)")

    print("GET /access_token ...")
    r3_access = session.get(f"{BASE}/access_token")
    r3_access.raise_for_status()
    (OUT_DIR / "03_access_token_page.html").write_text(_redact_html_secrets(r3_access.text), encoding="utf-8")
    print(f"  -> saved 03_access_token_page.html ({len(r3_access.text)} bytes)")

    # 4) If provided, submit an access code (token) to register_token
    if access_code:
        soup_access = BeautifulSoup(r3_access.text, "html.parser")
        form_access = soup_access.find("form", {"id": "program-access-token"}) or soup_access.find(
            "form", action=re.compile(r"register_token")
        )
        if not form_access:
            print("  Could not find access code form on /access_token; inspect 03_access_token_page.html")
        else:
            action_access = form_access.get("action") or "/register_token"
            if action_access.startswith("/"):
                action_access = BASE + action_access

            access_inputs = {
                inp["name"]: inp.get("value", "")
                for inp in form_access.find_all("input", {"name": True})
            }
            # The code input is named "token"
            access_inputs["token"] = access_code
            # Some forms include a submit input name; keep it if present, otherwise provide a safe default
            access_inputs.setdefault("verify_access_code", "Verify Access Code")

            print("POST /register_token ...")
            r4 = session.post(action_access, data=access_inputs, allow_redirects=True)
            (OUT_DIR / "04_after_register_token.html").write_text(_redact_html_secrets(r4.text), encoding="utf-8")
            print(f"  -> saved 04_after_register_token.html ({len(r4.text)} bytes)")

            print("GET / (after access code) ...")
            r5_home = session.get(f"{BASE}/")
            r5_home.raise_for_status()
            (OUT_DIR / "05_home_after_token.html").write_text(_redact_html_secrets(r5_home.text), encoding="utf-8")
            print(f"  -> saved 05_home_after_token.html ({len(r5_home.text)} bytes)")
    else:
        print("MB_TOKEN not set; skipping access code submission.")

    print(f"\nDone. Inspect files in {OUT_DIR}")


if __name__ == "__main__":
    main()
