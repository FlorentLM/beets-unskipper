from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

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
