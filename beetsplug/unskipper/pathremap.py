from __future__ import annotations

import os
from typing import Dict, Tuple

from . import sidecar
from .statefile import PathBytes, StateFileData


def remap_bytes(path: PathBytes, old: PathBytes, new: PathBytes) -> PathBytes:
    if path == old:
        return new
    sep = os.fsencode(os.sep)
    if path.startswith(old + sep):
        return new + path[len(old):]
    return path


def remap_str(path: str, old: str, new: str) -> str:
    return os.fsdecode(remap_bytes(os.fsencode(path), os.fsencode(old), os.fsencode(new)))


def remap_state(state: StateFileData, old: str, new: str) -> StateFileData:

    old_b, new_b = os.fsencode(old.rstrip(os.sep)), os.fsencode(new.rstrip(os.sep))

    taghistory = {
        tuple(remap_bytes(p, old_b, new_b) for p in paths)
        for paths in state.taghistory
    }
    tagprogress = {
        remap_bytes(toppath, old_b, new_b): [remap_bytes(p, old_b, new_b) for p in paths]
        for toppath, paths in state.tagprogress.items()
    }
    return StateFileData(tagprogress=tagprogress, taghistory=taghistory)


def remap_sidecar(data: Dict[str, dict], old: str, new: str) -> Dict[str, dict]:

    old_stripped, new_stripped = old.rstrip(os.sep), new.rstrip(os.sep)
    old_b, new_b = os.fsencode(old_stripped), os.fsencode(new_stripped)

    remapped: Dict[str, dict] = {}

    for key, info in data.items():
        new_info = dict(info)

        if info.get('kind') == 'import-done':
            toppath = info.get('toppath')
            new_key = key
            if toppath:
                new_toppath = remap_str(toppath, old_stripped, new_stripped)
                new_info['toppath'] = new_toppath
                new_key = sidecar.import_done_key(new_toppath)
            remapped[new_key] = new_info
            continue

        paths = sidecar.decode_path_key(key)
        new_paths = tuple(remap_bytes(p, old_b, new_b) for p in paths)
        new_key = sidecar.path_key(new_paths)

        if info.get('toppath'):
            new_info['toppath'] = remap_str(info['toppath'], old_stripped, new_stripped)
        if info.get('dest_paths'):
            new_info['dest_paths'] = [
                remap_str(p, old_stripped, new_stripped) for p in info['dest_paths']
            ]

        remapped[new_key] = new_info

    return remapped


def parse_remap_arg(arg: str) -> Tuple[str, str]:
    """Parse `OLD=NEW` CLI argument."""

    if '=' not in arg:
        raise ValueError("expected OLD=NEW")
    old, new = arg.split('=', 1)

    if not old or not new:
        raise ValueError("expected OLD=NEW")
    return old, new
