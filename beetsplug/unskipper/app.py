"""
Minimal curses TUI for browsing and editing a beets import-state pickle file.
Intentionally minimal and dependency-free.
"""
from __future__ import annotations

import curses
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .statefile import StateFileData, load, save


class Kind(Enum):
    HISTORY = 'history'
    PROGRESS = 'progress'


@dataclass
class Row:
    kind: Kind
    key: object  # taghistory: the path tuple itself, tagprogress: the toppath
    label: str
    marked: bool = False


def _decode(path: bytes) -> str:
    return os.fsdecode(path)


def build_rows(state: StateFileData) -> list[Row]:
    """Flatten the two tables into a single list of rows for display."""
    rows: list[Row] = []

    for paths in sorted(state.taghistory):
        shown = _decode(paths[0]) if paths else "<empty>"
        if len(paths) > 1:
            shown += f"  (+{len(paths) - 1} more)"
        rows.append(Row(Kind.HISTORY, paths, shown))

    for toppath, imported in sorted(state.tagprogress.items()):
        rows.append(Row(
            Kind.PROGRESS,
            toppath,
            f"{_decode(toppath)}  [{len(imported)} tagged]",
        ))

    return rows


class UnskipperApp:

    def __init__(self, path: Path):
        self.path = path
        self.state: StateFileData = load(path)
        self.rows: list[Row] = build_rows(self.state)
        self.cursor = 0
        self.top = 0
        self.dirty = False

    def run(self) -> None:
        curses.wrapper(self._main)

    def _main(self, stdscr) -> None:
        curses.curs_set(0)
        stdscr.keypad(True)

        while True:
            self._draw(stdscr)
            key = stdscr.getch()
            if not self._handle_key(key):
                break

    def _draw(self, stdscr) -> None:

        stdscr.erase()
        height, width = stdscr.getmaxyx()

        header = f" unskipper - {self.path} {'*' if self.dirty else ''}"
        stdscr.addnstr(0, 0, header, width - 1, curses.A_REVERSE)

        visible = max(height - 2, 0)
        if self.cursor < self.top:
            self.top = self.cursor

        elif self.cursor >= self.top + visible:
            self.top = self.cursor - visible + 1

        for i in range(visible):

            idx = self.top + i
            if idx >= len(self.rows):
                break

            row = self.rows[idx]
            mark = '[x]' if row.marked else '[ ]'
            line = f'{mark} {row.kind.value:<9} {row.label}'
            attr = curses.A_REVERSE if idx == self.cursor else curses.A_NORMAL
            stdscr.addnstr(1 + i, 0, line, width - 1, attr)

        if not self.rows:
            stdscr.addnstr(1, 0, "(state file is empty)", width - 1, curses.A_DIM)

        footer = " ↑/↓ move  space mark  d delete marked  w write  q quit"

        stdscr.addnstr(height - 1, 0, footer, width - 1, curses.A_DIM)
        stdscr.refresh()

    def _handle_key(self, key: int) -> bool:

        if key in (ord('q'), 27):  # q or Esc
            return False
        elif key in (ord('j'), curses.KEY_DOWN):
            self.cursor = min(self.cursor + 1, max(len(self.rows) - 1, 0))
        elif key in (ord('k'), curses.KEY_UP):
            self.cursor = max(self.cursor - 1, 0)
        elif key == ord(' '):
            if self.rows:
                self.rows[self.cursor].marked = not self.rows[self.cursor].marked
        elif key == ord('d'):
            self._delete_marked()
        elif key == ord('w'):
            self._write()

        return True

    def _delete_marked(self) -> None:

        marked = [r for r in self.rows if r.marked]
        if not marked and self.rows:
            marked = [self.rows[self.cursor]]

        for row in marked:
            if row.kind is Kind.HISTORY:
                self.state.taghistory.discard(row.key)
            else:
                self.state.tagprogress.pop(row.key, None)

        self.rows = build_rows(self.state)
        self.cursor = min(self.cursor, max(len(self.rows) - 1, 0))
        self.dirty = True

    def _write(self) -> None:
        save(self.path, self.state)
        self.dirty = False
