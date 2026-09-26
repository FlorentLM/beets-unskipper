"""
Beets plugin unskipper: browse and edit beets' import state file
(`state.pickle`) with a small terminal UI.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Tuple

from beets import ui
from beets.importer import SentinelImportTask
from beets.plugins import BeetsPlugin

from . import sidecar
from . import pathremap
from .statefile import default_state_path, StateFileData


class UnskipperPlugin(BeetsPlugin):

    def __init__(self):
        super().__init__()
        # id(task) -> {'paths': ..., 'toppath': ..., 'task': ...}, until the task's outcome (imported/skipped) is known
        self._pending: Dict[int, dict] = {}

        self._session = None    # Session doing the touching
        self._toppaths: set[bytes] = set()  # toppaths touched so far in the session

        self.register_listener('import_task_choice', self._on_choice)
        self.register_listener('import_task_files', self._on_files)
        self.register_listener('cli_exit', self._on_exit)

    def commands(self):
        cmd = ui.Subcommand(
            'unskipper',
            help="Browse/edit beets' import state file",
        )
        cmd.parser.add_option(
            '-s', '--state-file',
            dest='state_file',
            help='Path to state.pickle',
        )
        cmd.parser.add_option(
            '-j', '--unskipper-json',
            dest='sidecar_file',
            help='Path to the unskipper sidecar JSON (defaults to alongside the state file)',
        )
        cmd.parser.add_option(
            '-r', '--remap',
            dest='remap',
            metavar='OLD=NEW',
            help='Remap paths starting with OLD to start with NEW when loading',
        )
        cmd.parser.add_option(
            '--rebuild', action='store_true', dest='rebuild',
            help="Overwrite state.pickle by rebuilding it from the sidecar JSON",
        )
        cmd.parser.add_option(
            '--migrate-db', action='store_true', dest='migrate_db',
            help="Rewrite item/album paths in the beets database using --remap OLD=NEW",
        )
        cmd.parser.add_option(
            '-d', '--dry-run', action='store_true', dest='dry_run',
            help="With --rebuild, print a summary of what would change without writing state.pickle",
        )
        cmd.func = self._run
        return [cmd]

    def _run(self, lib, opts, args):
        from .app import UnskipperApp

        path = Path(opts.state_file) if opts.state_file else default_state_path()
        sidecar_path = Path(opts.sidecar_file) if opts.sidecar_file else sidecar.sidecar_path(path)

        remap = None
        if opts.remap:
            try:
                remap = pathremap.parse_remap_arg(opts.remap)
            except ValueError as exc:
                raise ui.UserError(f'--remap {exc}')

        if opts.migrate_db:
            if not remap:
                raise ui.UserError('--migrate-db requires --remap OLD=NEW')
            self._migrate_db(lib, remap, dry_run=bool(opts.dry_run))
            return

        if opts.rebuild:
            self._rebuild(path, sidecar_path, remap, dry_run=bool(opts.dry_run))
            return

        if not path.exists():
            raise ui.UserError(f'State file not found: {path}')

        UnskipperApp(path, remap=remap, sidecar_path=sidecar_path).run()

    @staticmethod
    def _rebuild(path: Path, sidecar_path: Path, remap, dry_run: bool = False) -> None:
        from .statefile import StateFileData, from_sidecar, load as load_state, save as save_state

        if not sidecar_path.exists():
            raise ui.UserError(f'Sidecar file not found: {sidecar_path}')

        data = sidecar.load(sidecar_path)
        new_data = data
        if remap:
            old, new = remap
            new_data = pathremap.remap_sidecar(data, old, new)

        new_state = from_sidecar(new_data)
        sidecar_changed = new_data != data

        if dry_run:
            old_state = load_state(path) if path.exists() else StateFileData()
            UnskipperPlugin._print_rebuild_diff(path, old_state, new_state)
            if sidecar_changed:
                print(f'  sidecar: {sidecar_path} would also be rewritten in place with remapped paths')
            return

        prompt = f'This will overwrite {path}'
        if sidecar_changed:
            prompt += f' and remap paths in {sidecar_path}'
        prompt += '. Continue?'

        if (path.exists() or sidecar_changed) and not ui.input_yn(prompt, require=True):
            return

        if sidecar_changed:
            sidecar.save(sidecar_path, new_data)

        save_state(path, new_state)
        print(
            f'Rebuilt {path} from {sidecar_path} '
            f'({len(new_state.taghistory)} taghistory entries, '
            f'{len(new_state.tagprogress)} tagprogress toppaths)'
        )
        if sidecar_changed:
            print(f'Remapped paths in {sidecar_path}.')

    @staticmethod
    def _print_rebuild_diff(path: Path, old_state: StateFileData, new_state: StateFileData) -> None:
        added_history = new_state.taghistory - old_state.taghistory
        removed_history = old_state.taghistory - new_state.taghistory

        old_toppaths = set(old_state.tagprogress)
        new_toppaths = set(new_state.tagprogress)

        added_progress = new_toppaths - old_toppaths
        removed_progress = old_toppaths - new_toppaths

        changed_progress = {
            t for t in old_toppaths & new_toppaths
            if old_state.tagprogress[t] != new_state.tagprogress[t]
        }

        print(f'Rebuild preview for {path} (dry run):')
        print(
            f'  taghistory: {len(old_state.taghistory)} -> {len(new_state.taghistory)} entries '
            f'(+{len(added_history)}, -{len(removed_history)})'
        )
        print(
            f'  tagprogress: {len(old_state.tagprogress)} -> {len(new_state.tagprogress)} toppaths '
            f'(+{len(added_progress)}, -{len(removed_progress)}, ~{len(changed_progress)} changed)'
        )

    @staticmethod
    def _migrate_db(lib, remap: Tuple[str, str], dry_run: bool = False) -> None:

        old, new = remap
        old_b = os.fsencode(old.rstrip(os.sep))
        new_b = os.fsencode(new.rstrip(os.sep))

        item_changes = []
        for item in lib.items():
            new_path = pathremap.remap_bytes(item.path, old_b, new_b)
            if new_path != item.path:
                item_changes.append((item, new_path))

        album_changes = []
        for album in lib.albums():
            if not album.artpath:
                continue
            new_artpath = pathremap.remap_bytes(album.artpath, old_b, new_b)
            if new_artpath != album.artpath:
                album_changes.append((album, new_artpath))

        print(
            f'{len(item_changes)} item path(s) and {len(album_changes)} album art path(s) '
            f'would be remapped ({old} -> {new}).'
        )

        if dry_run:
            for item, new_path in item_changes[:20]:
                print(f'  {os.fsdecode(item.path)} -> {os.fsdecode(new_path)}')
            if len(item_changes) > 20:
                print(f'  … (+{len(item_changes) - 20} more)')
            return

        if not (item_changes or album_changes):
            return

        if not ui.input_yn(
            f'This will rewrite {len(item_changes)} item path(s) and {len(album_changes)} '
            f'album art path(s) in the beets database. Continue?', require=True
        ):
            return

        if lib.path.exists():
            backup_path = lib.path.with_name(lib.path.name + '.bak')
            shutil.copy2(lib.path, backup_path)

        with lib.transaction():
            for item, new_path in item_changes:
                item.path = new_path
                item.store()
            for album, new_artpath in album_changes:
                album.artpath = new_artpath
                album.store()

        print('Database paths migrated.')

    # Import-time sidecar recording

    def _on_choice(self, session, task) -> None:

        # Sentinel: nothing to record
        if task.toppath is None or isinstance(task, SentinelImportTask):
            return

        self._session = session
        self._toppaths.add(task.toppath)

        self._pending[id(task)] = {
            'task': task,
            'session': session,
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
                dest_paths=[item.path for item in task.imported_items()],
            )

    def _on_exit(self, lib) -> None:
        # Anything still pending never reached import_task_files: it was skipped
        for rec in self._pending.values():
            self._record(rec, outcome='skipped', release=self._release_id(rec['task']))
        self._pending.clear()

        if self._toppaths and self._in_tagprogress(self._session):
            path = sidecar.sidecar_path(default_state_path())
            with sidecar.lock:
                data = sidecar.load(path)

                for toppath in self._toppaths:
                    sidecar.record_import_done(data, toppath)

                sidecar.save(path, data)

        self._toppaths.clear()
        self._session = None

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
        dest_paths: Optional[list] = None,
    ) -> None:

        path = sidecar.sidecar_path(default_state_path())
        session = rec['session']

        with sidecar.lock:
            data = sidecar.load(path)

            sidecar.record(
                data, rec['paths'], rec['toppath'], outcome,
                choice=rec['task'].choice_flag.name if rec['task'].choice_flag else None,
                operation=operation,
                release=release,
                kind='album' if rec['task'].is_album else 'singleton',
                in_tagprogress=self._in_tagprogress(session),
                in_taghistory=self._in_taghistory(session, outcome),
                dest_paths=dest_paths,
            )
            sidecar.save(path, data)

    @staticmethod
    def _in_tagprogress(session) -> bool:
        return bool(getattr(session, 'want_resume', False)) # True, False or "ask"

    @staticmethod
    def _in_taghistory(session, outcome: str) -> bool:
        cfg = session.config
        if not cfg['incremental']:
            return False
        if outcome == 'skipped' and cfg['incremental_skip_later']:
            return False
        return True
