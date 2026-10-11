"""Repository locations. Raw inputs are read-only and live outside this tree; derived data goes to build/."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pipeline" / "pyproject.toml").is_file() and (candidate / "pipeline" / "bhb").is_dir():
            return candidate
    raise FileNotFoundError("could not locate the bebibhist repository root")


def raw_candidate() -> Path:
    chosen = os.environ.get("BHB_RAW")
    if chosen:
        return Path(chosen).expanduser()
    return repo_root().parent / "bebibhist-raw"


def raw_available() -> bool:
    return raw_candidate().is_dir()


def raw_root() -> Path:
    path = raw_candidate()
    if not path.is_dir():
        raise FileNotFoundError(
            f"Raw inputs are not in this repository. Set BHB_RAW to the folder that holds them (looked for {path})."
        )
    return path


def build_dir() -> Path:
    path = repo_root() / "build"
    path.mkdir(parents=True, exist_ok=True)
    return path


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root()))
    except ValueError:
        return str(path)
