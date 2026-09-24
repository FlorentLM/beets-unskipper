from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from . import sidecar

PathBytes = bytes


@dataclass
class StateFileData:
    tagprogress: dict[PathBytes, list[PathBytes]] = field(default_factory=dict)
    taghistory: set[tuple[PathBytes, ...]] = field(default_factory=set)


def default_state_path() -> Path:
    """Location of `state.pickle` according to the active beets config."""
    from beets import config

    return Path(config['statefile'].as_filename())


def load(path: Path) -> StateFileData:
    """Load a `state.pickle` file. Missing keys treated as empty."""

    with path.open('rb') as f:
        raw = pickle.load(f)

    return StateFileData(
        tagprogress=raw.get('tagprogress', {}),
        taghistory=raw.get('taghistory', set()),
    )


def save(path: Path, state: StateFileData) -> None:
    """Write a `state.pickle` file."""

    with path.open('wb') as f:
        pickle.dump(
            {'tagprogress': state.tagprogress, 'taghistory': state.taghistory},
            f,
        )


def from_sidecar(data: Dict[str, dict]) -> StateFileData:
    """
    Rebuild a `state.pickle` from unskipper's records.
    """
    tagprogress: dict[PathBytes, list[PathBytes]] = {}
    taghistory: set[tuple[PathBytes, ...]] = set()

    done_at: dict[str, float] = {}
    for info in data.values():
        if info.get('kind') == 'import-done' and info.get('toppath'):
            toppath = info['toppath']
            done_at[toppath] = max(done_at.get(toppath, 0.0), info.get('ts', 0.0))

    for key, info in data.items():
        if info.get('kind') == 'import-done':
            continue

        paths = sidecar.decode_path_key(key)

        if info.get('in_taghistory'):
            taghistory.add(paths)

        toppath = info.get('toppath')
        if info.get('in_tagprogress') and toppath:

            if info.get('ts', 0.0) <= done_at.get(toppath, -1.0):
                continue  # Beets already cleared this by the time it wrote the pickle

            imported = tagprogress.setdefault(os.fsencode(toppath), [])
            for p in paths:
                if p not in imported:
                    imported.append(p)

    for imported in tagprogress.values():
        imported.sort()

    return StateFileData(tagprogress=tagprogress, taghistory=taghistory)
