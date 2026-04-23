"""扫描模块：负责发现可清理项（安全优先）。"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Callable

from models import CleanupItem, DeletionMode, ItemCategory


MB = 1024 * 1024


@dataclass(slots=True)
class ScanStats:
    """扫描统计信息。"""

    processed_targets: int = 0
    total_targets: int = 1


class SafeScanner:
    """安全优先的 C 盘清理扫描器。"""

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
        """检测是否管理员权限。"""
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def get_safe_direct_targets(self) -> list[tuple[Path, ItemCategory]]:
        """返回可直接删除的白名单目标。"""
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
        """返回建议人工确认的目标目录。"""
        return [
            (self.user_profile / "Downloads", ItemCategory.DOWNLOAD_LARGE_FILE),
            (self.local_appdata, ItemCategory.APPDATA_LARGE_CACHE),
            (self.system_drive / "ProgramData", ItemCategory.INSTALL_RESIDUE),
        ]

    def is_protected(self, path: Path) -> bool:
        """判断路径是否属于受保护目录。"""
        rp = path.resolve(strict=False)
        for protected in self.protected_roots:
            p = protected.resolve(strict=False)
            if rp == p or p in rp.parents:
                return True
        return False

    def get_path_size(self, target: Path) -> int:
        """计算路径大小（字节）。"""
        if not target.exists():
            return 0
        if target.is_file():
            try:
                return target.stat().st_size
            except OSError:
                return 0

        size = 0
        for root, _, files in os.walk(target, topdown=True):
            root_path = Path(root)
            if self.is_protected(root_path):
                continue
            for filename in files:
                file_path = root_path / filename
                try:
                    size += file_path.stat().st_size
                except OSError:
                    continue
        return size

    def _scan_direct_target(self, target: Path, category: ItemCategory) -> CleanupItem | None:
        """扫描可直接删除目标。"""
        if self.is_protected(target):
            return None
        size = self.get_path_size(target)
        if size <= 0:
            return None
        return CleanupItem(
            name=target.name or str(target),
            path=str(target),
            size_bytes=size,
            category=category,
            deletion_mode=DeletionMode.DIRECT_SAFE,
        )

    def _scan_downloads_large_files(self, downloads_dir: Path) -> list[CleanupItem]:
        """扫描下载目录中的大文件（>100MB）。"""
        items: list[CleanupItem] = []
        if not downloads_dir.exists():
            return items

        for child in downloads_dir.iterdir():
            try:
                if child.is_file():
                    size = child.stat().st_size
                    if size >= 100 * MB:
                        items.append(
                            CleanupItem(
                                name=child.name,
                                path=str(child),
                                size_bytes=size,
                                category=ItemCategory.DOWNLOAD_LARGE_FILE,
                                deletion_mode=DeletionMode.MANUAL_CONFIRM,
                            )
                        )
            except OSError:
                continue
        return items

    def _scan_appdata_large_dirs(self, base: Path) -> list[CleanupItem]:
        """扫描 AppData 下体积较大的缓存目录。"""
        items: list[CleanupItem] = []
        keywords = {"cache", "temp", "logs"}
        if not base.exists():
            return items

        try:
            candidates = list(base.iterdir())
        except OSError:
            return items

        for entry in candidates:
            name_lower = entry.name.lower()
            if not entry.is_dir():
                continue
            if not any(k in name_lower for k in keywords):
                continue

            size = self.get_path_size(entry)
            if size < 200 * MB:
                continue
            items.append(
                CleanupItem(
                    name=entry.name,
                    path=str(entry),
                    size_bytes=size,
                    category=ItemCategory.APPDATA_LARGE_CACHE,
                    deletion_mode=DeletionMode.MANUAL_CONFIRM,
                )
            )
        return items

    def _scan_logs_and_residue(self, base: Path) -> list[CleanupItem]:
        """扫描日志文件与安装残留目录。"""
        items: list[CleanupItem] = []
        if not base.exists():
            return items

        for root, dirs, files in os.walk(base, topdown=True):
            root_path = Path(root)
            if self.is_protected(root_path):
                dirs[:] = []
                continue

            for filename in files:
                lower_name = filename.lower()
                if not (lower_name.endswith(".log") or lower_name.endswith(".old")):
                    continue

                file_path = root_path / filename
                try:
                    size = file_path.stat().st_size
                except OSError:
                    continue

                if size < 20 * MB:
                    continue

                items.append(
                    CleanupItem(
                        name=file_path.name,
                        path=str(file_path),
                        size_bytes=size,
                        category=ItemCategory.LOG_FILE,
                        deletion_mode=DeletionMode.MANUAL_CONFIRM,
                    )
                )

            for d in list(dirs):
                lower_dir = d.lower()
                if "install" not in lower_dir and "setup" not in lower_dir:
                    continue
                dir_path = root_path / d
                size = self.get_path_size(dir_path)
                if size < 300 * MB:
                    continue
                items.append(
                    CleanupItem(
                        name=d,
                        path=str(dir_path),
                        size_bytes=size,
                        category=ItemCategory.INSTALL_RESIDUE,
                        deletion_mode=DeletionMode.MANUAL_CONFIRM,
                    )
                )

        return items

    def scan(self, progress_cb: Callable[[int, int, str], None] | None = None) -> list[CleanupItem]:
        """执行全量扫描，返回待清理项。"""
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

        # 去重：按路径
        dedup: dict[str, CleanupItem] = {}
        for item in items:
            existing = dedup.get(item.path)
            if not existing or item.size_bytes > existing.size_bytes:
                dedup[item.path] = item

        return list(dedup.values())
