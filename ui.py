"""Tkinter 图形界面。"""

from __future__ import annotations

import csv
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from deleter import SafeDeleter
from models import CleanupItem, DeleteResult, DeletionMode
from scanner import MB, SafeScanner


class CleanerUI:
    """清理工具主界面。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("安全优先 C 盘清理工具")
        self.root.geometry("1180x700")

        self.scanner = SafeScanner()
        self.deleter = SafeDeleter(self.scanner)
        self.all_items: list[CleanupItem] = []
        self.filtered_items: list[CleanupItem] = []
        self.check_vars: dict[str, tk.BooleanVar] = {}

        self.only_large_var = tk.BooleanVar(value=False)
        self.simulate_var = tk.BooleanVar(value=False)
        self.sort_desc_var = tk.BooleanVar(value=True)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="准备就绪")

        self._build_ui()
        self._show_admin_status()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        ttk.Button(top, text="开始扫描", command=self.start_scan).pack(side=tk.LEFT, padx=5)
        ttk.Button(top, text="导出 CSV 报告", command=self.export_csv).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(top, text="模拟删除模式", variable=self.simulate_var).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(top, text="按大小排序（降序）", variable=self.sort_desc_var, command=self.apply_filters).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(top, text="只看 > 100MB", variable=self.only_large_var, command=self.apply_filters).pack(side=tk.LEFT, padx=8)

        action_bar = ttk.Frame(self.root, padding=(10, 0))
        action_bar.pack(fill=tk.X)
        ttk.Button(action_bar, text="全选建议清理项", command=self.select_manual_items).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_bar, text="取消全选", command=self.unselect_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_bar, text="删除勾选项（优先回收站）", command=self.delete_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_bar, text="一键直接删除安全项", command=self.delete_direct_safe).pack(side=tk.LEFT, padx=5)

        columns = ("selected", "name", "path", "size", "category", "mode")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", height=24)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.tree.heading("selected", text="选择")
        self.tree.heading("name", text="名称")
        self.tree.heading("path", text="完整路径")
        self.tree.heading("size", text="大小")
        self.tree.heading("category", text="分类")
        self.tree.heading("mode", text="删除模式")

        self.tree.column("selected", width=55, anchor=tk.CENTER)
        self.tree.column("name", width=220)
        self.tree.column("path", width=420)
        self.tree.column("size", width=120, anchor=tk.E)
        self.tree.column("category", width=140)
        self.tree.column("mode", width=120)

        self.tree.bind("<Double-1>", self._toggle_item_checked)

        bottom = ttk.Frame(self.root, padding=10)
        bottom.pack(fill=tk.X)
        ttk.Progressbar(bottom, variable=self.progress_var, maximum=100).pack(fill=tk.X, pady=(0, 8))
        ttk.Label(bottom, textvariable=self.status_var).pack(anchor=tk.W)

    def _show_admin_status(self) -> None:
        is_admin = self.scanner.is_admin()
        status = "管理员权限：是" if is_admin else "管理员权限：否（部分系统目录可能无法删除）"
        self.status_var.set(status)

    @staticmethod
    def format_size(size: int) -> str:
        """字节转可读大小。"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024 or unit == "TB":
                return f"{size:.2f} {unit}" if unit != "B" else f"{size} B"
            size /= 1024
        return f"{size:.2f} TB"

    def start_scan(self) -> None:
        """启动后台扫描线程。"""
        self.status_var.set("正在扫描...")
        self.progress_var.set(0)
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
        """后台扫描逻辑。"""

        def on_progress(done: int, total: int, text: str) -> None:
            percent = 0 if total <= 0 else done / total * 100
            self.root.after(0, self.progress_var.set, percent)
            self.root.after(0, self.status_var.set, text)

        items = self.scanner.scan(progress_cb=on_progress)
        self.all_items = items
        self.root.after(0, self._after_scan)

    def _after_scan(self) -> None:
        self.apply_filters()
        total_size = sum(item.size_bytes for item in self.all_items)
        self.progress_var.set(100)
        self.status_var.set(f"扫描完成：共 {len(self.all_items)} 项，可释放 {self.format_size(total_size)}")

    def apply_filters(self) -> None:
        """应用筛选与排序。"""
        items = self.all_items
        if self.only_large_var.get():
            items = [x for x in items if x.size_bytes >= 100 * MB]

        items = sorted(items, key=lambda x: x.size_bytes, reverse=self.sort_desc_var.get())
        self.filtered_items = items
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)

        for idx, item in enumerate(self.filtered_items):
            key = item.path
            if key not in self.check_vars:
                self.check_vars[key] = tk.BooleanVar(value=False)
            checked = "☑" if self.check_vars[key].get() else "☐"
            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    checked,
                    item.name,
                    item.path,
                    self.format_size(item.size_bytes),
                    item.category.value,
                    item.deletion_mode.value,
                ),
            )

    def _toggle_item_checked(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item_id or col != "#1":
            return

        idx = int(item_id)
        if idx >= len(self.filtered_items):
            return
        target = self.filtered_items[idx]
        var = self.check_vars[target.path]
        var.set(not var.get())
        self._refresh_tree()

    def select_manual_items(self) -> None:
        """全选建议人工确认项。"""
        for item in self.filtered_items:
            if item.deletion_mode == DeletionMode.MANUAL_CONFIRM:
                self.check_vars.setdefault(item.path, tk.BooleanVar()).set(True)
        self._refresh_tree()

    def unselect_all(self) -> None:
        """取消所有勾选。"""
        for var in self.check_vars.values():
            var.set(False)
        self._refresh_tree()

    def _get_checked_items(self) -> list[CleanupItem]:
        return [item for item in self.filtered_items if self.check_vars.get(item.path, tk.BooleanVar(value=False)).get()]

    def _confirm_delete(self, items: list[CleanupItem]) -> bool:
        names = "\n".join(f"- {item.name}" for item in items[:15])
        if len(items) > 15:
            names += "\n..."
        return messagebox.askyesno("确认删除", f"即将删除以下项目：\n{names}\n\n是否继续？")

    def _show_results(self, results: list[DeleteResult]) -> None:
        success_items = [r for r in results if r.success]
        failed_items = [r for r in results if not r.success]
        freed = sum(r.freed_bytes for r in success_items)

        msg = [f"删除完成。实际释放空间：{self.format_size(freed)}"]
        if failed_items:
            msg.append("\n失败项目：")
            for fail in failed_items:
                msg.append(f"- {fail.item.name}: {fail.error}")

        messagebox.showinfo("删除结果", "\n".join(msg))
        self.start_scan()

    def delete_selected(self) -> None:
        """删除手动勾选项。"""
        items = self._get_checked_items()
        if not items:
            messagebox.showwarning("提示", "请先勾选要删除的项目。")
            return
        if not self._confirm_delete(items):
            return

        results = self.deleter.delete_items(items, simulate=self.simulate_var.get())
        self._show_results(results)

    def delete_direct_safe(self) -> None:
        """一键删除全部可直接删除项。"""
        items = [x for x in self.filtered_items if x.deletion_mode == DeletionMode.DIRECT_SAFE]
        if not items:
            messagebox.showwarning("提示", "当前无可直接删除的安全项。")
            return
        if not self._confirm_delete(items):
            return
        results = self.deleter.delete_items(items, simulate=self.simulate_var.get())
        self._show_results(results)

    def export_csv(self) -> None:
        """导出扫描报告 CSV。"""
        if not self.filtered_items:
            messagebox.showwarning("提示", "暂无可导出数据，请先扫描。")
            return

        path = filedialog.asksaveasfilename(
            title="导出扫描报告",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            initialfile="cleanup_report.csv",
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["名称", "完整路径", "大小(字节)", "大小(可读)", "分类", "删除模式"])
                for item in self.filtered_items:
                    writer.writerow(
                        [
                            item.name,
                            item.path,
                            item.size_bytes,
                            self.format_size(item.size_bytes),
                            item.category.value,
                            item.deletion_mode.value,
                        ]
                    )
            messagebox.showinfo("成功", f"报告已导出：{Path(path)}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导出失败", str(exc))
