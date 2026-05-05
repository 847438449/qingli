"""程序入口。"""

from __future__ import annotations

import tkinter as tk

from ui import CleanerUI


if __name__ == "__main__":
    root = tk.Tk()
    CleanerUI(root)
    root.mainloop()
