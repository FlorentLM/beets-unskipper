from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable

PathBytes = bytes


def sidecar_path(state_path: Path) -> Path:
    return state_path.with_name(state_path.stem + '.unskipper.json')


def path_key(paths: Iterable[PathBytes]) -> str:
    return '\x1f'.join(os.fsdecode(p) for p in paths)


def load(path: Path) -> dict[str, dict]:
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(path: Path, data: dict[str, dict]) -> None:
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)


def record(
    data: dict[str, dict],
    paths: Iterable[PathBytes],
    toppath: PathBytes | None,
    outcome: str,
    choice: str | None,
    source: str = 'live',
) -> None:
    data[path_key(paths)] = {
        'toppath': os.fsdecode(toppath) if toppath else None,
        'outcome': outcome,
        'choice': choice,
        'source': source,
        'ts': time.time(),
    }
