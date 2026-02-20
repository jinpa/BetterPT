#!/usr/bin/env python3
"""
Phase 1 debug script: login + token(s), record network/redirects/storage to discover
how MedBridge sets "current program".

Usage:
  Set MB_USER, MB_PASS in .env. Either MB_TOKENS=name1:code1,name2:code2 or
  MB_TOKEN=code and optional MB_TOKEN_NAME=name.
  Run from repo root: python scripts/phase1_debug_network.py
  Optional: --headed or PHASE1_HEADED=1 to show the browser (default headless).
  Requires browser binaries: playwright install (one-time after pip install -r requirements.txt).

Outputs (all under scripts/out/, redacted):
  phase1_network_log.json   - captured API/navigation requests and responses
  phase1_redirects.json     - redirect chains for login and each token
  phase1_storage_after_login.json, phase1_storage_after_token_<slug>.json - storage snapshots
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"
BASE = "https://www.medbridgego.com"

# URL substrings we care about for network log
NETWORK_URL_FILTER = ("api", "episode", "register_token", "sign_in", "access_token")

# Sensitive keys/headers to redact
REDACT_HEADERS = ("authorization", "cookie", "set-cookie", "x-csrf-token")
REDACT_KEYS = ("jwt", "csrf", "token", "cookie", "authorization", "password", "session")


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


def _should_log_url(url: str) -> bool:
    return any(sub in url for sub in NETWORK_URL_FILTER)


def _redact_value(val: str) -> str:
    if not val or not isinstance(val, str):
        return val
    if len(val) > 20 or any(
        x in val.lower() for x in ("bearer", "csrf", "session", "jwt", "token=")
    ):
        return "<REDACTED>"
    return val


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (headers or {}).items():
        key_lower = k.lower()
        if any(r in key_lower for r in REDACT_HEADERS):
            out[k] = "<REDACTED>"
        else:
            out[k] = _redact_value(v) if key_lower in ("authorization", "cookie") else v
    return out


def redact_obj(obj: object) -> object:
    """Recursively redact sensitive keys in dicts/lists; return copy."""
    if isinstance(obj, dict):
        return {
            k: "<REDACTED>" if any(r in k.lower() for r in REDACT_KEYS) else redact_obj(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_obj(i) for i in obj]
    if isinstance(obj, str) and (
        "token" in obj.lower() or "jwt" in obj or "bearer" in obj.lower()
    ):
        return "<REDACTED>"
    return obj


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1: record network/redirects/storage for MedBridge Go.")
    parser.add_argument("--headed", action="store_true", help="Show browser window (default: headless)")
    args = parser.parse_args()
    headed = args.headed or os.getenv("PHASE1_HEADED", "").strip().lower() in ("1", "true", "yes")

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
            print("MB_TOKENS is set but no valid name:code pairs found.", file=sys.stderr)
            sys.exit(1)
    elif single_token:
        slug = _slug(name_override or "single")
        token_pairs = [(name_override or "single", single_token)]
    else:
        token_pairs = []

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install Playwright: pip install -r requirements.txt && playwright install", file=sys.stderr)
        sys.exit(1)

    network_entries: list[dict] = []
    redirect_chains: list[dict] = []
    current_phase: str | None = None
    current_chain: list[str] = []

    def on_response(response):
        nonlocal current_phase, current_chain
        req = response.request
        url = req.url
        if not _should_log_url(url):
            return
        try:
            status = response.status
            res_headers = dict(response.headers)
            req_headers = dict(req.headers)
            entry = {
                "url": url,
                "method": req.method,
                "status": status,
                "resource_type": req.resource_type,
                "request_headers": redact_headers(req_headers),
                "response_headers": redact_headers(res_headers),
                "phase": current_phase,
            }
            if req.resource_type == "document" and status in (301, 302, 303, 307, 308):
                loc = response.headers.get("location")
                if loc:
                    current_chain.append(url)
                    if not url.startswith("http"):
                        pass  # relative; next request will have full url
            elif req.resource_type == "document" and current_phase and current_chain:
                current_chain.append(url)
                redirect_chains.append({"label": current_phase, "chain": list(current_chain)})
                current_chain.clear()
                current_phase = None

            ct = (res_headers.get("content-type") or "").lower()
            if "json" in ct and status == 200:
                try:
                    body = response.body()
                    if body:
                        data = json.loads(body.decode("utf-8", errors="replace"))
                        entry["response_body_summary"] = redact_obj(_body_summary(data))
                except Exception:
                    entry["response_body_summary"] = "<non-JSON or error>"
            network_entries.append(entry)
        except Exception as e:
            network_entries.append({"url": url, "error": str(e), "phase": current_phase})

    def _body_summary(data: dict) -> dict:
        """Extract program/episode ids and minimal keys for findings."""
        out: dict = {}
        if isinstance(data, dict):
            for key in ("program", "episode", "program_id", "episode_id", "episodes"):
                if key in data:
                    v = data[key]
                    if isinstance(v, dict) and "id" in v:
                        out[key] = {"id": v.get("id")}
                    elif isinstance(v, list) and v and isinstance(v[0], dict):
                        out[key] = [{"id": x.get("id")} for x in v[:5]]
                    else:
                        out[key] = v
        return out or data

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context()
        context.on("response", on_response)
        page = context.new_page()

        # Login
        print("Navigating to sign_in...")
        page.goto(f"{BASE}/sign_in", wait_until="domcontentloaded")
        page.fill('input[name="patient[username]"]', user)
        page.fill('input[name="patient[password]"]', password)
        current_phase = "login"
        current_chain.clear()
        page.click('form#patient-signin-form button[type="submit"], form[action*="sign_in"] button[type="submit"], input[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=15000)
        if current_phase and current_chain:
            redirect_chains.append({"label": current_phase, "chain": list(current_chain)})
            current_chain.clear()
        current_phase = None
        print("Logged in.")

        # Storage snapshot after login
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            state_path = tf.name
        try:
            context.storage_state(path=state_path)
            with open(state_path, encoding="utf-8") as f:
                storage_after_login = json.load(f)
            storage_after_login = redact_obj(storage_after_login)
            with open(OUT_DIR / "phase1_storage_after_login.json", "w", encoding="utf-8") as f:
                json.dump(storage_after_login, f, indent=2)
        finally:
            Path(state_path).unlink(missing_ok=True)

        if not token_pairs:
            print("No MB_TOKEN/MB_TOKENS set; skipping access code submission.")
        else:
            for i, (name, code) in enumerate(token_pairs):
                slug = _slug(name)
                print(f"Submitting token for {name!r}...")
                page.goto(f"{BASE}/access_token", wait_until="domcontentloaded")
                page.fill('input[name="token"]', code)
                current_phase = f"token_{slug}"
                current_chain.clear()
                page.click('form#program-access-token button[type="submit"], form#program-access-token input[type="submit"], form[action*="register_token"] input[type="submit"]')
                page.wait_for_load_state("networkidle", timeout=15000)
                if current_phase and current_chain:
                    redirect_chains.append({"label": current_phase, "chain": list(current_chain)})
                    current_chain.clear()
                current_phase = None
                page.wait_for_timeout(2000)

                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
                    state_path = tf.name
                try:
                    context.storage_state(path=state_path)
                    with open(state_path, encoding="utf-8") as f:
                        storage = json.load(f)
                    storage = redact_obj(storage)
                    with open(OUT_DIR / f"phase1_storage_after_token_{slug}.json", "w", encoding="utf-8") as f:
                        json.dump(storage, f, indent=2)
                finally:
                    Path(state_path).unlink(missing_ok=True)

        browser.close()

    with open(OUT_DIR / "phase1_network_log.json", "w", encoding="utf-8") as f:
        json.dump(network_entries, f, indent=2)
    with open(OUT_DIR / "phase1_redirects.json", "w", encoding="utf-8") as f:
        json.dump(redirect_chains, f, indent=2)

    print(f"Wrote phase1_network_log.json ({len(network_entries)} entries)")
    print(f"Wrote phase1_redirects.json ({len(redirect_chains)} chains)")
    print(f"Wrote phase1_storage_after_login.json and phase1_storage_after_token_*.json")
    print("Inspect scripts/out/ and document findings in docs/PHASE1_FINDINGS.md")


if __name__ == "__main__":
    main()
