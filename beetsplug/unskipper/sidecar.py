from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable, Optional, Dict

PathBytes = bytes


def sidecar_path(state_path: Path) -> Path:
    return state_path.with_name(state_path.stem + '.unskipper.json')


def path_key(paths: Iterable[PathBytes]) -> str:
    return '\x1f'.join(os.fsdecode(p) for p in paths)


def load(path: Path) -> Dict[str, dict]:
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(path: Path, data: Dict[str, dict]) -> None:
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)


def record(
    data: Dict[str, dict],
    paths: Iterable[PathBytes],
    toppath: Optional[PathBytes],
    outcome: str,
    choice: Optional[str],
    operation: Optional[str] = None,
    release: Optional[str] = None,
) -> None:

    data[path_key(paths)] = {
        'toppath': os.fsdecode(toppath) if toppath else None,
        'outcome': outcome,
        'choice': choice,
        'operation': operation,
        'release': release,
        'ts': time.time(),
    }
