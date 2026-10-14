import os
import shutil
import hashlib
import time
from pathlib import Path
from typing import List, Dict, Set, Tuple
from models import SyncJob, SyncMode, ConflictPolicy, SyncAction


TRASH_DIR_NAME = ".syncdrive_trash"


class SyncEngine:
    def __init__(self):
        # Human-readable safety warnings from the most recent plan_job() call
        # (e.g. "deletes blocked: target folder could not be fully read").
        self.last_warnings: List[str] = []
        # Per-job memory of which relative file paths existed on BOTH sides as of
        # the last completed (non-dry-run) two-way sync. Without this, plan_job
        # cannot tell "file is new on one side" apart from "file was deleted on
        # one side" — both look identical (missing on one side, present on the
        # other) from a single directory snapshot. That ambiguity is exactly why
        # deleting a file in a two-way job used to resurrect it from the other
        # folder instead of deleting it there too.
        self._known_relpaths: Dict[str, Set[str]] = {}

    @staticmethod
    def calculate_file_hash(filepath: Path, chunk_size: int = 65536) -> str:
        """Calculates SHA-256 hash for precise file integrity checks."""
        hasher = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError:
            return ""

    @staticmethod
    def _resolve_conflict(src_mtime: float, dst_mtime: float, policy: ConflictPolicy) -> str:
        """Determines transfer direction when a file exists in both source and
        target. Takes mtimes directly (already known from the single scan) instead
        of re-stat()'ing the files a third time. Only used as a headless fallback
        when no conflict_resolver is supplied to plan_job (e.g. programmatic/
        non-interactive callers) — the interactive GUI path always asks instead."""
        if policy == ConflictPolicy.SOURCE_WINS:
            return "COPY_TO_TARGET"
        elif policy == ConflictPolicy.TARGET_WINS:
            return "COPY_TO_SOURCE"
        elif policy == ConflictPolicy.SKIP:
            return "SKIP"
        elif policy == ConflictPolicy.KEEP_NEWEST:
            if src_mtime > dst_mtime + 1.0:
                return "COPY_TO_TARGET"
            elif dst_mtime > src_mtime + 1.0:
                return "COPY_TO_SOURCE"
            return "SKIP"
        return "SKIP"

    @staticmethod
    def _scan_with_stats(root: Path, exclude_patterns: List[str]) -> Dict[str, Tuple[int, float]]:
        """Compatibility wrapper: returns just the file map."""
        return SyncEngine._scan_checked(root, exclude_patterns)[0]

    @staticmethod
    def _scan_checked(root: Path, exclude_patterns: List[str]) -> Tuple[Dict[str, Tuple[int, float]], bool]:
        """Walks `root` exactly once and returns {relative_posix_path: (size, mtime)}
        for every file under it.

        Uses os.scandir directly (rather than os.walk + a separate Path.stat()
        call per file) so each DirEntry's cached metadata is reused instead of
        issuing a second stat syscall per file — on Windows, DirEntry.stat()
        is populated from the same directory-listing call that discovered the
        entry, so this avoids a redundant per-file round trip. That matters a
        lot on external/USB/network drives, where a fresh stat() per file is a
        real-latency random-access operation, not a free local call.

        Callers should call this exactly once per root per sync and reuse the
        result — re-walking the same tree multiple times per sync (as the
        previous implementation did) is the single biggest avoidable cost for
        large or slow drives.

        exclude_patterns are checked two ways: as a file-name suffix (so
        ".tmp" skips individual files), AND as an exact (case-insensitive)
        directory name — so "$RECYCLE.BIN" or "System Volume Information"
        skip that entire folder and everything inside it, rather than only
        filtering files whose own name happens to end with that string. That
        second check used to be missing entirely: those default patterns are
        folder names, not file suffixes, so they never matched anything via
        the file-suffix check, and the scan walked straight into the recycle
        bin / OS-reserved folders and synced whatever it found there.
        """
        result: Dict[str, Tuple[int, float]] = {}
        # complete=False means some directory/entry could not be read, so the
        # map may be MISSING files that actually exist. Callers must never
        # treat "absent from an incomplete scan" as "deleted".
        complete = True
        if not root.exists():
            return result, False

        excluded_dir_names = {p.lower() for p in exclude_patterns}
        excluded_dir_names.add(TRASH_DIR_NAME.lower())

        stack = [str(root)]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name.lower() in excluded_dir_names:
                                    continue
                                stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                if any(entry.name.endswith(ext) for ext in exclude_patterns):
                                    continue
                                st = entry.stat(follow_symlinks=False)
                                rel = Path(entry.path).relative_to(root).as_posix()
                                result[rel] = (st.st_size, st.st_mtime)
                        except OSError:
                            # Vanished mid-scan, permission denied, broken link, etc.
                            complete = False
                            continue
            except OSError:
                complete = False
                continue
        return result, complete

    def plan_job(self, job: SyncJob, conflict_resolver=None) -> List[SyncAction]:
        """Calculates exact execution actions without modifying files (Dry-Run / Plan).

        Each source/target pair is scanned exactly once per side (via
        _scan_with_stats), and every comparison — missing files, changed files,
        extra files for Mirror mode, deletions for Two-Way mode — is done
        in-memory against those two dicts. No path is ever stat()'d or walked
        more than once during planning.

        conflict_resolver: optional callable(conflicts: list[dict]) -> dict.
        Called once per source/target pair, with ALL conflicts found for that
        pair (files present on both sides with different size/mtime) — never
        per-file, so a caller can offer a single bulk decision alongside
        per-file overrides instead of being asked once per file. Each conflict
        dict has: relpath, source_path, target_path, src_size, src_mtime,
        dst_size, dst_mtime. Must return {relpath: "COPY_TO_TARGET" |
        "COPY_TO_SOURCE" | "SKIP"} — any relpath not in the returned dict is
        treated as SKIP. If not provided, falls back to automatically deciding
        via job.conflict_policy (used for headless/non-interactive callers).
        """
        actions: List[SyncAction] = []
        self.last_warnings = []

        for src_str in job.sources:
            src_root = Path(src_str)
            if not src_root.exists():
                self.last_warnings.append(f"Source folder not found: {src_root}")
                continue

            for target_str in job.targets:
                dst_root = Path(target_str)
                if not dst_root.exists():
                    self.last_warnings.append(f"Target folder not found: {dst_root}")
                    continue

                src_map, src_ok = self._scan_checked(src_root, job.exclude_patterns)
                dst_map, dst_ok = self._scan_checked(dst_root, job.exclude_patterns)

                # SAFETY: decide whether deletes may be planned at all for this
                # pair. A delete is only trustworthy if BOTH scans were complete
                # and neither side looks wiped (empty while the other is not).
                allow_deletes = True
                if not (src_ok and dst_ok):
                    allow_deletes = False
                    self.last_warnings.append(
                        f"Deletes disabled for {src_root} <-> {dst_root}: a folder could not be fully read "
                        f"(drive disconnected, locked, or permission denied).")
                elif (not src_map and dst_map) or (src_map and not dst_map):
                    if job.mode == SyncMode.ONE_WAY_MIRROR or self._known_relpaths.get(job.id):
                        allow_deletes = False
                        side = "source" if not src_map else "target"
                        self.last_warnings.append(
                            f"Deletes disabled for {src_root} <-> {dst_root}: the {side} folder is EMPTY while the "
                            f"other has files. Refusing to delete anything.")

                # Files present in source: missing-in-target, or present-but-different.
                conflicts: List[Dict] = []
                for rel, (s_size, s_mtime) in src_map.items():
                    src_file = src_root / rel
                    dst_file = dst_root / rel
                    dst_entry = dst_map.get(rel)

                    if dst_entry is None:
                        actions.append(SyncAction(
                            action_type="COPY_TO_TARGET",
                            source_path=str(src_file),
                            target_path=str(dst_file),
                            reason="File missing in target"
                        ))
                    else:
                        d_size, d_mtime = dst_entry
                        if s_size != d_size or abs(s_mtime - d_mtime) > 1.0:
                            conflicts.append({
                                "relpath": rel,
                                "source_path": str(src_file),
                                "target_path": str(dst_file),
                                "src_size": s_size,
                                "src_mtime": s_mtime,
                                "dst_size": d_size,
                                "dst_mtime": d_mtime,
                            })

                if conflicts:
                    if conflict_resolver is not None:
                        resolutions = conflict_resolver(conflicts) or {}
                        reason_text = "Conflict resolved by user"
                    else:
                        resolutions = {
                            c["relpath"]: self._resolve_conflict(c["src_mtime"], c["dst_mtime"], job.conflict_policy)
                            for c in conflicts
                        }
                        reason_text = f"Conflict resolved via policy: {job.conflict_policy.value}"

                    for c in conflicts:
                        decision = resolutions.get(c["relpath"], "SKIP")
                        if decision == "SKIP":
                            continue
                        actions.append(SyncAction(
                            action_type=decision,
                            source_path=c["source_path"],
                            target_path=c["target_path"],
                            reason=reason_text
                        ))

                if job.mode == SyncMode.TWO_WAY_SYNC:
                    known = self._known_relpaths.get(job.id)
                    src_keys = set(src_map)
                    dst_keys = set(dst_map)

                    only_in_target = dst_keys - src_keys
                    for rel in only_in_target:
                        dst_file = dst_root / rel
                        src_file = src_root / rel
                        if allow_deletes and known is not None and rel in known:
                            # Existed on both sides before, missing from source now
                            # -> it was deleted from source. Propagate the delete.
                            actions.append(SyncAction(
                                action_type="DELETE_TARGET",
                                target_path=str(dst_file),
                                reason="Deleted from source — propagating delete (Two-Way Sync)"
                            ))
                        else:
                            actions.append(SyncAction(
                                action_type="COPY_TO_SOURCE",
                                source_path=str(src_file),
                                target_path=str(dst_file),
                                reason="File missing in source (Two-Way Sync)"
                            ))

                    only_in_source = src_keys - dst_keys
                    for rel in only_in_source:
                        src_file = src_root / rel
                        if allow_deletes and known is not None and rel in known:
                            # Existed on both sides before, missing from target now
                            # -> it was deleted from target. Propagate the delete.
                            actions.append(SyncAction(
                                action_type="DELETE_SOURCE",
                                source_path=str(src_file),
                                reason="Deleted from target — propagating delete (Two-Way Sync)"
                            ))
                        # else: already covered above (file present in source,
                        # missing in target -> COPY_TO_TARGET).

                elif job.mode == SyncMode.ONE_WAY_MIRROR and allow_deletes:
                    extra_in_target = set(dst_map) - set(src_map)
                    for rel in extra_in_target:
                        dst_file = dst_root / rel
                        actions.append(SyncAction(
                            action_type="DELETE_TARGET",
                            target_path=str(dst_file),
                            reason="Extra file in target (Mirror mode)"
                        ))

        return actions

    def record_post_sync_state(self, job: SyncJob) -> None:
        """Call after a REAL (non-dry-run) sync completes, for TWO_WAY_SYNC jobs
        only. Snapshots which relative paths now exist on both sides, so the
        next plan_job() call can tell new files apart from deletions instead of
        treating every 'missing on one side' the same way.

        This does its own scan (source and target each walked once) because it
        runs after execute_job_instance has already finished copying/deleting —
        the on-disk state has changed since plan_job's scan, so that earlier
        scan can't be reused here without risking a stale snapshot.
        """
        if job.mode != SyncMode.TWO_WAY_SYNC:
            return
        combined: Set[str] = set()
        for src_str in job.sources:
            src_root = Path(src_str)
            src_keys = set(self._scan_with_stats(src_root, job.exclude_patterns))
            for target_str in job.targets:
                dst_root = Path(target_str)
                dst_keys = set(self._scan_with_stats(dst_root, job.exclude_patterns))
                # Only paths present on both sides count as "known" — anything
                # only on one side didn't successfully sync (e.g. a conflict
                # skip) and shouldn't be assumed stable yet.
                combined |= (src_keys & dst_keys)
        self._known_relpaths[job.id] = combined

    @staticmethod
    def quarantine_file(path: str, job: SyncJob, stamp: str = None) -> str:
        """SAFE delete: MOVE the file into <root>/.syncdrive_trash/<stamp>/<relpath>
        instead of erasing it. Never calls unlink. Returns the new location.
        Raises on any failure (caller must then skip the delete, never fall back
        to permanent removal)."""
        p = Path(path)
        if not p.exists():
            return ""
        stamp = stamp or time.strftime("%Y%m%d_%H%M%S")
        root = None
        for r in list(job.sources) + list(job.targets):
            rp = Path(r)
            try:
                p.relative_to(rp)
                if root is None or len(str(rp)) > len(str(root)):
                    root = rp
            except ValueError:
                continue
        if root is None:
            raise OSError(f"{path} is not inside any job folder; refusing to touch it")
        dest = root / TRASH_DIR_NAME / stamp / p.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}_{int(time.time()*1000)}{dest.suffix}")
        shutil.move(str(p), str(dest))
        return str(dest)

    def execute_job(self, job: SyncJob, dry_run: bool = False, progress_callback=None,
                    allow_deletes: bool = False) -> List[SyncAction]:
        """Executes the planned sync operations. Deletes are skipped unless
        allow_deletes=True, and even then files go to the trash folder."""
        actions = self.plan_job(job)
        if dry_run:
            return actions

        stamp = time.strftime("%Y%m%d_%H%M%S")
        for action in actions:
            if action.action_type in ("DELETE_TARGET", "DELETE_SOURCE") and not allow_deletes:
                continue
            if action.action_type == "COPY_TO_TARGET":
                s = Path(action.source_path)
                d = Path(action.target_path)
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
            elif action.action_type == "COPY_TO_SOURCE":
                s = Path(action.source_path)
                d = Path(action.target_path)
                s.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d, s)
            elif action.action_type == "DELETE_TARGET":
                self.quarantine_file(action.target_path, job, stamp)
            elif action.action_type == "DELETE_SOURCE":
                self.quarantine_file(action.source_path, job, stamp)

            if progress_callback:
                progress_callback(f"Executed: {action.action_type} -> {action.target_path or action.source_path}")

        self.record_post_sync_state(job)
        return actions
