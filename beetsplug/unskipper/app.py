"""
Minimal curses TUI for browsing and editing a beets import-state pickle file.
Intentionally minimal and dependency-free.
"""
from __future__ import annotations

import curses
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Tuple, List

from . import sidecar
from . import scan
from . import pathremap
from .statefile import StateFileData, load, save


class Kind(Enum):
    HISTORY = 'history'
    PROGRESS = 'progress'
    NEW = 'new'


@dataclass
class Row:
    kind: Kind
    key: object  # taghistory: the path tuple, tagprogress: the toppath, new: (folder, files)
    label: str
    group: Optional[str] = None  # decoded toppath this row belongs to (if known)
    missing: bool = False
    marked: bool = False


UNKNOWN_GROUP = "(unknown top path)"

# Colour pair numbers
PAIR_SELECTED = 1
PAIR_SELECTED_MISSING = 2
PAIR_HEADER = 3
PAIR_MISSING = 4
PAIR_IMPORTED = 5
PAIR_SKIPPED = 6
PAIR_NEW = 7


def _decode(path: bytes) -> str:
    return os.fsdecode(path)


def _strip_toppath(path: str, toppath: str) -> str:
    trimmed = toppath.rstrip(os.sep)
    if path == trimmed:
        return os.path.basename(trimmed) or path
    if path.startswith(trimmed + os.sep):
        return path[len(trimmed) + 1:]
    return path


def build_rows(
    state: StateFileData,
    sidecar_data: Optional[Dict[str, dict]] = None,
    audio_folders: Optional[List[Tuple[bytes, bytes, List[bytes]]]] = None,
) -> List[Row]:
    """
    Flatten the two tables into a single list of rows grouped by toppath.
    """

    rows: List[Row] = []
    sidecar_data = sidecar_data or {}

    for paths in sorted(state.taghistory):
        shown = _decode(paths[0]) if paths else "<empty>"
        info = sidecar_data.get(sidecar.path_key(paths))
        group = info.get('toppath') if info else None

        if group:
            shown = _strip_toppath(shown, group)
        if len(paths) > 1:
            shown += f"  (+{len(paths) - 1} more)"

        missing = not all(os.path.exists(p) for p in paths)
        # if missing:
        #     shown += f"  [missing files!]"

        rows.append(Row(Kind.HISTORY, paths, shown, group=group, missing=missing))

    for toppath, imported in sorted(state.tagprogress.items()):
        group = _decode(toppath)
        rows.append(Row(
            Kind.PROGRESS,
            toppath,
            f"{group}  ({len(imported)} tagged)",
            group=group,
            missing=not os.path.exists(toppath),
        ))

    known_paths = set()

    for paths in state.taghistory:
        known_paths.update(paths)

    for imported in state.tagprogress.values():
        known_paths.update(imported)

    for toppath, folder, files in audio_folders or []:

        if folder in known_paths or any(f in known_paths for f in files):
            continue  # This folder (or a file in it) has been seen before

        group = _decode(toppath)
        shown = _strip_toppath(_decode(folder), group)
        rows.append(Row(Kind.NEW, (folder, tuple(files)), f"[new] {shown}", group=group))

    # Group by toppath (unknown groups last)
    # Within a group, the progress entry acts as header
    rows.sort(key=lambda r: (
        r.group if r.group is not None else '￿',
        0 if r.kind is Kind.PROGRESS else 1,
        r.label,
    ))

    return rows


