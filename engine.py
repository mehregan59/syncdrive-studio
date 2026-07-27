import os
import shutil
import hashlib
from pathlib import Path
from typing import List
from models import SyncJob, SyncMode, ConflictPolicy, SyncAction


class SyncEngine:
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
                    for root, _, files in os.walk(dst_root):
                        rel_path = Path(root).relative_to(dst_root)
                        src_dir = src_root / rel_path

                        for file in files:
                            if any(file.endswith(ext) for ext in job.exclude_patterns):
                                continue

                            dst_file = Path(root) / file
                            src_file = src_dir / file

                            if not src_file.exists():
                                actions.append(SyncAction(
                                    action_type="COPY_TO_SOURCE",
                                    source_path=str(src_file),
                                    target_path=str(dst_file),
                                    reason="File missing in source (Two-Way Sync)"
                                ))

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

            if progress_callback:
                progress_callback(f"Executed: {action.action_type} -> {action.target_path or action.source_path}")

        return actions
