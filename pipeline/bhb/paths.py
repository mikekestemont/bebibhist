"""Repository locations. Raw inputs are read-only; derived data goes to build/."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "PLAN.md").is_file() and (candidate / "pipeline" / "bhb").is_dir():
            return candidate
    raise FileNotFoundError("could not locate the bebibhist repository root")


def build_dir() -> Path:
    path = repo_root() / "build"
    path.mkdir(parents=True, exist_ok=True)
    return path


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root()))
    except ValueError:
        return str(path)
