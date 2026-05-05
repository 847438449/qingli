"""数据模型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ItemCategory(str, Enum):
    """清理项分类。"""

    USER_TEMP = "用户 TEMP"
    WINDOWS_TEMP = "Windows Temp"
    WINDOWS_UPDATE_CACHE = "Windows 更新缓存"
    CRASH_DUMPS = "CrashDumps"
    BROWSER_CACHE = "浏览器缓存"
    DOWNLOAD_LARGE_FILE = "下载目录大文件"
    APPDATA_LARGE_CACHE = "AppData 大缓存"
    LOG_FILE = "日志文件"
    INSTALL_RESIDUE = "安装残留目录"


class DeletionMode(str, Enum):
    """删除模式。"""

    DIRECT_SAFE = "可直接删除"
    MANUAL_CONFIRM = "建议人工确认"


class ScanItemType(str, Enum):
    """扫描项类型。"""

    FILE = "file"
    FOLDER = "folder"


@dataclass(slots=True)
class CleanupItem:
    """单个待清理项。"""

    name: str
    path: str
    size_bytes: int
    category: ItemCategory
    deletion_mode: DeletionMode


@dataclass(slots=True)
class LargeScanItem:
    """大文件/大文件夹扫描结果项。"""

    item_type: ScanItemType
    name: str
    path: str
    size_bytes: int
    modified_at: datetime
    file_count: int | None = None
    extension: str = ""
    is_dev_residue: bool = False


@dataclass(slots=True)
class DeleteResult:
    """删除结果。"""

    name: str
    path: str
    success: bool
    freed_bytes: int = 0
    error: str | None = None
