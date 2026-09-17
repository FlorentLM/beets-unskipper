"""
Beets plugin unskipper: browse and edit beets' import state file
(`state.pickle`) with a small terminal UI.
"""
from __future__ import annotations

from pathlib import Path
from beets import ui
from beets.plugins import BeetsPlugin

from .statefile import default_state_path


class UnskipperPlugin(BeetsPlugin):

    def commands(self):
        cmd = ui.Subcommand(
            'unskipper',
            help="Browse/edit beets' import state file",
        )
        cmd.parser.add_option(
            '-f', '--file',
            dest='state_file',
            help='Path to state.pickle (defaults to the configured statefile)',
        )
        cmd.func = self._run
        return [cmd]

    def _run(self, lib, opts, args):
        from .app import UnskipperApp

        path = Path(opts.state_file) if opts.state_file else default_state_path()
        if not path.exists():
            raise ui.UserError(f'State file not found: {path}')

        UnskipperApp(path).run()
