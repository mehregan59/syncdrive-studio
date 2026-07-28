import os
import shutil
import hashlib
from pathlib import Path
from typing import List, Dict, Set
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
    def _resolve_conflict(src_file: Path, dst_file: Path, policy: ConflictPolicy) -> str:
        """Determines transfer direction when a file exists in both source and target."""
        if policy == ConflictPolicy.SOURCE_WINS:
            return "COPY_TO_TARGET"
        elif policy == ConflictPolicy.TARGET_WINS:
            return "COPY_TO_SOURCE"
        elif policy == ConflictPolicy.SKIP:
            return "SKIP"
        elif policy == ConflictPolicy.KEEP_NEWEST:
            src_mtime = src_file.stat().st_mtime
            dst_mtime = dst_file.stat().st_mtime
            if src_mtime > dst_mtime + 1.0:
                return "COPY_TO_TARGET"
            elif dst_mtime > src_mtime + 1.0:
                return "COPY_TO_SOURCE"
            return "SKIP"
        return "SKIP"

    @staticmethod
    def _scan_relpaths(root: Path, exclude_patterns: List[str]) -> Set[str]:
        """Returns the set of file paths under root, relative to root, as POSIX strings."""
        found: Set[str] = set()
        if not root.exists():
            return found
        for r, _, files in os.walk(root):
            for file in files:
                if any(file.endswith(ext) for ext in exclude_patterns):
                    continue
                rel = (Path(r) / file).relative_to(root).as_posix()
                found.add(rel)
        return found

    def plan_job(self, job: SyncJob) -> List[SyncAction]:
        """Calculates exact execution actions without modifying files (Dry-Run / Plan)."""
        actions: List[SyncAction] = []

        for src_str in job.sources:
            src_root = Path(src_str)
            if not src_root.exists():
                continue

            for target_str in job.targets:
                dst_root = Path(target_str)
                if not dst_root.exists():
                    continue

                for root, _, files in os.walk(src_root):
                    rel_path = Path(root).relative_to(src_root)
                    dst_dir = dst_root / rel_path

                    for file in files:
                        if any(file.endswith(ext) for ext in job.exclude_patterns):
                            continue

                        src_file = Path(root) / file
                        dst_file = dst_dir / file

                        if not dst_file.exists():
                            actions.append(SyncAction(
                                action_type="COPY_TO_TARGET",
                                source_path=str(src_file),
                                target_path=str(dst_file),
                                reason="File missing in target"
                            ))
                        else:
                            src_stat = src_file.stat()
                            dst_stat = dst_file.stat()
                            if src_stat.st_size != dst_stat.st_size or abs(src_stat.st_mtime - dst_stat.st_mtime) > 1.0:
                                decision = self._resolve_conflict(src_file, dst_file, job.conflict_policy)
                                if decision != "SKIP":
                                    actions.append(SyncAction(
                                        action_type=decision,
                                        source_path=str(src_file),
                                        target_path=str(dst_file),
                                        reason=f"Conflict resolved via policy: {job.conflict_policy.value}"
                                    ))

                if job.mode == SyncMode.TWO_WAY_SYNC:
                    # Rebuilt below using known-state comparison instead of a
                    # one-directional "missing in source -> copy from target"
                    # walk, so deletions can be told apart from new files.
                    known = self._known_relpaths.get(job.id)
                    src_relset = self._scan_relpaths(src_root, job.exclude_patterns)
                    dst_relset = self._scan_relpaths(dst_root, job.exclude_patterns)

                    only_in_target = dst_relset - src_relset
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

                    only_in_source = src_relset - dst_relset
                    for rel in only_in_source:
                        src_file = src_root / rel
                        dst_file = dst_root / rel
                        if known is not None and rel in known:
                            # Existed on both sides before, missing from target now
                            # -> it was deleted from target. Propagate the delete.
                            actions.append(SyncAction(
                                action_type="DELETE_SOURCE",
                                source_path=str(src_file),
                                reason="Deleted from target — propagating delete (Two-Way Sync)"
                            ))
                        # else: this is already covered by the first COPY_TO_TARGET
                        # walk above (file present in source, missing in target).

                elif job.mode == SyncMode.ONE_WAY_MIRROR:
                    for root, _, files in os.walk(dst_root):
                        rel_path = Path(root).relative_to(dst_root)
                        src_dir = src_root / rel_path

                        for file in files:
                            dst_file = Path(root) / file
                            src_file = src_dir / file
                            if not src_file.exists():
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
        treating every 'missing on one side' the same way."""
        if job.mode != SyncMode.TWO_WAY_SYNC:
            return
        combined: Set[str] = set()
        for src_str in job.sources:
            src_root = Path(src_str)
            src_relset = self._scan_relpaths(src_root, job.exclude_patterns)
            for target_str in job.targets:
                dst_root = Path(target_str)
                dst_relset = self._scan_relpaths(dst_root, job.exclude_patterns)
                # Only paths present on both sides count as "known" — anything
                # only on one side didn't successfully sync (e.g. a conflict
                # skip) and shouldn't be assumed stable yet.
                combined |= (src_relset & dst_relset)
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
