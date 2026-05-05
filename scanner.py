"""扫描模块：负责垃圾清理项和大文件/大文件夹扫描。"""

from __future__ import annotations

import ctypes
import heapq
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from models import CleanupItem, DeletionMode, ItemCategory, LargeScanItem, ScanItemType


MB = 1024 * 1024
GB = 1024 * MB
PRIORITY_EXTENSIONS = {".zip", ".rar", ".7z", ".iso", ".mp4", ".mkv", ".avi", ".log", ".tmp", ".dmp", ".exe", ".msi"}
DEV_RESIDUE_DIRS = {"node_modules", "venv", ".venv", "__pycache__", "build", "dist"}


def format_size(size_bytes: int) -> str:
    """将字节转为可读字符串。"""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


class SafeScanner:
    """安全优先扫描器。"""

    def __init__(self) -> None:
        self.system_drive = Path(os.environ.get("SystemDrive", "C:"))
        self.user_profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        self.local_appdata = Path(os.environ.get("LOCALAPPDATA", str(self.user_profile / "AppData" / "Local")))
        self.appdata = Path(os.environ.get("APPDATA", str(self.user_profile / "AppData" / "Roaming")))
        self.win_dir = Path(os.environ.get("WINDIR", str(self.system_drive / "Windows")))

        self.protected_roots = {
            self.win_dir / "System32",
            self.system_drive / "Program Files",
            self.system_drive / "Program Files (x86)",
            self.user_profile / "Desktop",
            self.user_profile / "Documents",
        }

    @staticmethod
    def is_admin() -> bool:
        """检测管理员权限。"""
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def get_safe_direct_targets(self) -> list[tuple[Path, ItemCategory]]:
        """可直接删除白名单目标。"""
        return [
            (Path(os.environ.get("TEMP", str(self.local_appdata / "Temp"))), ItemCategory.USER_TEMP),
            (self.win_dir / "Temp", ItemCategory.WINDOWS_TEMP),
            (self.win_dir / "SoftwareDistribution" / "Download", ItemCategory.WINDOWS_UPDATE_CACHE),
            (self.win_dir / "Minidump", ItemCategory.CRASH_DUMPS),
            (self.system_drive / "CrashDumps", ItemCategory.CRASH_DUMPS),
            (self.local_appdata / "Google" / "Chrome" / "User Data" / "Default" / "Cache", ItemCategory.BROWSER_CACHE),
            (self.local_appdata / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache", ItemCategory.BROWSER_CACHE),
            (self.local_appdata / "Microsoft" / "Windows" / "INetCache", ItemCategory.BROWSER_CACHE),
        ]

    def get_manual_targets(self) -> list[tuple[Path, ItemCategory]]:
        """建议人工确认目标。"""
        return [
            (self.user_profile / "Downloads", ItemCategory.DOWNLOAD_LARGE_FILE),
            (self.local_appdata, ItemCategory.APPDATA_LARGE_CACHE),
            (self.system_drive / "ProgramData", ItemCategory.INSTALL_RESIDUE),
        ]

    def get_default_scan_roots(self) -> list[Path]:
        """大文件扫描默认根目录。"""
        roots = [
            self.user_profile / "Downloads",
            self.user_profile / "Desktop",
            self.user_profile / "Documents",
            self.user_profile / "Videos",
            self.user_profile / "Pictures",
            self.local_appdata,
            self.appdata,
        ]
        return [p for p in roots if p.exists()]

    def get_skip_dirs(self) -> set[Path]:
        """大文件扫描跳过目录。"""
        return {
            self.win_dir,
            self.system_drive / "Program Files",
            self.system_drive / "Program Files (x86)",
            self.system_drive / "ProgramData",
        }

    def is_protected(self, path: Path) -> bool:
        """检查是否为保护目录。"""
        rp = path.resolve(strict=False)
        for protected in self.protected_roots:
            p = protected.resolve(strict=False)
            if rp == p or p in rp.parents:
                return True
        return False

    def _is_under_skip_dir(self, path: Path) -> bool:
        rp = path.resolve(strict=False)
        for skip in self.get_skip_dirs():
            sp = skip.resolve(strict=False)
            if rp == sp or sp in rp.parents:
                return True
        return False

    def get_path_size(self, target: Path) -> int:
        """计算路径大小。"""
        if not target.exists():
            return 0
        if target.is_file():
            try:
                return target.stat().st_size
            except OSError:
                return 0

        total = 0
        for root, dirs, files in os.walk(target, topdown=True):
            root_path = Path(root)
            if self.is_protected(root_path) or self._is_under_skip_dir(root_path):
                dirs[:] = []
                continue
            for name in files:
                fp = root_path / name
                try:
                    total += fp.stat().st_size
                except (OSError, PermissionError, FileNotFoundError):
                    continue
        return total

    def _scan_direct_target(self, target: Path, category: ItemCategory) -> CleanupItem | None:
        if self.is_protected(target):
            return None
        size = self.get_path_size(target)
        if size <= 0:
            return None
        return CleanupItem(target.name or str(target), str(target), size, category, DeletionMode.DIRECT_SAFE)

    def _scan_downloads_large_files(self, downloads_dir: Path) -> list[CleanupItem]:
        items: list[CleanupItem] = []
        if not downloads_dir.exists():
            return items
        try:
            children = list(downloads_dir.iterdir())
        except OSError:
            return items

        for child in children:
            try:
                if child.is_file():
                    size = child.stat().st_size
                    if size >= 100 * MB:
                        items.append(CleanupItem(child.name, str(child), size, ItemCategory.DOWNLOAD_LARGE_FILE, DeletionMode.MANUAL_CONFIRM))
            except (OSError, PermissionError, FileNotFoundError):
                continue
        return items

    def _scan_appdata_large_dirs(self, base: Path) -> list[CleanupItem]:
        items: list[CleanupItem] = []
        if not base.exists():
            return items
        try:
            candidates = list(base.iterdir())
        except OSError:
            return items

        for entry in candidates:
            try:
                if not entry.is_dir():
                    continue
                if not any(k in entry.name.lower() for k in {"cache", "temp", "logs"}):
                    continue
                size = self.get_path_size(entry)
                if size >= 200 * MB:
                    items.append(CleanupItem(entry.name, str(entry), size, ItemCategory.APPDATA_LARGE_CACHE, DeletionMode.MANUAL_CONFIRM))
            except (OSError, PermissionError, FileNotFoundError):
                continue
        return items

    def _scan_logs_and_residue(self, base: Path) -> list[CleanupItem]:
        items: list[CleanupItem] = []
        if not base.exists():
            return items

        for root, dirs, files in os.walk(base, topdown=True):
            root_path = Path(root)
            if self.is_protected(root_path) or self._is_under_skip_dir(root_path):
                dirs[:] = []
                continue

            for filename in files:
                lower = filename.lower()
                if not (lower.endswith(".log") or lower.endswith(".old")):
                    continue
                fp = root_path / filename
                try:
                    size = fp.stat().st_size
                    if size >= 20 * MB:
                        items.append(CleanupItem(fp.name, str(fp), size, ItemCategory.LOG_FILE, DeletionMode.MANUAL_CONFIRM))
                except (OSError, PermissionError, FileNotFoundError):
                    continue

            for d in list(dirs):
                if "install" not in d.lower() and "setup" not in d.lower():
                    continue
                dp = root_path / d
                size = self.get_path_size(dp)
                if size >= 300 * MB:
                    items.append(CleanupItem(d, str(dp), size, ItemCategory.INSTALL_RESIDUE, DeletionMode.MANUAL_CONFIRM))

        return items

    def scan(self, progress_cb: Callable[[int, int, str], None] | None = None) -> list[CleanupItem]:
        """原有垃圾清理扫描。"""
        items: list[CleanupItem] = []
        direct_targets = self.get_safe_direct_targets()
        manual_targets = self.get_manual_targets()
        total = len(direct_targets) + len(manual_targets)
        done = 0

        for target, category in direct_targets:
            done += 1
            if progress_cb:
                progress_cb(done, total, f"扫描: {target}")
            result = self._scan_direct_target(target, category)
            if result:
                items.append(result)

        for target, category in manual_targets:
            done += 1
            if progress_cb:
                progress_cb(done, total, f"扫描: {target}")
            if category == ItemCategory.DOWNLOAD_LARGE_FILE:
                items.extend(self._scan_downloads_large_files(target))
            elif category == ItemCategory.APPDATA_LARGE_CACHE:
                items.extend(self._scan_appdata_large_dirs(target))
            elif category == ItemCategory.INSTALL_RESIDUE:
                items.extend(self._scan_logs_and_residue(target))

        dedup: dict[str, CleanupItem] = {}
        for item in items:
            if item.path not in dedup or item.size_bytes > dedup[item.path].size_bytes:
                dedup[item.path] = item
        return list(dedup.values())

    def scan_large_files(
        self,
        min_size_bytes: int = 100 * MB,
        max_results: int = 1000,
        progress_cb: Callable[[str], None] | None = None,
    ) -> list[LargeScanItem]:
        """扫描大文件。"""
        heap: list[tuple[int, LargeScanItem]] = []
        for root in self.get_default_scan_roots():
            if progress_cb:
                progress_cb(f"扫描大文件: {root}")
            for current_root, dirs, files in os.walk(root, topdown=True):
                current = Path(current_root)
                if self._is_under_skip_dir(current):
                    dirs[:] = []
                    continue
                for filename in files:
                    fp = current / filename
                    try:
                        stat = fp.stat()
                    except (OSError, PermissionError, FileNotFoundError):
                        continue
                    if stat.st_size < min_size_bytes:
                        continue

                    ext = fp.suffix.lower()
                    item = LargeScanItem(
                        item_type=ScanItemType.FILE,
                        name=fp.name,
                        path=str(fp),
                        size_bytes=stat.st_size,
                        modified_at=datetime.fromtimestamp(stat.st_mtime),
                        extension=ext,
                        is_dev_residue=any(part.lower() in DEV_RESIDUE_DIRS for part in fp.parts),
                    )
                    heapq.heappush(heap, (item.size_bytes, item))
                    if len(heap) > max_results:
                        heapq.heappop(heap)

        result = [h[1] for h in heap]
        result.sort(key=lambda x: x.size_bytes, reverse=True)
        return result

    def scan_large_folders(
        self,
        min_size_bytes: int = 500 * MB,
        max_results: int = 300,
        progress_cb: Callable[[str], None] | None = None,
    ) -> list[LargeScanItem]:
        """扫描大文件夹（含开发残留优先识别）。"""
        candidates: list[LargeScanItem] = []

        for root in self.get_default_scan_roots():
            if progress_cb:
                progress_cb(f"扫描大文件夹: {root}")
            folder_sizes: dict[str, int] = {}
            folder_files: dict[str, int] = {}

            for current_root, dirs, files in os.walk(root, topdown=False):
                current = Path(current_root)
                if self._is_under_skip_dir(current):
                    continue

                direct_size = 0
                direct_count = 0
                for filename in files:
                    fp = current / filename
                    try:
                        direct_size += fp.stat().st_size
                        direct_count += 1
                    except (OSError, PermissionError, FileNotFoundError):
                        continue

                total_size = direct_size
                total_files = direct_count
                for d in dirs:
                    child = str(current / d)
                    total_size += folder_sizes.get(child, 0)
                    total_files += folder_files.get(child, 0)

                key = str(current)
                folder_sizes[key] = total_size
                folder_files[key] = total_files

                lower_name = current.name.lower()
                is_dev = lower_name in DEV_RESIDUE_DIRS
                threshold = 50 * MB if is_dev else min_size_bytes
                if total_size >= threshold:
                    try:
                        mtime = datetime.fromtimestamp(current.stat().st_mtime)
                    except (OSError, PermissionError, FileNotFoundError):
                        mtime = datetime.now()
                    candidates.append(
                        LargeScanItem(
                            item_type=ScanItemType.FOLDER,
                            name=current.name or str(current),
                            path=key,
                            size_bytes=total_size,
                            modified_at=mtime,
                            file_count=total_files,
                            is_dev_residue=is_dev,
                        )
                    )

        candidates.sort(key=lambda x: (not x.is_dev_residue, -x.size_bytes))
        dedup: dict[str, LargeScanItem] = {}
        for item in candidates:
            dedup[item.path] = item
        result = list(dedup.values())
        result.sort(key=lambda x: (not x.is_dev_residue, -x.size_bytes))
        return result[:max_results]
