"""
SyncDrive Studio engine — ONE-WAY backup: Main -> Backup.

Safety rules enforced here (not only in the UI):
  * Main is only READ, except for two actions the user must choose explicitly
    per file ("copy to Main" for a backup-only file, "keep Backup version" for
    a conflict). Even then the replaced Main file is first saved in the Backup's
    versions folder.
  * Nothing is ever erased. Replaced/old files go to  <Backup>/.backup_versions/<stamp>/
    and files the user removes go to  <Backup>/.backup_trash/<stamp>/ .
    The only permanent removals in this module are (a) our own half-written
    temp files (*.sbtmp) and (b) empty_folder(), which only runs when the user
    clicks "Empty" and confirms.
  * New copies are written to a temp name, verified (size, optionally SHA-256)
    and only then moved into place, so a failed copy never damages the
    existing file.
  * If a folder cannot be fully read, or Main looks empty while Backup is not,
    the plan is refused instead of guessing.

Comparison strategy (fast first, exact only when needed):
  1. different size                       -> files differ (no hashing needed)
  2. same size, modified time within 2 s  -> treated as identical
  3. same size, different modified time   -> SHA-256 of both decides
     (same content = identical, nothing to do; different = real change)
"""
import os
import time
import shutil
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

VERSIONS_DIR = ".backup_versions"
TRASH_DIR = ".backup_trash"
LEGACY_TRASH_DIR = ".syncdrive_trash"
TEMP_SUFFIX = ".sbtmp"
MTIME_TOLERANCE = 2.0  # seconds (FAT/exFAT store times with 2 s precision)

EXCLUDED_DIR_NAMES = {
    "$recycle.bin", "system volume information",
    VERSIONS_DIR, TRASH_DIR, LEGACY_TRASH_DIR,
}
EXCLUDED_FILE_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
EXCLUDED_SUFFIXES = (".tmp", TEMP_SUFFIX)


@dataclass
class Item:
    rel: str
    main_size: Optional[int] = None
    main_mtime: Optional[float] = None
    backup_size: Optional[int] = None
    backup_mtime: Optional[float] = None
    note: str = ""


