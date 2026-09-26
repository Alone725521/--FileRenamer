"""自定义对话框：确认、快捷键帮助、进度。"""
import tkinter as tk
import ttkbootstrap as ttkb
from ttkbootstrap.constants import *


def ask_yes_no(parent, message, title="确认",
               font=("微软雅黑", 10), log_func=None):
    """
    自实现的是/否对话框。返回布尔值。
    - 按钮区先 pack 到 BOTTOM，不会被消息挤出窗口
    - 消息超过 14 行时自动带滚动条
    """
    if log_func:
        log_func(f"ask_yes_no 弹出对话框：{title}")

    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.transient(parent)

    result = {'value': False}

    def on_yes():
        result['value'] = True
        dialog.destroy()

    def on_no():
        result['value'] = False
        dialog.destroy()

    # 按钮区先 pack 到 BOTTOM
    btn_frame = ttkb.Frame(dialog, padding=(20, 10, 20, 20))
    btn_frame.pack(side=BOTTOM, fill=X)

    yes_btn = ttkb.Button(btn_frame, text="是", command=on_yes,
                          bootstyle="success", width=10)
    yes_btn.pack(side=RIGHT, padx=(5, 0))

    no_btn = ttkb.Button(btn_frame, text="否", command=on_no,
                         bootstyle="secondary", width=10)
    no_btn.pack(side=RIGHT, padx=(0, 5))

    # 消息区
    msg_frame = ttkb.Frame(dialog, padding=(20, 20, 20, 0))
    msg_frame.pack(side=TOP, fill=BOTH, expand=True)

    estimated_lines = 0
    for line in message.split('\n'):
        estimated_lines += max(1, len(line) // 60 + 1)

    if estimated_lines > 14:
        text_wrap = ttkb.Frame(msg_frame)
        text_wrap.pack(fill=BOTH, expand=True)
        text_widget = tk.Text(
            text_wrap, wrap='word', font=font,
            relief='flat', borderwidth=0, highlightthickness=0,
            height=14, width=60,
            background=dialog.cget("background") or "#ffffff",
        )
        text_widget.insert('1.0', message)
        text_widget.configure(state='disabled')
        sb = ttkb.Scrollbar(text_wrap, orient=VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=sb.set)
        text_widget.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)
    else:
        ttkb.Label(msg_frame, text=message, font=font,
                   wraplength=520, justify=LEFT, anchor='w').pack(fill=X)

    dialog.protocol("WM_DELETE_WINDOW", on_no)

    dialog.update_idletasks()
    w = max(560, dialog.winfo_reqwidth())
    h = dialog.winfo_reqheight()
    screen_h = dialog.winfo_screenheight()
    max_h = int(screen_h * 0.8)
    if h > max_h:
        h = max_h

    rx = parent.winfo_x() + max(0, (parent.winfo_width() - w) // 2)
    ry = parent.winfo_y() + max(0, (parent.winfo_height() - h) // 2)
    dialog.geometry(f"{w}x{h}+{rx}+{ry}")

    try:
        dialog.grab_set()
    except tk.TclError:
        pass

    no_btn.focus_force()
    dialog.bind("<Escape>", lambda e: on_no())
    dialog.bind("<Return>", lambda e: on_no())

    parent.wait_window(dialog)
    if log_func:
        log_func(f"ask_yes_no 结果：{result['value']}")
    return result['value']


def show_shortcuts_help(parent, shortcuts, font, hint_font):
    """显示快捷键帮助对话框。"""
    dialog = tk.Toplevel(parent)
    dialog.title("键盘快捷键")
    dialog.resizable(False, False)
    dialog.transient(parent)

    header = ttkb.Frame(dialog, padding=(20, 15, 20, 5))
    header.pack(fill=X)
    ttkb.Label(header, text="键盘快捷键",
               font=("微软雅黑", 14, "bold")).pack(anchor=W)
    ttkb.Label(header, text="使用以下快捷键可以更快速操作",
               font=hint_font, foreground="gray").pack(anchor=W, pady=(2, 0))

    ttkb.Separator(dialog, orient=HORIZONTAL).pack(fill=X, padx=20, pady=5)

    body = ttkb.Frame(dialog, padding=(20, 5, 20, 10))
    body.pack(fill=BOTH, expand=True)
    for seq, desc in shortcuts:
        row = ttkb.Frame(body)
        row.pack(fill=X, pady=3)
        ttkb.Label(row, text=f" {seq} ",
                   font=("Consolas", 10, "bold"),
                   bootstyle="primary-inverse",
                   padding=(6, 2)).pack(side=LEFT)
        ttkb.Label(row, text=desc, font=font,
                   padding=(15, 0, 0, 0)).pack(side=LEFT)

    btn_frame = ttkb.Frame(dialog, padding=(20, 10, 20, 20))
    btn_frame.pack(side=BOTTOM, fill=X)
    ttkb.Button(btn_frame, text="关闭", command=dialog.destroy,
                bootstyle="primary", width=10).pack(side=RIGHT)

    dialog.update_idletasks()
    w = max(480, dialog.winfo_reqwidth())
    h = dialog.winfo_reqheight()
    rx = parent.winfo_x() + max(0, (parent.winfo_width() - w) // 2)
    ry = parent.winfo_y() + max(0, (parent.winfo_height() - h) // 2)
    dialog.geometry(f"{w}x{h}+{rx}+{ry}")

    try:
        dialog.grab_set()
    except tk.TclError:
        pass

    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.focus_force()
    parent.wait_window(dialog)


class ProgressDialog:
    """异步进度对话框。UI 更新在主线程调用。"""

    def __init__(self, parent, total, on_cancel,
                 font=("微软雅黑", 10),
                 font_bold=("微软雅黑", 11, "bold"),
                 log_func=None):
        self.parent = parent
        self.total = total
        self.on_cancel = on_cancel
        self.font = font
        self.font_bold = font_bold
        self.log_func = log_func

        self.window = None
        self.bar = None
        self.label = None
        self.cancel_btn = None

        self._build()

    def _build(self):
        try:
            parent = self.parent
            win = tk.Toplevel(parent)
            win.title("正在重命名")
            win.resizable(False, False)
            win.transient(parent)

            parent.update_idletasks()
            win_w, win_h = 580, 200
            rx = parent.winfo_x() + (parent.winfo_width() - win_w) // 2
            ry = parent.winfo_y() + (parent.winfo_height() - win_h) // 2
            win.geometry(f"{win_w}x{win_h}+{rx}+{ry}")

            frame = ttkb.Frame(win, padding=20)
            frame.pack(fill=BOTH, expand=True)

            ttkb.Label(frame, text="正在处理文件...",
                       font=self.font_bold, anchor=W).pack(fill=X, pady=(0, 8))

            self.label = ttkb.Label(
                frame, text=f"准备中...  0 / {self.total}",
                font=self.font, anchor=W, justify=LEFT, wraplength=520,
            )
            self.label.pack(fill=X, pady=(0, 10))

            self.bar = ttkb.Progressbar(
                frame, maximum=self.total, value=0,
                bootstyle="success", mode='determinate',
            )
            self.bar.pack(fill=X, pady=(0, 15))

            btn_frame = ttkb.Frame(frame)
            btn_frame.pack(fill=X)
            self.cancel_btn = ttkb.Button(
                btn_frame, text="取消",
                command=self._handle_cancel,
                bootstyle="danger-outline", width=12,
            )
            self.cancel_btn.pack(side=RIGHT)

            self.window = win
            win.protocol("WM_DELETE_WINDOW", self._handle_cancel)

            try:
                win.grab_set()
            except tk.TclError:
                pass
            win.focus_force()

            if self.log_func:
                self.log_func(f"进度窗口已打开，total={self.total}")
        except Exception as e:
            if self.log_func:
                self.log_func(f"打开进度窗口失败：{e}")
            self.window = None
            self.bar = None
            self.label = None
            self.cancel_btn = None

    def _handle_cancel(self):
        try:
            self.on_cancel()
        except Exception:
            pass

    def update(self, stage, current, total, old, new):
        if self.bar is None or self.label is None:
            return
        try:
            stage_name = "准备阶段" if stage == 1 else "完成阶段"
            text = f"{stage_name}：{current} / {total}\n{old}  →  {new}"
            self.label.configure(text=text)
            self.bar.configure(value=current)
        except Exception as e:
            if self.log_func:
                self.log_func(f"更新进度 UI 失败：{e}")

    def set_cancelling(self):
        try:
            if self.cancel_btn:
                self.cancel_btn.configure(state='disabled', text="正在取消...")
            if self.label:
                self.label.configure(text="正在取消，请稍候...")
        except Exception:
            pass

    def close(self):
        if self.window is None:
            return
        try:
            self.window.grab_release()
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass
        self.window = None
        self.bar = None
        self.label = None
        self.cancel_btn = None
