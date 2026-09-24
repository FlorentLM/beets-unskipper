# beets-unskipper

Ultra simple [beets](https://beets.io) plugin to browse and edit beets' import state
file (`state.pickle`) with a tiny terminal UI.

Beets records which album/track directories it has already imported in
`state.pickle`. An `--incremental` import skips anything already recorded
there, even if a past import was aborted partway through or the tags need
reworking later. `unskipper` opens that file, lets you look through what is
recorded, and remove entries so beets will reconsider those directories on
the next import.

**Status: early skeleton.** Browsing, marking and deleting `taghistory` /
`tagprogress` entries works. Filtering, search, and undo are not implemented
yet.

## Installation

Clone and install:

```sh
git clone https://github.com/FlorentLM/beets-unskipper
uv pip install beets-unskipper
```

or if you used Beets' default `uv tool` install:

```sh
uv tool install beets --with ./beets-unskipper --reinstall
```

Then add `unskipper` to the `plugins` line in your beets config.

## Usage

```sh
beet unskipper
```

Opens the state file at the location beets is configured to use. Pass
`-f/--file` to point at a different `state.pickle`:

```sh
beet unskipper -f /path/to/state.pickle
```

### Keys

| Key            | Action                                                      |
|----------------|---------------------------------------------------------------|
| `↓`            | move down                                                    |
| `↑`            | move up                                                      |
| `a`-`z`        | jump to the next row starting with that letter               |
| `space`        | mark/unmark the current row                                  |
| `Del`          | delete marked rows (or the current one if none are marked)   |
| `Ctrl+S`       | write changes back to the state file                         |
| `Ctrl+Q`/`Esc` | quit                                                          |