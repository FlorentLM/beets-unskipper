from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Iterable, Optional, Dict, Sequence

PathBytes = bytes

lock = threading.Lock()


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


def reconcile(data: Dict[str, dict], taghistory: Iterable[tuple[PathBytes, ...]]) -> int:
    """
    Update the sidecar to follow state.pickle. Returns number of changes.

    - A record the pickle no longer has (removed by another tool or an unskip)
      gets `in_taghistory` cleared.
    - A multi-folder record that the pickle lists one folder at a time is split the
      same way (so that `--rebuild` does not bring back the combined entry)
    """
    listed = set(taghistory)
    singles = {p for entry in listed for p in entry}
    changed = 0

    for key, info in list(data.items()):
        if info.get('kind') == 'import-done' or not info.get('in_taghistory'):
            continue

        paths = decode_path_key(key)
        if paths in listed:
            continue

        if len(paths) > 1 and all(p in singles for p in paths):
            del data[key]
            for p in paths:
                data[path_key((p,))] = dict(info)
        else:
            info['in_taghistory'] = False

        changed += 1

    return changed + adopt_orphans(data, listed)


def adopt_orphans(data: Dict[str, dict], taghistory: Iterable[tuple[PathBytes, ...]]) -> int:
    """
    Add a sidecar record for history entries that unskipper never saw being created.
    Returns number of changes.
    (a folder that is part of a multi-folder record inherits that record's details)
    """
    members: dict[PathBytes, dict] = {}
    toppaths: set[bytes] = set()

    for key, info in data.items():
        if info.get('toppath'):
            toppaths.add(os.fsencode(info['toppath']).rstrip(os.sep.encode()) or os.sep.encode())
        if info.get('kind') == 'import-done':
            continue
        paths = decode_path_key(key)
        if len(paths) > 1:
            for p in paths:
                members.setdefault(p, info)

    sep = os.sep.encode()
    changed = 0

    for paths in taghistory:
        key = path_key(paths)
        if key in data or not paths:
            continue

        parent = members.get(paths[0]) if len(paths) == 1 else None
        if parent is not None:
            data[key] = {**parent, 'in_taghistory': True, 'in_tagprogress': False, 'dest_paths': None}
            changed += 1
            continue

        candidates = [t for t in toppaths if paths[0] == t or paths[0].startswith(t.rstrip(sep) + sep)]
        if candidates:
            data[key] = {
                'kind': 'album',
                'toppath': os.fsdecode(max(candidates, key=len)),
                'outcome': None,
                'in_taghistory': True,
                'in_tagprogress': False,
                'ts': time.time(),
            }
            changed += 1

    return changed


def folders_to_split(
        taghistory: Iterable[tuple[PathBytes, ...]],
    ) -> tuple[dict[tuple[PathBytes, ...], tuple[PathBytes, ...]], int]:
    """
    Single-folder entries missing for multi-folder entries.
    """

    existing = set(taghistory)
    missing: dict[tuple[PathBytes, ...], tuple[PathBytes, ...]] = {}
    not_dirs: set[PathBytes] = set()

    for entry in sorted(existing):
        if len(entry) < 2:
            continue
        for p in entry:
            single = (p,)
            if single in existing or single in missing:
                continue
            if os.path.isdir(p):
                missing[single] = entry
            else:
                not_dirs.add(p)

    return missing, len(not_dirs)
