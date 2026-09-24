"""
Beets plugin unskipper: browse and edit beets' import state file
(`state.pickle`) with a small terminal UI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict

from beets import ui
from beets.plugins import BeetsPlugin

from . import sidecar
from .statefile import default_state_path


class UnskipperPlugin(BeetsPlugin):

    def __init__(self):
        super().__init__()
        # id(task) -> {'paths': ..., 'toppath': ..., 'task': ...}, until the task's outcome (imported/skipped) is known
        self._pending: Dict[int, dict] = {}
        self.register_listener('import_task_choice', self._on_choice)
        self.register_listener('import_task_files', self._on_files)
        self.register_listener('cli_exit', self._on_exit)

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

    # Import-time sidecar recording

    def _on_choice(self, session, task) -> None:

        if not getattr(task, 'is_album', False) or task.toppath is None:
            return  # TODO: Also support single track imports

        self._pending[id(task)] = {
            'task': task,
            'paths': tuple(task.paths),
            'toppath': task.toppath,
        }

    def _on_files(self, session, task) -> None:
        # Fires once a task's status is set to "not skipped", after
        # files have been moved/copied/linked
        rec = self._pending.pop(id(task), None)
        if rec is not None:
            self._record(
                rec, outcome='imported',
                operation=self._operation_name(session),
                release=self._release_id(task),
            )

    def _on_exit(self, lib) -> None:
        # Anything still pending never reached import_task_files: it was skipped
        for rec in self._pending.values():
            self._record(rec, outcome='skipped', release=self._release_id(rec['task']))
        self._pending.clear()

    @staticmethod
    def _operation_name(session) -> str | None:
        # Mirrors logic in beets.importer.stages.manipulate_files
        cfg = session.config

        if cfg['move']:
            return 'move'
        if cfg['copy']:
            return 'copy'
        if cfg['link']:
            return 'symlink'
        if cfg['hardlink']:
            return 'hardlink'
        if cfg['reflink'].get() == 'auto':
            return 'reflink_auto'
        if cfg['reflink']:
            return 'reflink'
        return 'in-place'  # file left where it was

    @staticmethod
    def _release_id(task) -> str | None:
        album = getattr(task, 'album', None)
        if album is not None and getattr(album, 'mb_albumid', None):
            return album.mb_albumid
        match = getattr(task, 'match', None)
        info = getattr(match, 'info', None) if match else None
        return getattr(info, 'album_id', None) if info else None

    def _record(self,
        rec: dict,
        outcome: str,
        operation: Optional[str] = None,
        release: Optional[str] = None,
    ) -> None:

        path = sidecar.sidecar_path(default_state_path())
        data = sidecar.load(path)

        sidecar.record(
            data, rec['paths'], rec['toppath'], outcome,
            choice=rec['task'].choice_flag.name if rec['task'].choice_flag else None,
            operation=operation,
            release=release,
        )
        sidecar.save(path, data)
