"""Pack the derived dataset for a GitHub release. The raw sources stay elsewhere."""

from __future__ import annotations

import gzip
import json
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path

from bhb.mods import DATA_LICENCE, DATA_LICENCE_URL
from bhb.paths import repo_root


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def write_release(records: Path, destination: Path, built_on: str | None = None, commit: str | None = None) -> Path:
    """Gzip ``records.jsonl`` and write ``NOTES.md`` beside it. Returns the notes path."""
    if not records.is_file():
        raise FileNotFoundError(f"{records} is missing; run bhb build first")
    destination.mkdir(parents=True, exist_ok=True)
    packed = destination / "records.jsonl.gz"
    counts: Counter[str] = Counter()
    with records.open("rb") as source, gzip.open(packed, "wb") as target:
        for raw in source:
            if raw.strip():
                row = json.loads(raw)
                counts[str(row.get("source") or "unknown")] += 1
            target.write(raw)
    when = built_on or date.today().isoformat()
    notes = destination / "NOTES.md"
    notes.write_text(render_notes(counts, when, commit or git_commit()), encoding="utf-8")
    return notes


def render_notes(counts: Counter[str], built_on: str, commit: str) -> str:
    lines = [
        "# BHB-BGB derived dataset",
        "",
        "This is the derived dataset, not the raw sources.",
        "",
        f"- Built: {built_on}",
        f"- Git commit: {commit}",
        "",
        "## Records",
        "",
        "| Source | Records |",
        "|---|---:|",
    ]
    for source in sorted(counts):
        lines.append(f"| {source} | {counts[source]} |")
    lines.append(f"| **Total** | {sum(counts.values())} |")
    lines.extend(
        [
            "",
            f"The bibliography as a whole is {DATA_LICENCE} ({DATA_LICENCE_URL}). "
            "Credit the Royal Commission of History. Commercial use is not permitted.",
            "",
        ]
    )
    return "\n".join(lines)


def release_command(built_on: str) -> str:
    tag = f"data-{built_on}"
    return (
        f"gh release create {tag} build/release/records.jsonl.gz build/release/NOTES.md "
        f'--title "BHB-BGB data {built_on}" --notes-file build/release/NOTES.md'
    )
