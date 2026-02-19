#!/usr/bin/env python3
"""
Generate a static site from workout JSON file(s).

Reads all scripts/out/workout*.json (or paths from WORKOUT_JSON_DIR / WORKOUT_JSON_GLOB),
produces dist/index.html and dist/<slug>.html for each program.

Run from repo root: python scripts/build_site.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "scripts" / "out"
DIST_DIR = REPO_ROOT / "dist"


def slug(s: str) -> str:
    """URL-safe slug from program name."""
    s = re.sub(r"[^\w\s-]", "", s.lower())
    return re.sub(r"[-\s]+", "-", s).strip("-") or "workout"


def load_workout_paths() -> list[tuple[str, Path]]:
    """Discover workout JSON files; return list of (slug_or_name, path)."""
    paths = list(OUT_DIR.glob("workout*.json"))
    if not paths:
        # Single file from env or default
        custom = os.getenv("WORKOUT_JSON_PATH")
        if custom and Path(custom).exists():
            p = Path(custom)
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            return [(slug(data.get("program_name", "workout")), p)]
        return []
    result = []
    for p in sorted(paths):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("program_name") or p.stem
            result.append((slug(name), p))
        except (json.JSONDecodeError, OSError):
            continue
    return result


def load_workout(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_dosage(ex: dict) -> str:
    parts = []
    if ex.get("sets") is not None:
        parts.append(f"{ex['sets']} set(s)")
    if ex.get("reps") is not None:
        parts.append(f"{ex['reps']} rep(s)")
    if ex.get("hold") is not None:
        parts.append(f"hold {ex['hold']}")
    if ex.get("frequency") is not None:
        parts.append(ex["frequency"])
    if not parts and (ex.get("min_sets") is not None or ex.get("min_reps") is not None):
        s = ex.get("min_sets") or ex.get("max_sets")
        r = ex.get("min_reps") or ex.get("max_reps")
        if s is not None:
            parts.append(f"{s} set(s)")
        if r is not None:
            parts.append(f"{r} rep(s)")
    return " · ".join(parts) if parts else "—"


def render_program_page(program_slug: str, data: dict, all_entries: list[tuple[str, str]]) -> str:
    """all_entries: list of (slug, program_name)."""
    name = data.get("program_name") or "Workout"
    exercises = data.get("exercises") or []
    back_links = " · ".join(
        f'<a href="{s}.html">{escape(prog_name)}</a>' if s != program_slug else f'<strong>{escape(prog_name)}</strong>'
        for s, prog_name in all_entries
    )
    exercise_rows = []
    for i, ex in enumerate(exercises, 1):
        dosage = format_dosage(ex)
        desc = (ex.get("description") or "").strip()
        note = (ex.get("note") or "").strip()
        exercise_rows.append(
            f"""
    <article class="exercise">
      <h3>{escape(ex.get("name") or "Exercise")}</h3>
      <p class="dosage">{escape(dosage)}</p>
      {"<div class=\"description\">" + desc + "</div>" if desc else ""}
      {"<p class=\"note\"><strong>Note:</strong> " + escape(note) + "</p>" if note else ""}
    </article>"""
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(name)} — BetterPT</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <nav class="programs">Switch: {back_links}</nav>
    <h1>{escape(name)}</h1>
  </header>
  <main>
    <p class="count">{len(exercises)} exercise(s)</p>
{"".join(exercise_rows)}
  </main>
  <footer><a href="index.html">All programs</a></footer>
</body>
</html>"""


def render_index(entries: list[tuple[str, str]]) -> str:
    """entries: (slug, program_name)."""
    links = "".join(
        f'<li><a href="{s}.html">{escape(name)}</a></li>' for s, name in entries
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>My workouts — BetterPT</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header><h1>My workouts</h1></header>
  <main>
    <ul class="program-list">
{links}
    </ul>
  </main>
</body>
</html>"""


def write_css(dist: Path) -> None:
    (dist / "style.css").write_text(
        """
:root { --bg: #fafafa; --fg: #111; --muted: #555; --accent: #0a5; --border: #ddd; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #1a1a1a; --fg: #eaeaea; --muted: #999; --accent: #2d8; --border: #333; }
}
body { font-family: system-ui, sans-serif; max-width: 52rem; margin: 0 auto; padding: 1rem; background: var(--bg); color: var(--fg); line-height: 1.5; }
header { margin-bottom: 1.5rem; }
header h1 { font-size: 1.5rem; margin: 0; }
nav.programs { font-size: 0.9rem; margin-top: 0.5rem; }
nav.programs a { margin-right: 0.75rem; }
main .count { color: var(--muted); margin-bottom: 1rem; }
article.exercise { border: 1px solid var(--border); border-radius: 0.5rem; padding: 1rem; margin-bottom: 1rem; }
article.exercise h3 { margin: 0 0 0.25rem; font-size: 1.1rem; }
.dosage { margin: 0 0 0.5rem; color: var(--muted); font-size: 0.9rem; }
.description { margin: 0.5rem 0; }
.description ul { margin: 0.25rem 0; }
.note { margin: 0.5rem 0 0; font-size: 0.9rem; }
footer { margin-top: 2rem; font-size: 0.9rem; color: var(--muted); }
ul.program-list { list-style: none; padding: 0; }
ul.program-list a { color: var(--accent); }
""",
        encoding="utf-8",
    )


def main() -> None:
    pairs = load_workout_paths()
    if not pairs:
        print("No workout JSON found. Run export_workout.py first (or set WORKOUT_JSON_PATH).", file=sys.stderr)
        sys.exit(1)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    write_css(DIST_DIR)

    entries = []
    for program_slug, path in pairs:
        data = load_workout(path)
        name = data.get("program_name") or program_slug
        entries.append((program_slug, name))
    for program_slug, path in pairs:
        data = load_workout(path)
        html = render_program_page(program_slug, data, entries)
        (DIST_DIR / f"{program_slug}.html").write_text(html, encoding="utf-8")

    index_html = render_index(entries)
    (DIST_DIR / "index.html").write_text(index_html, encoding="utf-8")

    print(f"Built {DIST_DIR}: index.html + {len(entries)} program page(s)")
    for s, name in entries:
        print(f"  {s}.html — {name}")


if __name__ == "__main__":
    main()
