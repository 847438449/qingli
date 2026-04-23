"""删除模块：执行安全删除与模拟删除。"""

from __future__ import annotations

import shutil
from pathlib import Path

from send2trash import send2trash

from models import CleanupItem, DeleteResult, DeletionMode
from scanner import SafeScanner


class SafeDeleter:
    """安全删除器，执行白名单校验。"""

    def __init__(self, scanner: SafeScanner) -> None:
        self.scanner = scanner
        self._direct_allowed = [p.resolve(strict=False) for p, _ in scanner.get_safe_direct_targets()]

    def _is_under_allowed_path(self, path: Path) -> bool:
        rp = path.resolve(strict=False)
        for allowed in self._direct_allowed:
            if rp == allowed or allowed in rp.parents:
                return True
        return False

    def _calc_existing_size(self, path: Path) -> int:
        return self.scanner.get_path_size(path)

    def _delete_direct(self, path: Path) -> None:
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=False)

    def delete_items(self, items: list[CleanupItem], simulate: bool = False) -> list[DeleteResult]:
        """删除清理项。手动确认项优先进入回收站。"""
        results: list[DeleteResult] = []

        for item in items:
            target = Path(item.path)
            try:
                if not target.exists():
                    results.append(DeleteResult(item=item, success=False, error="路径不存在"))
                    continue

                if self.scanner.is_protected(target):
                    results.append(DeleteResult(item=item, success=False, error="目标属于受保护目录"))
                    continue

                # 所有删除都必须位于明确安全范围
                if not self._is_under_allowed_path(target) and item.deletion_mode == DeletionMode.DIRECT_SAFE:
                    results.append(DeleteResult(item=item, success=False, error="不在可直接删除白名单范围"))
                    continue

                size = self._calc_existing_size(target)
                if simulate:
                    results.append(DeleteResult(item=item, success=True, freed_bytes=size))
                    continue

                if item.deletion_mode == DeletionMode.MANUAL_CONFIRM:
                    send2trash(str(target))
                else:
                    if not self._is_under_allowed_path(target):
                        results.append(DeleteResult(item=item, success=False, error="路径不在白名单清理范围"))
                        continue
                    self._delete_direct(target)

                results.append(DeleteResult(item=item, success=True, freed_bytes=size))
            except PermissionError:
                results.append(DeleteResult(item=item, success=False, error="权限不足（可能需要管理员权限）"))
            except Exception as exc:  # noqa: BLE001
                results.append(DeleteResult(item=item, success=False, error=str(exc)))

        return results
