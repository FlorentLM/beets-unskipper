from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable, Optional, Dict, Sequence

PathBytes = bytes


def import_done_key(toppath: str) -> str:
    return '\x00import-done\x00' + toppath


def sidecar_path(state_path: Path) -> Path:
    return state_path.with_name(state_path.stem + '.unskipper.json')


def path_key(paths: Iterable[PathBytes]) -> str:
    return '\x1f'.join(os.fsdecode(p) for p in paths)


def decode_path_key(key: str) -> tuple[PathBytes, ...]:
    return tuple(os.fsencode(p) for p in key.split('\x1f'))


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
    kind: str = 'album',
    in_tagprogress: bool = False,
    in_taghistory: bool = False,
    dest_paths: Optional[Sequence[PathBytes]] = None,
) -> None:

    data[path_key(paths)] = {
        'toppath': os.fsdecode(toppath) if toppath else None,
        'outcome': outcome,
        'choice': choice,
        'operation': operation,
        'release': release,
        'kind': kind,
        'in_tagprogress': in_tagprogress,
        'in_taghistory': in_taghistory,
        'dest_paths': [os.fsdecode(p) for p in dest_paths] if dest_paths else None,
        'ts': time.time(),
    }

def record_import_done(data: Dict[str, dict], toppath: PathBytes) -> None:
    """
    Records when beets finished scanning `toppath`.
    """
    data[import_done_key(os.fsdecode(toppath))] = {
        'kind': 'import-done',
        'toppath': os.fsdecode(toppath),
        'ts': time.time(),
    }