@dataclass
class Plan:
    main: str
    backup: str
    new: List[Item] = field(default_factory=list)          # only on Main -> copy to Backup
    updates: List[Item] = field(default_factory=list)      # Main newer -> update Backup (old version saved)
    conflicts: List[Item] = field(default_factory=list)    # differ, Backup NOT older -> user decides
    backup_only: List[Item] = field(default_factory=list)  # only on Backup -> user decides
    identical: int = 0
    hashed: int = 0
    warnings: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class Operation:
    kind: str  # new | update | keep_main | keep_backup | trash | copy_to_main
    item: Item


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def sha256_of(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def stamp_now() -> str:
    return time.strftime("%Y-%m-%d_%H%M%S")


def check_roots(main: Path, backup: Path) -> str:
    """Returns an error message, or '' if the pair is acceptable."""
    if not str(main).strip() or not str(backup).strip():
        return "Please choose both a Main folder and a Backup folder."
    if not main.is_dir():
        return f"Main folder not found or not available: {main}"
    if not backup.is_dir():
        return f"Backup folder not found or not available: {backup}"
    m, b = main.resolve(), backup.resolve()
    if m == b:
        return "Main and Backup are the same folder."
    for a, c, an, cn in ((m, b, "Main", "Backup"), (b, m, "Backup", "Main")):
        try:
            a.relative_to(c)
            return f"{an} folder is inside the {cn} folder. Choose two separate folders."
        except ValueError:
            pass
    return ""


def scan(root: Path, should_stop: Callable[[], bool] = None,
         progress: Callable[[int], None] = None) -> Tuple[Dict[str, Tuple[int, float]], bool]:
    """Walks `root` once. Returns ({relpath: (size, mtime)}, complete).
    complete=False means something could not be read, so the map may be
    missing files that really exist — callers must not trust 'absent'."""
    result: Dict[str, Tuple[int, float]] = {}
    complete = True
    stack = [str(root)]
    n = 0
    while stack:
        if should_stop and should_stop():
            return result, False
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        name_l = e.name.lower()
                        if e.is_dir(follow_symlinks=False):
                            if name_l in EXCLUDED_DIR_NAMES:
                                continue
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            if name_l in EXCLUDED_FILE_NAMES or name_l.endswith(EXCLUDED_SUFFIXES):
                                continue
                            st = e.stat(follow_symlinks=False)
                            rel = Path(e.path).relative_to(root).as_posix()
                            result[rel] = (st.st_size, st.st_mtime)
                            n += 1
                            if progress and n % 500 == 0:
                                progress(n)
                    except OSError:
                        complete = False
        except OSError:
            complete = False
    if progress:
        progress(n)
    return result, complete


# ----------------------------------------------------------------------------
# planning
# ----------------------------------------------------------------------------
def build_plan(main_str: str, backup_str: str,
               should_stop: Callable[[], bool] = None,
               status: Callable[[str], None] = None) -> Plan:
    say = status or (lambda _m: None)
    main, backup = Path(main_str), Path(backup_str)
    plan = Plan(main=main_str, backup=backup_str)

    err = check_roots(main, backup)
    if err:
        plan.error = err
        return plan

    say("Scanning Main...")
    m_map, m_ok = scan(main, should_stop, lambda n: say(f"Scanning Main... {n:,} files"))
    if should_stop and should_stop():
        plan.error = "Cancelled."
        return plan
    say("Scanning Backup...")
    b_map, b_ok = scan(backup, should_stop, lambda n: say(f"Scanning Backup... {n:,} files"))
    if should_stop and should_stop():
        plan.error = "Cancelled."
        return plan

    if not m_ok:
        plan.error = ("Main folder could not be fully read (drive disconnected, locked, or permission denied). "
                      "Nothing was changed. Fix the problem and Analyze again.")
        return plan
    if not b_ok:
        plan.error = ("Backup folder could not be fully read (drive disconnected, locked, or permission denied). "
                      "Nothing was changed. Fix the problem and Analyze again.")
        return plan
    if not m_map and b_map:
        plan.error = ("Main folder is EMPTY but Backup has files. This usually means the wrong folder is selected "
                      "or the drive is not ready. Refusing to continue — nothing was changed.")
        return plan

    both = [r for r in m_map if r in b_map]
    for rel in sorted(r for r in m_map if r not in b_map):
        s, t = m_map[rel]
        plan.new.append(Item(rel, main_size=s, main_mtime=t))

    for rel in sorted(both):
        if should_stop and should_stop():
            plan.error = "Cancelled."
            return plan
        ms, mt = m_map[rel]
        bs, bt = b_map[rel]
        it = Item(rel, ms, mt, bs, bt)
        if ms == bs:
            if abs(mt - bt) <= MTIME_TOLERANCE:
                plan.identical += 1
                continue
            # same size, different time: only the content can tell.
            say(f"Comparing content: {rel}")
            try:
                same = sha256_of(main / rel) == sha256_of(backup / rel)
            except OSError as e:
                plan.warnings.append(f"Could not compare {rel}: {e}")
                continue
            plan.hashed += 1
            if same:
                plan.identical += 1
                continue
            it.note = "Same size, different content"
        else:
            it.note = "Different size"

        if mt > bt + MTIME_TOLERANCE:
            plan.updates.append(it)       # Main is newer: normal update, old Backup copy is kept in versions
        else:
            if bt > mt + MTIME_TOLERANCE:
                it.note += " · Backup copy is NEWER than Main"
            else:
                it.note += " · same date"
            plan.conflicts.append(it)     # Backup newer/same date but different: user must decide

    for rel in sorted(r for r in b_map if r not in m_map):
        s, t = b_map[rel]
        plan.backup_only.append(Item(rel, backup_size=s, backup_mtime=t))

    return plan


# ----------------------------------------------------------------------------
# execution
# ----------------------------------------------------------------------------
def _inside(root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    return dest.with_name(f"{dest.stem}_{int(time.time() * 1000)}{dest.suffix}")


def _copy_verified(src: Path, dst: Path, verify: bool) -> Path:
    """Copies src to a temp file next to dst and verifies it. Returns the temp
    path; the caller moves it into place. dst itself is untouched."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + TEMP_SUFFIX)
    try:
        shutil.copy2(src, tmp)
        if tmp.stat().st_size != src.stat().st_size:
            raise OSError("copy verification failed (size mismatch)")
        if verify and sha256_of(tmp) != sha256_of(src):
            raise OSError("copy verification failed (content mismatch)")
    except BaseException:
        try:
            tmp.unlink()  # our own temp file only
        except OSError:
            pass
        raise
    return tmp


def _move_aside(path: Path, base: Path, rel: str) -> Path:
    dest = _unique(base / rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def apply_operation(op: Operation, main: Path, backup: Path, stamp: str, verify: bool = True) -> str:
    """Performs one operation. Returns a human-readable result line.
    Raises on failure; the caller logs it and carries on with the next file."""
    rel = op.item.rel
    m, b = main / rel, backup / rel
    versions = backup / VERSIONS_DIR / stamp
    trash = backup / TRASH_DIR / stamp

    if not (_inside(main, m) and _inside(backup, b)):
        raise OSError("path escapes its folder; refused")

    if op.kind == "new":
        if b.exists():
            return f"SKIPPED (appeared in Backup meanwhile): {rel}"
        tmp = _copy_verified(m, b, verify)
        os.replace(tmp, b)
        return f"COPIED to Backup: {rel}"

    if op.kind in ("update", "keep_main"):
        tmp = _copy_verified(m, b, verify)           # new version verified FIRST
        old = _move_aside(b, versions, rel) if b.exists() else None
        os.replace(tmp, b)
        return f"UPDATED in Backup: {rel}" + (f"  (old version kept in {VERSIONS_DIR}/{stamp})" if old else "")

    if op.kind == "keep_backup":
        # Backup version wins: copy it to Main. Main's current file is saved first.
        saved = _unique(versions / "_replaced_in_main" / rel)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(m, saved)
        if saved.stat().st_size != m.stat().st_size:
            raise OSError("could not save a safety copy of the Main file; Main left unchanged")
        tmp = _copy_verified(b, m, verify)
        os.replace(tmp, m)
        return (f"MAIN REPLACED with Backup version: {rel}  "
                f"(Main's old file saved in Backup/{VERSIONS_DIR}/{stamp}/_replaced_in_main)")

    if op.kind == "copy_to_main":
        if m.exists():
            return f"SKIPPED (already in Main): {rel}"
        tmp = _copy_verified(b, m, verify)
        os.replace(tmp, m)
        return f"COPIED to Main: {rel}  (Backup copy kept)"

    if op.kind == "trash":
        _move_aside(b, trash, rel)
        return f"MOVED TO BACKUP TRASH: {rel}  -> {TRASH_DIR}/{stamp}"

    raise ValueError(f"unknown operation {op.kind}")


def folder_stats(folder: Path) -> Tuple[int, int]:
    """(file_count, total_bytes) for a versions/trash folder."""
    n = total = 0
    if folder.is_dir():
        for dp, _dn, fn in os.walk(folder):
            for f in fn:
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                    n += 1
                except OSError:
                    pass
    return n, total


def empty_folder(folder: Path, backup_root: Path) -> None:
    """USER-INITIATED permanent removal of the contents of the versions/trash
    folder. Refuses any folder that is not exactly one of those two."""
    if folder.name not in (VERSIONS_DIR, TRASH_DIR) or folder.parent.resolve() != backup_root.resolve():
        raise OSError("refusing to empty a folder that is not the backup's versions/trash folder")
    if folder.is_dir():
        shutil.rmtree(folder)
