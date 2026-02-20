#!/usr/bin/env python3
"""
Convert a raw episode_with_video_urls API response (pasted from browser Network tab)
into workout_<slug>.json so build_site.py can use it.

Use when you open a program URL in the browser (e.g. medbridgego.com/access_token/CODE),
copy the JSON from the episode_with_video_urls response, save to a file, then run this.

Usage:
  python scripts/from_api_response.py path/to/api_response.json --name neck
  # Writes scripts/out/workout_neck.json

  python scripts/from_api_response.py neck_api_response.json
  # Uses filename stem as name (neck_api_response -> "neck_api_response"); prefer --name.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"


def _slug(name: str) -> str:
    safe = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[-\s]+", "-", safe).strip("-") or "workout"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert raw episode_with_video_urls JSON to workout_<slug>.json"
    )
    parser.add_argument("json_file", type=Path, help="Path to the raw API response JSON file")
    parser.add_argument(
        "--name",
        default=None,
        help="Program name for the workout (e.g. neck). Default: stem of json_file.",
    )
    args = parser.parse_args()

    path = args.json_file
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        api_payload = json.load(f)

    if not isinstance(api_payload, dict) or not (api_payload.get("program") or api_payload.get("episode")):
        print("JSON does not look like an episode_with_video_urls response (need program or episode).", file=sys.stderr)
        sys.exit(1)

    name = args.name or path.stem
    slug = _slug(name)

    # Reuse Phase 2 conversion (same schema as export_workout / build_site).
    from phase2_export_playwright import build_export_payload

    export = build_export_payload(api_payload, program_name_override=name)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"workout_{slug}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    print(f"Wrote {export['exercise_count']} exercises to {out_path}")
    print("Run python scripts/build_site.py to regenerate the static site.")


if __name__ == "__main__":
    main()
