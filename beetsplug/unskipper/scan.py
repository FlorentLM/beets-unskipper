from __future__ import annotations

import os
from typing import Iterable, List, Tuple

PathBytes = bytes

AUDIO_EXTS = {
    b'.mp3', b'.flac', b'.m4a', b'.m4b', b'.aac', b'.ogg', b'.oga', b'.opus',
    b'.wav', b'.aiff', b'.aif', b'.wma', b'.ape', b'.wv', b'.mpc',
    b'.dsf', b'.dff', b'.alac', b'.ac3', b'.spx',
}


def _is_audio(name: bytes) -> bool:
    return os.path.splitext(name)[1].lower() in AUDIO_EXTS


def scan_folders(
    toppaths: Iterable[PathBytes],
) -> List[Tuple[PathBytes, PathBytes, List[PathBytes]]]:
    """
    Walk each toppath and return (toppath, folder, audio_files)
    per directory that directly contains audio files.
    """
    results: List[Tuple[PathBytes, PathBytes, List[PathBytes]]] = []

    for toppath in sorted(set(toppaths)):
        if not os.path.isdir(toppath):
            continue
        for dirpath, _dirnames, filenames in os.walk(toppath):
            audio = sorted(os.path.join(dirpath, f) for f in filenames if _is_audio(f))
            if audio:
                results.append((toppath, dirpath, audio))

    return results
