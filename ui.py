"""Tkinter 图形界面。"""

from __future__ import annotations

import csv
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from deleter import SafeDeleter
from models import CleanupItem, DeleteResult, DeletionMode, LargeScanItem, ScanItemType
from scanner import GB, MB, PRIORITY_EXTENSIONS, SafeScanner, format_size


class CleanerUI:
    """清理工具主界面。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("安全优先 C 盘清理工具")
        self.root.geometry("1300x760")

        self.scanner = SafeScanner()
        self.deleter = SafeDeleter(self.scanner)

        self.all_items: list[CleanupItem] = []
        self.filtered_items: list[CleanupItem] = []
        self.check_vars: dict[str, tk.BooleanVar] = {}

        self.large_results: list[LargeScanItem] = []
        self.large_filtered: list[LargeScanItem] = []
        self.large_check_vars: dict[str, tk.BooleanVar] = {}

        self.only_large_var = tk.BooleanVar(value=False)
        self.simulate_var = tk.BooleanVar(value=False)
        self.sort_desc_var = tk.BooleanVar(value=True)

        self.filter_only_files = tk.BooleanVar(value=False)
        self.filter_only_folders = tk.BooleanVar(value=False)
        self.filter_over_1gb = tk.BooleanVar(value=False)
        self.filter_30_days = tk.BooleanVar(value=False)
        self.filter_180_days = tk.BooleanVar(value=False)
        self.filter_priority_ext = tk.BooleanVar(value=False)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="准备就绪")

        self.cleanup_buttons: list[ttk.Button] = []
        self.large_scan_button: ttk.Button | None = None
        self.large_delete_button: ttk.Button | None = None

        self._build_ui()
        self._show_admin_status()

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True)

        cleanup_tab = ttk.Frame(notebook)
        large_tab = ttk.Frame(notebook)
        notebook.add(cleanup_tab, text="垃圾清理")
        notebook.add(large_tab, text="大文件/大文件夹")

        self._build_cleanup_tab(cleanup_tab)
        self._build_large_tab(large_tab)

        bottom = ttk.Frame(self.root, padding=10)
        bottom.pack(fill=tk.X)
        ttk.Progressbar(bottom, variable=self.progress_var, maximum=100).pack(fill=tk.X, pady=(0, 8))
        ttk.Label(bottom, textvariable=self.status_var).pack(anchor=tk.W)

    def _build_cleanup_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, padding=10)
        top.pack(fill=tk.X)

        btn_scan = ttk.Button(top, text="开始扫描", command=self.start_scan)
        btn_export = ttk.Button(top, text="导出 CSV 报告", command=self.export_csv)
        btn_scan.pack(side=tk.LEFT, padx=5)
        btn_export.pack(side=tk.LEFT, padx=5)
        self.cleanup_buttons.extend([btn_scan, btn_export])

        ttk.Checkbutton(top, text="模拟删除模式", variable=self.simulate_var).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(top, text="按大小排序（降序）", variable=self.sort_desc_var, command=self.apply_filters).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(top, text="只看 > 100MB", variable=self.only_large_var, command=self.apply_filters).pack(side=tk.LEFT, padx=8)

        action_bar = ttk.Frame(parent, padding=(10, 0))
        action_bar.pack(fill=tk.X)
        btn_select = ttk.Button(action_bar, text="全选建议清理项", command=self.select_manual_items)
        btn_unselect = ttk.Button(action_bar, text="取消全选", command=self.unselect_all)
        btn_delete = ttk.Button(action_bar, text="删除勾选项（优先回收站）", command=self.delete_selected)
        btn_direct = ttk.Button(action_bar, text="一键直接删除安全项", command=self.delete_direct_safe)
        btn_select.pack(side=tk.LEFT, padx=5)
        btn_unselect.pack(side=tk.LEFT, padx=5)
        btn_delete.pack(side=tk.LEFT, padx=5)
        btn_direct.pack(side=tk.LEFT, padx=5)
        self.cleanup_buttons.extend([btn_select, btn_unselect, btn_delete, btn_direct])

        columns = ("selected", "name", "path", "size", "category", "mode")
        self.tree = ttk.Treeview(parent, columns=columns, show="headings", height=22)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        for key, title, width in [
            ("selected", "选择", 55),
            ("name", "名称", 220),
            ("path", "完整路径", 470),
            ("size", "大小", 120),
            ("category", "分类", 160),
            ("mode", "删除模式", 120),
        ]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=tk.CENTER if key == "selected" else tk.W)

        self.tree.column("size", anchor=tk.E)
        self.tree.bind("<Double-1>", self._toggle_cleanup_checked)

    def _build_large_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, padding=10)
        top.pack(fill=tk.X)

        self.large_scan_button = ttk.Button(top, text="扫描大文件/大文件夹", command=self.start_large_scan)
        self.large_scan_button.pack(side=tk.LEFT, padx=5)

        self.large_delete_button = ttk.Button(top, text="删除所选项（回收站）", command=self.delete_large_selected)
        self.large_delete_button.pack(side=tk.LEFT, padx=5)

        ttk.Checkbutton(top, text="仅文件", variable=self.filter_only_files, command=self.apply_large_filters).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(top, text="仅文件夹", variable=self.filter_only_folders, command=self.apply_large_filters).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(top, text="> 1GB", variable=self.filter_over_1gb, command=self.apply_large_filters).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(top, text=">30天未修改", variable=self.filter_30_days, command=self.apply_large_filters).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(top, text=">180天未修改", variable=self.filter_180_days, command=self.apply_large_filters).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(top, text="优先扩展名", variable=self.filter_priority_ext, command=self.apply_large_filters).pack(side=tk.LEFT, padx=5)

        columns = ("selected", "type", "name", "path", "size", "modified", "file_count", "tag")
        self.large_tree = ttk.Treeview(parent, columns=columns, show="headings", height=22)
        self.large_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        headers = {
            "selected": ("选择", 55),
            "type": ("类型", 70),
            "name": ("名称", 180),
            "path": ("完整路径", 450),
            "size": ("大小", 120),
            "modified": ("最后修改时间", 170),
            "file_count": ("文件数", 100),
            "tag": ("标记", 120),
        }
        for key, (title, width) in headers.items():
            self.large_tree.heading(key, text=title)
            self.large_tree.column(key, width=width, anchor=tk.CENTER if key in {"selected", "type", "file_count"} else tk.W)
        self.large_tree.column("size", anchor=tk.E)
        self.large_tree.bind("<Double-1>", self._toggle_large_checked)

    def _set_scanning_state(self, scanning: bool) -> None:
        state = tk.DISABLED if scanning else tk.NORMAL
        for btn in self.cleanup_buttons:
            btn.configure(state=state)
        if self.large_scan_button:
            self.large_scan_button.configure(state=state)

    def _show_admin_status(self) -> None:
        is_admin = self.scanner.is_admin()
        self.status_var.set("管理员权限：是" if is_admin else "管理员权限：否（部分目录可能无法删除）")

    def start_scan(self) -> None:
        self.status_var.set("正在扫描垃圾项...")
        self.progress_var.set(0)
        self._set_scanning_state(True)
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
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
        self.status_var.set(f"垃圾扫描完成：{len(self.all_items)} 项，可释放 {format_size(total_size)}")
        self._set_scanning_state(False)

    def start_large_scan(self) -> None:
        self.progress_var.set(0)
        self.status_var.set("正在扫描大文件/大文件夹...")
        self._set_scanning_state(True)
        if self.large_delete_button:
            self.large_delete_button.configure(state=tk.DISABLED)
        threading.Thread(target=self._large_scan_worker, daemon=True).start()

    def _large_scan_worker(self) -> None:
        messages = ["正在扫描大文件...", "正在扫描大文件夹..."]

        def on_message(text: str) -> None:
            self.root.after(0, self.status_var.set, text)

        self.root.after(0, self.progress_var.set, 5)
        files = self.scanner.scan_large_files(progress_cb=on_message)
        self.root.after(0, self.progress_var.set, 55)
        folders = self.scanner.scan_large_folders(progress_cb=on_message)
        self.root.after(0, self.progress_var.set, 95)

        self.large_results = sorted(files + folders, key=lambda x: x.size_bytes, reverse=True)
        self.root.after(0, self._after_large_scan)

    def _after_large_scan(self) -> None:
        self.apply_large_filters()
        self.progress_var.set(100)
        total_size = sum(i.size_bytes for i in self.large_results)
        self.status_var.set(f"大文件扫描完成：{len(self.large_results)} 项，总计 {format_size(total_size)}")
        self._set_scanning_state(False)
        if self.large_delete_button:
            self.large_delete_button.configure(state=tk.NORMAL)

    def apply_filters(self) -> None:
        items = self.all_items
        if self.only_large_var.get():
            items = [x for x in items if x.size_bytes >= 100 * MB]
        self.filtered_items = sorted(items, key=lambda x: x.size_bytes, reverse=self.sort_desc_var.get())
        self._refresh_cleanup_tree()

    def apply_large_filters(self) -> None:
        items = self.large_results
        now = datetime.now()

        if self.filter_only_files.get() and not self.filter_only_folders.get():
            items = [x for x in items if x.item_type == ScanItemType.FILE]
        elif self.filter_only_folders.get() and not self.filter_only_files.get():
            items = [x for x in items if x.item_type == ScanItemType.FOLDER]

        if self.filter_over_1gb.get():
            items = [x for x in items if x.size_bytes >= GB]

        if self.filter_180_days.get():
            threshold = now - timedelta(days=180)
            items = [x for x in items if x.modified_at <= threshold]
        elif self.filter_30_days.get():
            threshold = now - timedelta(days=30)
            items = [x for x in items if x.modified_at <= threshold]

        if self.filter_priority_ext.get():
            items = [x for x in items if x.item_type == ScanItemType.FOLDER or x.extension in PRIORITY_EXTENSIONS]

        items = sorted(items, key=lambda x: (not x.is_dev_residue, -x.size_bytes))
        self.large_filtered = items
        self._refresh_large_tree()

    def _refresh_cleanup_tree(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)

        for idx, item in enumerate(self.filtered_items):
            var = self.check_vars.setdefault(item.path, tk.BooleanVar(value=False))
            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=("☑" if var.get() else "☐", item.name, item.path, format_size(item.size_bytes), item.category.value, item.deletion_mode.value),
            )

    def _refresh_large_tree(self) -> None:
        for row in self.large_tree.get_children():
            self.large_tree.delete(row)

        for idx, item in enumerate(self.large_filtered):
            var = self.large_check_vars.setdefault(item.path, tk.BooleanVar(value=False))
            tag = "开发残留" if item.is_dev_residue else ("优先扩展" if item.extension in PRIORITY_EXTENSIONS else "")
            self.large_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    "☑" if var.get() else "☐",
                    item.item_type.value,
                    item.name,
                    item.path,
                    format_size(item.size_bytes),
                    item.modified_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "-" if item.file_count is None else str(item.file_count),
                    tag,
                ),
            )

    def _toggle_cleanup_checked(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not row or col != "#1":
            return
        idx = int(row)
        if idx < len(self.filtered_items):
            item = self.filtered_items[idx]
            var = self.check_vars.setdefault(item.path, tk.BooleanVar(value=False))
            var.set(not var.get())
            self._refresh_cleanup_tree()

    def _toggle_large_checked(self, event: tk.Event) -> None:
        row = self.large_tree.identify_row(event.y)
        col = self.large_tree.identify_column(event.x)
        if not row or col != "#1":
            return
        idx = int(row)
        if idx < len(self.large_filtered):
            item = self.large_filtered[idx]
            var = self.large_check_vars.setdefault(item.path, tk.BooleanVar(value=False))
            var.set(not var.get())
            self._refresh_large_tree()

    def select_manual_items(self) -> None:
        for item in self.filtered_items:
            if item.deletion_mode == DeletionMode.MANUAL_CONFIRM:
                self.check_vars.setdefault(item.path, tk.BooleanVar(value=False)).set(True)
        self._refresh_cleanup_tree()

    def unselect_all(self) -> None:
        for var in self.check_vars.values():
            var.set(False)
        self._refresh_cleanup_tree()

    def _get_checked_cleanup_items(self) -> list[CleanupItem]:
        return [item for item in self.filtered_items if self.check_vars.get(item.path, tk.BooleanVar(value=False)).get()]

    def _get_checked_large_paths(self) -> list[str]:
        return [item.path for item in self.large_filtered if self.large_check_vars.get(item.path, tk.BooleanVar(value=False)).get()]

    def _confirm_delete(self, names: list[str]) -> bool:
        summary = "\n".join(f"- {name}" for name in names[:15])
        if len(names) > 15:
            summary += "\n..."
        return messagebox.askyesno("确认删除", f"即将删除以下项目：\n{summary}\n\n是否继续？")

    def _show_delete_summary(self, results: list[DeleteResult], title: str) -> None:
        success = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        freed = sum(r.freed_bytes for r in success)

        lines = [
            f"成功删除：{len(success)} 项",
            f"释放空间：{format_size(freed)}",
            f"失败数量：{len(failed)} 项",
        ]
        if failed:
            lines.append("失败项（前 10 条）：")
            for item in failed[:10]:
                lines.append(f"- {item.name}: {item.error}")
        messagebox.showinfo(title, "\n".join(lines))

    def delete_selected(self) -> None:
        items = self._get_checked_cleanup_items()
        if not items:
            messagebox.showwarning("提示", "请先勾选要删除的项目。")
            return
        if not self._confirm_delete([i.name for i in items]):
            return
        results = self.deleter.delete_items(items, simulate=self.simulate_var.get())
        self._show_delete_summary(results, "垃圾清理删除结果")
        self.start_scan()

    def delete_direct_safe(self) -> None:
        items = [x for x in self.filtered_items if x.deletion_mode == DeletionMode.DIRECT_SAFE]
        if not items:
            messagebox.showwarning("提示", "当前无可直接删除项。")
            return
        if not self._confirm_delete([i.name for i in items]):
            return
        results = self.deleter.delete_items(items, simulate=self.simulate_var.get())
        self._show_delete_summary(results, "一键安全删除结果")
        self.start_scan()

    def delete_large_selected(self) -> None:
        paths = self._get_checked_large_paths()
        if not paths:
            messagebox.showwarning("提示", "请先在大文件列表中勾选项目。")
            return
        names = [Path(p).name or p for p in paths]
        if not self._confirm_delete(names):
            return
        results = self.deleter.safe_delete_paths(paths, simulate=self.simulate_var.get())
        self._show_delete_summary(results, "大文件删除结果")

    def export_csv(self) -> None:
        if not self.filtered_items:
            messagebox.showwarning("提示", "暂无数据，请先扫描。")
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
                    writer.writerow([item.name, item.path, item.size_bytes, format_size(item.size_bytes), item.category.value, item.deletion_mode.value])
            messagebox.showinfo("成功", f"报告已导出：{Path(path)}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导出失败", str(exc))