class UnskipperApp:

    def __init__(self, path: Path, remap: Optional[Tuple[str, str]] = None):
        self.path = path
        self.state: StateFileData = load(path)
        self.sidecar_path = sidecar.sidecar_path(path)
        self.sidecar_data: Dict[str, dict] = sidecar.load(self.sidecar_path)

        self.remap = remap
        if remap:
            old, new = remap
            self.state = pathremap.remap_state(self.state, old, new)
            self.sidecar_data = pathremap.remap_sidecar(self.sidecar_data, old, new)

        toppaths = set(self.state.tagprogress.keys())
        for info in self.sidecar_data.values():
            if info.get('toppath'):
                toppaths.add(os.fsencode(info['toppath']))
        self.audio_folders = scan.scan_folders(toppaths)

        self.rows: List[Row] = build_rows(self.state, self.sidecar_data, self.audio_folders)
        self.cursor = 0
        self.top = 0
        self.dirty = False

    def run(self) -> None:
        curses.wrapper(self._main)

    def _main(self, stdscr) -> None:
        curses.curs_set(0)
        curses.raw()
        stdscr.keypad(True)
        self._init_colors()

        while True:
            self._draw(stdscr)
            key = stdscr.getch()
            if not self._handle_key(key):
                break

    def _init_colors(self) -> None:
        self.has_color = False
        try:
            if not curses.has_colors():
                return
            curses.start_color()
            try:
                curses.use_default_colors()
                bg = -1
            except curses.error:
                bg = curses.COLOR_BLACK

            curses.init_pair(PAIR_SELECTED, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(PAIR_SELECTED_MISSING, curses.COLOR_RED, curses.COLOR_CYAN)
            curses.init_pair(PAIR_HEADER, curses.COLOR_CYAN, bg)
            curses.init_pair(PAIR_MISSING, curses.COLOR_RED, bg)
            curses.init_pair(PAIR_IMPORTED, curses.COLOR_GREEN, bg)
            curses.init_pair(PAIR_SKIPPED, curses.COLOR_YELLOW, bg)
            curses.init_pair(PAIR_NEW, curses.COLOR_MAGENTA, bg)
            self.has_color = True
        except curses.error:
            self.has_color = False

    def _pair(self, n: int) -> int:
        return curses.color_pair(n) if self.has_color else 0

    def _draw(self, stdscr) -> None:

        stdscr.erase()
        height, width = stdscr.getmaxyx()

        remap_note = f"  [remapped {self.remap[0]} -> {self.remap[1]}]" if self.remap else ''
        header = f" unskipper - {self.path}{remap_note} {'*' if self.dirty else ''}"
        stdscr.addnstr(0, 0, header, width - 1, curses.A_REVERSE)

        visible = max(height - 2, 0)
        list_width = max(min(width // 2, 80), 30) if width > 40 else width

        self._draw_list(stdscr, 1, 0, list_width, visible)

        if width > 40:
            for i in range(visible):
                stdscr.addstr(1 + i, list_width, '│')
            self._draw_details(stdscr, 1, list_width + 1, width - list_width - 1, visible)

        footer = '  |  '.join([
            '↑/↓: move',
            'space: mark',
            'del: delete marked',
            '^s: save',
            'esc: quit',
            'a-z: jump to letter'
        ])

        stdscr.addnstr(height - 1, 0, footer, width - 1, curses.A_DIM)
        stdscr.refresh()

    def _build_display_lines(self) -> List[Tuple[str, Optional[int], bool]]:
        """
        Rows, and with group-header lines for toppaths that have
        no progress entry themselves.
        """
        display: List[Tuple[str, Optional[int], bool]] = []
        last_group = object()  # sentinel, unequal to any real group

        for idx, row in enumerate(self.rows):
            if row.group != last_group:
                last_group = row.group
                if row.kind is not Kind.PROGRESS:
                    header = row.group if row.group is not None else UNKNOWN_GROUP
                    display.append((f" {header}", None, True))

            mark = '[•]' if row.marked else '[ ]'
            if row.kind is Kind.PROGRESS:
                line = f'{mark} {row.label}'
            else:
                line = f'  {mark} {row.label}'
            display.append((line, idx, False))

        return display

    def _draw_list(self, stdscr, y0: int, x0: int, width: int, visible: int) -> None:

        display = self._build_display_lines()
        cursor_at = next((i for i, d in enumerate(display) if d[1] == self.cursor), 0)

        if cursor_at < self.top:
            self.top = cursor_at

        elif cursor_at >= self.top + visible:
            self.top = cursor_at - visible + 1

        self.top = max(0, min(self.top, max(len(display) - visible, 0)))

        for i in range(visible):

            idx = self.top + i
            if idx >= len(display):
                break

            text, row_idx, is_header = display[idx]
            attr = self._row_attr(row_idx, is_header)
            stdscr.addnstr(y0 + i, x0, text.ljust(width), width, attr)

        if not self.rows:
            stdscr.addnstr(y0, x0, "(state file is empty)", width, curses.A_DIM)

    def _row_attr(self, row_idx: Optional[int], is_header: bool) -> int:

        if is_header:
            return self._pair(PAIR_HEADER) | curses.A_BOLD

        row = self.rows[row_idx]
        selected = row_idx == self.cursor

        if not self.has_color:
            attr = curses.A_REVERSE if selected else curses.A_NORMAL
            return attr | (curses.A_BOLD if row.missing else 0)

        if selected and row.missing:
            return self._pair(PAIR_SELECTED_MISSING) | curses.A_BOLD
        if selected:
            return self._pair(PAIR_SELECTED)
        if row.missing:
            return self._pair(PAIR_MISSING) | curses.A_BOLD
        if row.kind is Kind.NEW:
            return self._pair(PAIR_NEW) | curses.A_BOLD

        return curses.A_NORMAL

    def _draw_details(self, stdscr, y0: int, x0: int, width: int, visible: int) -> None:

        if width <= 0:
            return

        if not self.rows:
            return

        lines = self._build_details(self.rows[self.cursor])

        for i in range(visible):
            if i >= len(lines):
                break
            prefix, value, style = lines[i]
            x = x0
            if prefix:
                stdscr.addnstr(y0 + i, x, prefix, width, curses.A_BOLD)
                x += len(prefix)
            remaining = width - (x - x0)
            if value and remaining > 0:
                stdscr.addnstr(y0 + i, x, value, remaining, self._detail_attr(style))

        if len(lines) > visible:
            more = f"… (+{len(lines) - visible} more lines)"
            stdscr.addnstr(y0 + visible - 1, x0, more, width, curses.A_DIM)

    def _detail_attr(self, style: str) -> int:

        if style == 'missing':
            return self._pair(PAIR_MISSING) | curses.A_BOLD
        if style == 'imported':
            return self._pair(PAIR_IMPORTED) | (0 if self.has_color else curses.A_BOLD)
        if style == 'skipped':
            return self._pair(PAIR_SKIPPED) | (0 if self.has_color else curses.A_BOLD)
        if style == 'dim':
            return curses.A_DIM
        if style == 'label':
            return curses.A_BOLD
        return curses.A_NORMAL

    def _build_details(self, row: Row) -> List[Tuple[str, str, str]]:

        lines: List[Tuple[str, str, str]] = [
            ("Kind: ", row.kind.value, 'plain'),
            ("", "", 'plain'),
        ]

        if row.kind is Kind.HISTORY:
            paths = row.key
            lines.append((f"Paths ({len(paths)}):", "", 'label'))
            for p in paths:
                style = 'plain' if os.path.exists(p) else 'missing'
                lines.append(("", f"  {_decode(p)}", style))

            info = self.sidecar_data.get(sidecar.path_key(paths))
            lines.append(("", "", 'plain'))

            if info:
                lines.append(("Details:", "", 'label'))
                outcome = info.get('outcome')
                outcome_style = {'imported': 'imported', 'skipped': 'skipped'}.get(outcome, 'plain')

                lines.append(("  Choice: ", str(info.get('choice')).title(), 'plain'))
                lines.append(("  Outcome: ", str(outcome), outcome_style))

                if info.get('operation'):
                    lines.append(("  Operation: ", str(info['operation']), 'plain'))

                dest_paths = info.get('dest_paths')
                if dest_paths:
                    lines.append(("  Destination:", "", 'plain'))
                    for dest in dest_paths:
                        style = 'plain' if os.path.exists(dest) else 'missing'
                        lines.append(("", f"    {dest}", style))

                if info.get('release'):
                    lines.append(("  Release: ", f"https://musicbrainz.org/release/{str(info['release'])}", 'plain'))

                if info.get('toppath'):
                    style = 'plain' if os.path.exists(os.fsencode(info['toppath'])) else 'missing'
                    lines.append(("  Top path: ", info['toppath'], style))

                ts = info.get('ts')
                if ts:
                    stamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
                    lines.append(("  Recorded: ", stamp, 'dim'))
            else:
                lines.append(("", "No record (outcome unknown).", 'dim'))
        elif row.kind is Kind.PROGRESS:
            toppath = row.key
            imported = self.state.tagprogress.get(toppath, [])
            top_style = 'plain' if os.path.exists(toppath) else 'missing'
            lines.append(("Top path: ", _decode(toppath), top_style))
            lines.append(("", "", 'plain'))
            lines.append((f"Tagged items ({len(imported)}):", "", 'label'))
            for p in sorted(imported):
                style = 'plain' if os.path.exists(p) else 'missing'
                lines.append(("", f"  {_decode(p)}", style))

        else:  # Kind.NEW
            folder, files = row.key
            lines.append(("Folder: ", _decode(folder), 'plain'))
            lines.append(("", "", 'plain'))
            lines.append((f"Audio files ({len(files)}):", "", 'label'))
            for p in files:
                lines.append(("", f"  {_decode(p)}", 'plain'))

        return lines

    def _handle_key(self, key: int) -> bool:

        if key == 27:  # Esc
            return False
        elif key == curses.KEY_DOWN:
            self.cursor = min(self.cursor + 1, max(len(self.rows) - 1, 0))
        elif key == curses.KEY_UP:
            self.cursor = max(self.cursor - 1, 0)
        elif key == ord(' '):
            if self.rows:
                self.rows[self.cursor].marked = not self.rows[self.cursor].marked
        elif key in (curses.KEY_DC, curses.KEY_BACKSPACE, 127, 8):
            self._delete_marked()
        elif key == 19:  # ctrl + s
            self._write()
        elif 0 <= key < 256 and chr(key).isalpha():
            self._jump_to_letter(chr(key).lower())

        return True

    def _jump_to_letter(self, ch: str) -> None:

        n = len(self.rows)
        if not n:
            return

        for offset in range(1, n + 1):
            idx = (self.cursor + offset) % n
            if self.rows[idx].label.lower().startswith(ch):
                self.cursor = idx
                return

    def _delete_marked(self) -> None:

        marked = [r for r in self.rows if r.marked]
        if not marked and self.rows:
            marked = [self.rows[self.cursor]]

        for row in marked:
            if row.kind is Kind.HISTORY:
                self.state.taghistory.discard(row.key)
                self.sidecar_data.pop(sidecar.path_key(row.key), None)
            elif row.kind is Kind.PROGRESS:
                self.state.tagprogress.pop(row.key, None)

        self.rows = build_rows(self.state, self.sidecar_data, self.audio_folders)
        self.cursor = min(self.cursor, max(len(self.rows) - 1, 0))
        self.dirty = True

    def _write(self) -> None:
        save(self.path, self.state)
        sidecar.save(self.sidecar_path, self.sidecar_data)
        self.dirty = False
