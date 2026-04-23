# 安全优先 C 盘清理工具（Windows）

一个基于 **Python 3.11+** 与 **tkinter** 的 Windows 桌面清理工具，核心目标是“安全优先”。

## 功能概览

- 扫描 C 盘中适合清理的垃圾项，并按两类展示：
  - 可直接删除
  - 建议人工确认
- 表格展示每个项目：
  - 名称
  - 完整路径
  - 占用空间
  - 分类
  - 删除模式
- 支持勾选后选择性删除。
- 支持“一键直接删除安全项”。
- 用户手动勾选项优先移动到回收站（`send2trash`）。
- 删除前确认弹窗展示待删项目名称。
- 删除后显示实际释放空间。
- 删除失败项单独列出错误原因。
- 新增增强功能：
  - 按大小排序
  - 仅显示大于 100MB 项
  - 导出 CSV 扫描报告
  - 全选建议清理项 / 取消全选
  - 扫描进度条
  - 管理员权限检测
  - 扫描 Chrome / Edge 缓存（仅缓存，不触碰账号与书签）
  - 模拟删除模式（仅预览，不实际删除）

## 项目结构

- `main.py`：程序入口
- `ui.py`：图形界面层
- `scanner.py`：扫描逻辑（安全规则）
- `deleter.py`：删除逻辑（优先回收站）
- `models.py`：数据模型
- `requirements.txt`：依赖
- `start_cleaner.bat`：Windows 启动脚本

## 环境要求

- Windows 10/11
- Python 3.11+

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动方式

### 方式 1：命令行启动

```bash
python main.py
```

### 方式 2：双击脚本启动（Windows）

双击项目根目录的 `start_cleaner.bat`。

## 打包 EXE（PyInstaller）

```bash
pyinstaller --noconfirm --onefile --windowed --name SafeCleaner main.py
```

打包后可在 `dist/SafeCleaner.exe` 找到可执行文件。

## 安全说明

工具内置保护策略，不会默认删除以下内容：

- `C:\Windows\System32`
- `C:\Program Files`
- `C:\Program Files (x86)`
- 用户桌面
- 用户文档
- 注册表相关内容（本工具不涉及注册表操作）

如遇“权限不足”，请尝试以管理员身份运行。
