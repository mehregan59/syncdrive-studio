import os
import shutil
import hashlib
from pathlib import Path
from typing import List, Dict, Set, Tuple
from models import SyncJob, SyncMode, ConflictPolicy, SyncAction


class SyncEngine:
    def __init__(self):
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
        of re-stat()'ing the files a third time."""
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
        """
        result: Dict[str, Tuple[int, float]] = {}
        if not root.exists():
            return result

        stack = [str(root)]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                if any(entry.name.endswith(ext) for ext in exclude_patterns):
                                    continue
                                st = entry.stat(follow_symlinks=False)
                                rel = Path(entry.path).relative_to(root).as_posix()
                                result[rel] = (st.st_size, st.st_mtime)
                        except OSError:
                            # Vanished mid-scan, permission denied, broken link, etc.
                            # — skip that one entry rather than aborting the scan.
                            continue
            except OSError:
                continue
        return result

    def plan_job(self, job: SyncJob) -> List[SyncAction]:
        """Calculates exact execution actions without modifying files (Dry-Run / Plan).

        Each source/target pair is scanned exactly once per side (via
        _scan_with_stats), and every comparison — missing files, changed files,
        extra files for Mirror mode, deletions for Two-Way mode — is done
        in-memory against those two dicts. No path is ever stat()'d or walked
        more than once during planning.
        """
        actions: List[SyncAction] = []

        for src_str in job.sources:
            src_root = Path(src_str)
            if not src_root.exists():
                continue

            for target_str in job.targets:
                dst_root = Path(target_str)
                if not dst_root.exists():
                    continue

                src_map = self._scan_with_stats(src_root, job.exclude_patterns)
                dst_map = self._scan_with_stats(dst_root, job.exclude_patterns)

                # Files present in source: missing-in-target, or present-but-different.
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
                            decision = self._resolve_conflict(s_mtime, d_mtime, job.conflict_policy)
                            if decision != "SKIP":
                                actions.append(SyncAction(
                                    action_type=decision,
                                    source_path=str(src_file),
                                    target_path=str(dst_file),
                                    reason=f"Conflict resolved via policy: {job.conflict_policy.value}"
                                ))

                if job.mode == SyncMode.TWO_WAY_SYNC:
                    known = self._known_relpaths.get(job.id)
                    src_keys = set(src_map)
                    dst_keys = set(dst_map)

                    only_in_target = dst_keys - src_keys
                    for rel in only_in_target:
                        dst_file = dst_root / rel
                        src_file = src_root / rel
                        if known is not None and rel in known:
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
                        if known is not None and rel in known:
                            # Existed on both sides before, missing from target now
                            # -> it was deleted from target. Propagate the delete.
                            actions.append(SyncAction(
                                action_type="DELETE_SOURCE",
                                source_path=str(src_file),
                                reason="Deleted from target — propagating delete (Two-Way Sync)"
                            ))
                        # else: already covered above (file present in source,
                        # missing in target -> COPY_TO_TARGET).

                elif job.mode == SyncMode.ONE_WAY_MIRROR:
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

    def execute_job(self, job: SyncJob, dry_run: bool = False, progress_callback=None) -> List[SyncAction]:
        """Executes the planned sync operations."""
        actions = self.plan_job(job)
        if dry_run:
            return actions

        for action in actions:
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
                Path(action.target_path).unlink(missing_ok=True)
            elif action.action_type == "DELETE_SOURCE":
                Path(action.source_path).unlink(missing_ok=True)

            if progress_callback:
                progress_callback(f"Executed: {action.action_type} -> {action.target_path or action.source_path}")

        self.record_post_sync_state(job)
        return actions
