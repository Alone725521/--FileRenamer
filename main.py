"""批量重命名工具 — 主应用（UI + 调度）。"""
import os
import queue
import threading
import traceback
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from collections import defaultdict

import ttkbootstrap as ttkb
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

import helpers as H
import file_ops
import dialogs


class FileRenamerApp:
    def __init__(self, root):
        self.root = root
        self.style = ttkb.Style()

        # ---- 状态 ----
        self.preview_data = None
        self.preview_signature = None
        self._param_check_after_id = None
        self._suggested_digits = None
        self._filter_check_after_id = None

        # ---- 线程 / 进度 ----
        self._cancel_event = threading.Event()
        self._worker_thread = None
        self._progress_dialog = None
        self._progress_queue = None
        self._poll_after_id = None

        # ---- 日志 ----
        H.log("=" * 60)
        H.log(f"程序启动，日志文件：{H.LOG_PATH}")

        # ---- 字体 ----
        self.font = ("微软雅黑", 10)
        self.font_bold = ("微软雅黑", 11, "bold")
        self.title_font = ("微软雅黑", 15, "bold")
        self.hint_font = ("微软雅黑", 9)
        self._fonts = {
            'font': self.font,
            'font_bold': self.font_bold,
            'title_font': self.title_font,
            'hint_font': self.hint_font,
        }

        # ---- 主题 ----
        all_themes = self.style.theme_names()
        self.available_themes = [t for t in all_themes if t not in H.THEME_EXCLUDE]
        if not self.available_themes:
            self.available_themes = ['bootstrap-light']

        self.theme_name_map = {}
        for theme in self.available_themes:
            if theme.endswith('-light'):
                base, suffix = theme[:-6], '亮色'
            elif theme.endswith('-dark'):
                base, suffix = theme[:-5], '暗色'
            else:
                base, suffix = theme, ''
            base_cn = H.THEME_BASE_NAMES_CN.get(base, base.capitalize())
            self.theme_name_map[theme] = f"{base_cn}{suffix}" if suffix else base_cn

        self.theme_display_list = [self.theme_name_map[t] for t in self.available_themes]
        self.current_theme = tk.StringVar(value=self.available_themes[0])
        self.style.theme_use(self.current_theme.get())
        self.theme_display_var = tk.StringVar(
            value=self.theme_name_map[self.current_theme.get()]
        )

        # ---- 窗口 ----
        self.root.title("批量重命名工具")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = min(1180, int(screen_w * 0.85))
        win_h = min(1000, int(screen_h * 0.9))
        self.root.geometry(f"{win_w}x{win_h}")
        self.root.minsize(1020, 820)

        H.apply_custom_styles(self.style, self._fonts)
        H.refresh_combobox_style(self.style, self.root)

        # ---- UI ----
        self._build_ui()

        self.files = []
        self.all_files_count = 0

        self._center_window(win_w, win_h)
        self._bind_shortcuts()

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _build_ui(self):
        main_frame = ttkb.Frame(self.root, padding=8)
        main_frame.pack(fill=BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)

        for i in range(7):
            main_frame.rowconfigure(i, weight=0)
        main_frame.rowconfigure(4, weight=1)

        # ---------- 标题行 ----------
        title_row = ttkb.Frame(main_frame)
        title_row.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 8))
        ttkb.Label(title_row, text="批量重命名工具",
                   style="Title.TLabel").pack(side=LEFT)

        theme_frame = ttkb.Frame(title_row)
        theme_frame.pack(side=RIGHT)
        ttkb.Button(theme_frame, text="快捷键 (F1)",
                    command=self._shortcut_show_help,
                    bootstyle="secondary-link",
                    width=12).pack(side=LEFT, padx=(0, 15))
        ttkb.Label(theme_frame, text="主题：",
                   font=self.font).pack(side=LEFT, padx=(0, 5))
        self.theme_combo = ttkb.Combobox(
            theme_frame,
            textvariable=self.theme_display_var,
            values=self.theme_display_list,
            state='readonly', width=12, font=self.font,
        )
        self.theme_combo.pack(side=LEFT)
        self.theme_combo.bind('<<ComboboxSelected>>', self._on_theme_change)

        # ---------- 目录选择 ----------
        ttkb.Label(main_frame, text="目录路径:",
                   font=self.font).grid(row=1, column=0, sticky='w', pady=4)
        self.dir_path = tk.StringVar()
        ttkb.Entry(main_frame, textvariable=self.dir_path,
                   font=self.font).grid(row=1, column=1, sticky='ew', pady=4, padx=5)
        self.browse_btn = ttkb.Button(main_frame, text="浏览 (Ctrl+O)",
                                      command=self.browse_directory,
                                      bootstyle="secondary-outline")
        self.browse_btn.grid(row=1, column=2, padx=5, pady=4)

        # ---------- 参数 ----------
        params_frame = ttkb.Labelframe(main_frame, text="重命名参数",
                                       padding=10, style="Section.TLabelframe")
        params_frame.grid(row=2, column=0, columnspan=3, sticky='ew', pady=6)
        params_frame.columnconfigure(1, weight=1)

        ttkb.Label(params_frame, text="文件名前缀:",
                   font=self.font).grid(row=0, column=0, sticky='w', pady=4)
        self.file_prefix = tk.StringVar(value=" ")
        ttkb.Entry(params_frame, textvariable=self.file_prefix,
                   font=self.font).grid(row=0, column=1, sticky='ew', pady=4, padx=5)

        ttkb.Label(params_frame, text="文件扩展名:",
                   font=self.font).grid(row=0, column=2, sticky='w', pady=4)
        self.file_extension = tk.StringVar(value="png")
        ttkb.Entry(params_frame, textvariable=self.file_extension,
                   width=10, font=self.font).grid(row=0, column=3, sticky='w',
                                                  pady=4, padx=5)

        ttkb.Label(params_frame, text="起始序号:",
                   font=self.font).grid(row=1, column=0, sticky='w', pady=4)
        self.start_number = tk.StringVar(value="1")
        ttkb.Entry(params_frame, textvariable=self.start_number,
                   width=10, font=self.font).grid(row=1, column=1, sticky='w',
                                                  pady=4, padx=5)

        ttkb.Label(params_frame, text="序号位数:",
                   font=self.font).grid(row=1, column=2, sticky='w', pady=4)
        self.digits = tk.StringVar(value="1")
        ttkb.Entry(params_frame, textvariable=self.digits,
                   width=10, font=self.font).grid(row=1, column=3, sticky='w',
                                                  pady=4, padx=5)

        ttkb.Label(params_frame, text="每次增加:",
                   font=self.font).grid(row=2, column=0, sticky='w', pady=4)
        self.increment = tk.StringVar(value="1")
        ttkb.Entry(params_frame, textvariable=self.increment,
                   width=10, font=self.font).grid(row=2, column=1, sticky='w',
                                                  pady=4, padx=5)

        ttkb.Label(params_frame,
                   text="整数模式：序号位数=补零位数；小数模式：序号位数=小数位数。\n"
                        "前缀留空（或全为空格）时不会自动补“_”。",
                   style="Hint.TLabel", wraplength=520, justify=LEFT
                   ).grid(row=2, column=2, columnspan=2, sticky='w', pady=4, padx=5)

        ttkb.Label(params_frame, text="过滤扩展名:",
                   font=self.font).grid(row=3, column=0, sticky='w', pady=4)
        self.filter_ext_var = tk.StringVar(value="")
        ttkb.Entry(params_frame, textvariable=self.filter_ext_var,
                   font=self.font).grid(row=3, column=1, sticky='ew', pady=4, padx=5)

        self.filter_count_var = tk.StringVar(value="")
        ttkb.Label(params_frame, textvariable=self.filter_count_var,
                   style="Hint.TLabel").grid(row=3, column=2, columnspan=2,
                                             sticky='w', pady=4, padx=5)

        ttkb.Label(params_frame,
                   text="提示：只处理指定扩展名的文件，多个用逗号分隔（如 png, jpg）。"
                        "留空则处理目录下所有文件。",
                   style="Hint.TLabel", wraplength=800, justify=LEFT
                   ).grid(row=4, column=0, columnspan=4, sticky='w',
                          pady=(2, 0), padx=5)

        self.param_hint_var = tk.StringVar(value="")
        ttkb.Label(params_frame, textvariable=self.param_hint_var,
                   style="ParamHint.TLabel", wraplength=800,
                   justify=LEFT, anchor='w'
                   ).grid(row=5, column=0, columnspan=3, sticky='ew',
                          pady=(6, 0), padx=5)

        self.apply_digits_btn = ttkb.Button(params_frame, text="应用建议位数",
                                            command=self._apply_suggested_digits,
                                            bootstyle="warning-outline",
                                            state='disabled', width=14)
        self.apply_digits_btn.grid(row=5, column=3, sticky='e',
                                   pady=(6, 0), padx=5)

        for var in (self.start_number, self.increment, self.digits):
            var.trace_add('write', self._schedule_param_check)
        self.file_prefix.trace_add('write', self._schedule_param_check)
        self.file_extension.trace_add('write', self._schedule_param_check)
        self.filter_ext_var.trace_add('write', self._schedule_filter_refresh)

        # ---------- 排序 ----------
        sort_frame = ttkb.Labelframe(main_frame, text="排序方式",
                                     padding=10, style="Section.TLabelframe")
        sort_frame.grid(row=3, column=0, columnspan=3, sticky='ew', pady=6)

        ttkb.Label(sort_frame, text="排序依据:",
                   font=self.font).pack(side=LEFT, padx=5)
        self.sort_by = tk.StringVar(value="名称")
        sort_by_combo = ttkb.Combobox(
            sort_frame, textvariable=self.sort_by,
            values=["名称", "修改时间", "大小", "类型"],
            state="readonly", width=10, font=self.font,
        )
        sort_by_combo.pack(side=LEFT, padx=5)
        sort_by_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_sort(silent=True))

        ttkb.Label(sort_frame, text="排序方向:",
                   font=self.font).pack(side=LEFT, padx=5)
        self.sort_order = tk.StringVar(value="升序")
        sort_order_combo = ttkb.Combobox(
            sort_frame, textvariable=self.sort_order,
            values=["升序", "降序"],
            state="readonly", width=8, font=self.font,
        )
        sort_order_combo.pack(side=LEFT, padx=5)
        sort_order_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_sort(silent=True))

        self.apply_sort_btn = ttkb.Button(sort_frame, text="应用排序 (Ctrl+S)",
                                          command=self.on_apply_sort_clicked,
                                          bootstyle="info-outline")
        self.apply_sort_btn.pack(side=LEFT, padx=10)

        ttkb.Label(sort_frame, text="（排序结果决定重命名时的编号顺序）",
                   style="Hint.TLabel").pack(side=LEFT, padx=5)

        # ---------- 文件列表 ----------
        list_frame = ttkb.Labelframe(main_frame, text="目录文件列表",
                                     padding=8, style="Section.TLabelframe")
        list_frame.grid(row=4, column=0, columnspan=3, sticky='nsew', pady=6)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        columns = ("name", "size", "type", "modified")
        self.tree = ttkb.Treeview(list_frame, columns=columns, show="headings",
                                  bootstyle="primary", height=22)
        self.tree.heading("name", text="文件名")
        self.tree.heading("size", text="大小")
        self.tree.heading("type", text="类型")
        self.tree.heading("modified", text="修改时间")
        self.tree.column("name", width=430)
        self.tree.column("size", width=110)
        self.tree.column("type", width=110)
        self.tree.column("modified", width=170)
        self.tree.tag_configure('conflict', foreground='#dc3545')

        scrollbar = ttkb.Scrollbar(list_frame, orient=VERTICAL,
                                   command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')

        # ---------- 按钮 ----------
        button_frame = ttkb.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=3, pady=8)

        self.refresh_btn = ttkb.Button(button_frame, text="刷新文件列表 (F5)",
                                       command=self.refresh_file_list,
                                       bootstyle="secondary")
        self.refresh_btn.pack(side=LEFT, padx=5)

        self.preview_btn = ttkb.Button(button_frame, text="预览重命名 (Ctrl+R)",
                                       command=self.preview_rename,
                                       bootstyle="primary")
        self.preview_btn.pack(side=LEFT, padx=5)

        self.execute_btn = ttkb.Button(button_frame, text="执行重命名 (Ctrl+Enter)",
                                       command=self.execute_rename,
                                       bootstyle="success")
        self.execute_btn.pack(side=LEFT, padx=5)

        # ---------- 状态栏 ----------
        self.status_var = tk.StringVar(value="就绪  ·  按 F1 查看快捷键")
        self.status_label = ttkb.Label(
            main_frame, textvariable=self.status_var,
            anchor=W, padding=(8, 4), font=self.font,
            bootstyle=H.STATUS_IDLE,
        )
        self.status_label.grid(row=6, column=0, columnspan=3,
                               sticky='ew', pady=(4, 0))

        self.dir_path.trace("w", self.on_directory_changed)

    # ==================================================================
    # 快捷键
    # ==================================================================
    def _bind_shortcuts(self):
        H.log("绑定快捷键")
        mappings = [
            ("<Control-o>", self._sc_browse),
            ("<Control-O>", self._sc_browse),
            ("<F5>",        self._sc_refresh),
            ("<Control-r>", self._sc_preview),
            ("<Control-R>", self._sc_preview),
            ("<Control-Return>", self._sc_execute),
            ("<Control-s>", self._sc_apply_sort),
            ("<Control-S>", self._sc_apply_sort),
            ("<Control-Key-1>", lambda: self._sc_sort_by("名称")),
            ("<Control-Key-2>", lambda: self._sc_sort_by("修改时间")),
            ("<Control-Key-3>", lambda: self._sc_sort_by("大小")),
            ("<Control-Key-4>", lambda: self._sc_sort_by("类型")),
            ("<Control-d>", self._sc_toggle_order),
            ("<Control-D>", self._sc_toggle_order),
            ("<F1>",       self._shortcut_show_help),
            ("<Control-q>", self._sc_quit),
            ("<Control-Q>", self._sc_quit),
        ]
        for seq, handler in mappings:
            wrapper = self._make_safe_handler(handler)
            try:
                self.root.bind_all(seq, wrapper)
            except Exception as e:
                H.log(f"绑定快捷键失败 {seq}: {e}")

    def _make_safe_handler(self, handler):
        def wrapper(event=None):
            if self._progress_dialog is not None and self._progress_dialog.window is not None:
                return
            try:
                current_grab = self.root.grab_current()
                if current_grab is not None and current_grab != self.root:
                    return
            except Exception:
                pass
            try:
                handler()
            except Exception as e:
                H.log(f"快捷键处理异常：{e}\n{traceback.format_exc()}")
        return wrapper

    # ---- 快捷键处理 ----
    def _sc_browse(self):
        H.log("快捷键：Ctrl+O 打开目录")
        self.browse_directory()

    def _sc_refresh(self):
        H.log("快捷键：F5 刷新")
        if not self.dir_path.get():
            self.set_status("请先选择目录（Ctrl+O）", kind=H.STATUS_WARNING)
            return
        self.refresh_file_list()

    def _sc_preview(self):
        H.log("快捷键：Ctrl+R 预览")
        self.preview_rename()

    def _sc_execute(self):
        H.log("快捷键：Ctrl+Enter 执行")
        self.execute_rename()

    def _sc_apply_sort(self):
        H.log("快捷键：Ctrl+S 应用排序")
        self.on_apply_sort_clicked()

    def _sc_sort_by(self, by):
        H.log(f"快捷键：排序依据 → {by}")
        if not self.files:
            self.set_status("目录中没有文件", kind=H.STATUS_WARNING)
            return
        self.sort_by.set(by)
        self.apply_sort(silent=True)

    def _sc_toggle_order(self):
        H.log("快捷键：Ctrl+D 切换排序方向")
        if not self.files:
            self.set_status("目录中没有文件", kind=H.STATUS_WARNING)
            return
        current = self.sort_order.get()
        self.sort_order.set("降序" if current == "升序" else "升序")
        self.apply_sort(silent=True)

    def _sc_quit(self):
        H.log("快捷键：Ctrl+Q 退出")
        if self._ask_yes_no("确定要退出程序吗？", "退出确认"):
            self.root.quit()

    def _shortcut_show_help(self):
        H.log("快捷键：F1 帮助")
        dialogs.show_shortcuts_help(self.root, H.SHORTCUTS,
                                    self.font, self.hint_font)

    # ==================================================================
    # 主题
    # ==================================================================
    def _on_theme_change(self, event=None):
        selected_display = self.theme_display_var.get()
        english_name = None
        for eng, chn in self.theme_name_map.items():
            if chn == selected_display:
                english_name = eng
                break
        if english_name is None:
            english_name = selected_display

        self.current_theme.set(english_name)
        self.style.theme_use(english_name)
        H.apply_custom_styles(self.style, self._fonts)
        H.refresh_combobox_style(self.style, self.root)
        H.force_refresh_comboboxes(self.root)

    # ==================================================================
    # 对话框
    # ==================================================================
    def _ask_yes_no(self, message, title="确认"):
        return dialogs.ask_yes_no(self.root, message, title,
                                  font=self.font, log_func=H.log)

    # ==================================================================
    # 目录 / 文件列表
    # ==================================================================
    def browse_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.dir_path.set(directory)
            self.refresh_file_list()

    def on_directory_changed(self, *args):
        if os.path.exists(self.dir_path.get()):
            self.refresh_file_list()

    def refresh_file_list(self):
        directory = self.dir_path.get()
        if not directory or not os.path.exists(directory):
            return

        all_files = []
        try:
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                if os.path.isfile(item_path):
                    stat = os.stat(item_path)
                    all_files.append({
                        'name': item,
                        'size': stat.st_size,
                        'mtime': stat.st_mtime,
                        'type': Path(item).suffix or "文件",
                    })
        except Exception as e:
            Messagebox.show_error(f"无法读取目录: {str(e)}", "错误", parent=self.root)
            return

        self.all_files_count = len(all_files)
        raw_filter = self.filter_ext_var.get()
        self.files = [f for f in all_files if H.matches_filter(f['name'], raw_filter)]

        self._update_filter_count_label()
        self.apply_sort(silent=True, show_status=False)

        self.preview_data = None
        self.preview_signature = None

        if H.parse_filter(raw_filter) is None:
            self.set_status(f"已加载 {len(self.files)} 个文件", kind=H.STATUS_INFO)
        else:
            self.set_status(
                f"已加载 {len(self.files)} 个文件（过滤 {self.all_files_count - len(self.files)} 个）",
                kind=H.STATUS_INFO)

        self._check_params_and_hint()

    def _update_filter_count_label(self):
        total = self.all_files_count
        matched = len(self.files)
        exts = H.parse_filter(self.filter_ext_var.get())
        if exts is None:
            self.filter_count_var.set(f"共 {total} 个文件（未过滤）" if total > 0 else "")
        else:
            self.filter_count_var.set(f"匹配 {matched} / 共 {total} 个文件" if total > 0 else "")

    # ==================================================================
    # 排序
    # ==================================================================
    def apply_sort(self, silent=False, show_status=True):
        if not self.files:
            self.tree.delete(*self.tree.get_children())
            if show_status:
                self.set_status("目录中没有文件，未执行排序", kind=H.STATUS_WARNING)
            return False

        sort_by = self.sort_by.get()
        reverse = (self.sort_order.get() == "降序")

        if sort_by == "修改时间":
            key = lambda f: f['mtime']
        elif sort_by == "大小":
            key = lambda f: f['size']
        elif sort_by == "类型":
            key = lambda f: (f['type'], H.natural_sort_key(f['name']))
        else:
            key = lambda f: H.natural_sort_key(f['name'])

        self.files.sort(key=key, reverse=reverse)
        self.populate_tree()

        self.preview_data = None
        self.preview_signature = None

        if show_status:
            self.set_status(
                f"✓ 已按【{sort_by} · {self.sort_order.get()}】排序，共 {len(self.files)} 个文件",
                kind=H.STATUS_SUCCESS)
        return True

    def populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        for f in self.files:
            self.tree.insert("", END, values=(
                f['name'],
                H.format_file_size(f['size']),
                f['type'],
                H.format_time(f['mtime']),
            ))

    def set_status(self, text, kind=None):
        self.status_var.set(text)
        self.status_label.configure(bootstyle=kind or H.STATUS_IDLE)

    def on_apply_sort_clicked(self):
        applied = self.apply_sort(silent=False)
        if not applied:
            return
        Messagebox.show_info(
            message=f"已按【{self.sort_by.get()} · {self.sort_order.get()}】排序，"
                    f"共 {len(self.files)} 个文件。\n\n"
                    f"预览和执行重命名时将按此顺序编号。",
            title="排序已应用", parent=self.root,
        )

    # ==================================================================
    # 参数实时检查
    # ==================================================================
    def _schedule_param_check(self, *args):
        if self._param_check_after_id is not None:
            try:
                self.root.after_cancel(self._param_check_after_id)
            except Exception:
                pass
        self._param_check_after_id = self.root.after(300, self._check_params_and_hint)

    def _check_params_and_hint(self):
        self._param_check_after_id = None
        self._suggested_digits = None

        try:
            self.apply_digits_btn.configure(state='disabled')
        except Exception:
            pass

        prefix = self.file_prefix.get()
        ext = self.file_extension.get()

        ok, err = H.validate_component(prefix, "文件名前缀")
        if not ok:
            self.param_hint_var.set("⚠ " + err)
            return

        ok, err = H.validate_extension(ext)
        if not ok:
            self.param_hint_var.set("⚠ " + err)
            return

        start_str = self.start_number.get().strip()
        inc_str = self.increment.get().strip()
        digits_str = self.digits.get().strip()

        if not start_str or not inc_str or not digits_str:
            self.param_hint_var.set("")
            return

        try:
            cur_digits = int(digits_str)
            if cur_digits <= 0:
                self.param_hint_var.set("")
                return
        except ValueError:
            self.param_hint_var.set("")
            return

        count = max(len(self.files), 1)
        min_d = H.find_min_decimal_digits(start_str, inc_str, count)

        if min_d is None:
            self.param_hint_var.set("")
            return

        if min_d > cur_digits:
            self._suggested_digits = min_d
            self.param_hint_var.set(
                f"⚠ 当前「序号位数」为 {cur_digits}，按此设置将产生重复文件名"
                f"（共 {count} 个文件）。建议改为 {min_d}。"
            )
            try:
                self.apply_digits_btn.configure(state='normal')
            except Exception:
                pass
        else:
            self.param_hint_var.set("")

    def _apply_suggested_digits(self):
        if self._suggested_digits is None:
            return
        self.digits.set(str(self._suggested_digits))

    def _schedule_filter_refresh(self, *args):
        if self._filter_check_after_id is not None:
            try:
                self.root.after_cancel(self._filter_check_after_id)
            except Exception:
                pass
        self._filter_check_after_id = self.root.after(300, self._do_filter_refresh)

    def _do_filter_refresh(self):
        self._filter_check_after_id = None
        directory = self.dir_path.get()
        if directory and os.path.exists(directory):
            self.refresh_file_list()

    # ==================================================================
    # 序号 / 文件名生成（薄包装，供本类内部调用）
    # ==================================================================
    def is_decimal_mode(self):
        return H.is_decimal_mode(self.start_number.get(), self.increment.get())

    def build_serial(self, index):
        return H.build_serial(index,
                              self.start_number.get(),
                              self.increment.get(),
                              int(self.digits.get()))

    def build_new_filename(self, serial):
        return H.build_new_filename(serial,
                                    self.file_prefix.get(),
                                    self.file_extension.get())

    # ==================================================================
    # 预览签名 / TOCTOU / 冲突
    # ==================================================================
    def _compute_signature(self):
        file_sig = tuple((f['name'], f['mtime']) for f in self.files)
        param_sig = (
            self.file_prefix.get(),
            self.file_extension.get(),
            self.start_number.get(),
            self.digits.get(),
            self.increment.get(),
            self.filter_ext_var.get(),
        )
        return (file_sig, param_sig)

    def _detect_directory_changes(self):
        directory = self.dir_path.get()
        current = {}
        try:
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                if os.path.isfile(item_path):
                    try:
                        st = os.stat(item_path)
                        current[item] = st.st_mtime
                    except OSError:
                        pass
        except Exception as e:
            return {
                'changed': True,
                'added': [], 'removed': [], 'modified': [],
                'error': f'无法重新读取目录：{e}',
            }

        snapshot = {f['name']: f['mtime'] for f in self.files}
        current_names = set(current.keys())
        snapshot_names = set(snapshot.keys())

        raw_filter = self.filter_ext_var.get()
        if H.parse_filter(raw_filter) is not None:
            current_names = {n for n in current_names if H.matches_filter(n, raw_filter)}
            snapshot_names = {n for n in snapshot_names if H.matches_filter(n, raw_filter)}

        added = sorted(current_names - snapshot_names)
        removed = sorted(snapshot_names - current_names)

        modified = []
        for name in current_names & snapshot_names:
            if abs(current[name] - snapshot[name]) > 1.0:
                modified.append(name)
        modified.sort()

        return {
            'changed': bool(added or removed or modified),
            'added': added, 'removed': removed, 'modified': modified,
            'error': None,
        }

    def _show_directory_changed_warning(self, changes):
        lines = []
        if changes.get('error'):
            lines.append(changes['error'])
            lines.append("")
        else:
            lines.append("预览之后，目录内容发生了变化。")
            lines.append("")

        for label, key in [("新增文件", 'added'),
                           ("被删除的文件", 'removed'),
                           ("被修改的文件", 'modified')]:
            items = changes[key]
            if items:
                lines.append(f"【{label}】（{len(items)} 个）")
                for n in items[:8]:
                    lines.append(f"  · {n}")
                if len(items) > 8:
                    lines.append(f"  ……（还有 {len(items) - 8} 个）")
                lines.append("")

        lines.append("为避免冲突或数据丢失，请点击「刷新文件列表」，")
        lines.append("再点击「预览重命名」重新确认。")
        Messagebox.show_warning("\n".join(lines), "目录已变化", parent=self.root)

    def _detect_conflicts(self, mappings):
        conflicts = []

        target_map = defaultdict(lambda: {'display': None, 'sources': []})
        for old, new in mappings:
            if old == new:
                continue
            key = os.path.normcase(new)
            if target_map[key]['display'] is None:
                target_map[key]['display'] = new
            target_map[key]['sources'].append(old)

        for key, info in target_map.items():
            if len(info['sources']) > 1:
                conflicts.append({
                    'type': 'duplicate',
                    'target': info['display'],
                    'sources': info['sources'],
                })

        directory = self.dir_path.get()
        try:
            existing = {os.path.normcase(f) for f in os.listdir(directory)}
        except Exception:
            existing = set()

        rename_sources = {os.path.normcase(old) for old, _ in mappings}

        for old, new in mappings:
            if old == new:
                continue
            new_key = os.path.normcase(new)
            old_key = os.path.normcase(old)
            if new_key in existing and new_key != old_key and new_key not in rename_sources:
                conflicts.append({
                    'type': 'overwrite',
                    'source': old, 'target': new, 'victim': new,
                })

        return conflicts

    def _show_conflict_warning(self, conflicts):
        dup = [c for c in conflicts if c['type'] == 'duplicate']
        over = [c for c in conflicts if c['type'] == 'overwrite']

        lines = ["检测到命名冲突，已禁止执行重命名。\n"]

        if dup:
            lines.append(f"【一】目标文件名重复（{len(dup)} 组）：")
            for i, c in enumerate(dup[:5], 1):
                lines.append(f"  {i}. 目标名「{c['target']}」将被以下 "
                             f"{len(c['sources'])} 个文件同时占用：")
                for s in c['sources'][:8]:
                    lines.append(f"        · {s}")
                if len(c['sources']) > 8:
                    lines.append(f"        ……（还有 {len(c['sources']) - 8} 个）")
            if len(dup) > 5:
                lines.append(f"  ……（还有 {len(dup) - 5} 组未列出）")
            lines.append("")

        if over:
            lines.append(f"【二】目标名与现有文件重名（{len(over)} 处）：")
            for c in over[:5]:
                lines.append(f"  · {c['source']}  →  {c['target']}（会覆盖现有文件）")
            if len(over) > 5:
                lines.append(f"  ……（还有 {len(over) - 5} 处未列出）")
            lines.append("")

        lines.append("建议：")
        if dup and self.is_decimal_mode():
            try:
                cur_d = int(self.digits.get())
            except ValueError:
                cur_d = 0
            min_d = H.find_min_decimal_digits(
                self.start_number.get().strip(),
                self.increment.get().strip(),
                len(self.files))
            if min_d is not None and min_d > cur_d:
                lines.append(f"  · 将「序号位数」从 {cur_d} 改为 {min_d}，即可避免重复")
            else:
                lines.append("  · 增大「序号位数」，避免小数精度不足导致重名")
        else:
            lines.append("  · 增大「序号位数」，避免小数精度不足导致重名")
        lines.append("  · 修改「文件名前缀」或「扩展名」")
        lines.append("  · 调整「排序方式」，让编号分配更合理")

        Messagebox.show_error("\n".join(lines), "命名冲突", parent=self.root)

    # ==================================================================
    # 预览
    # ==================================================================
    def preview_rename(self):
        if not self.validate_inputs():
            return

        ok, errs = H.validate_filenames_for_preview(
            self.file_prefix.get(), self.file_extension.get(), None)
        if not ok:
            self.preview_data = None
            self.preview_signature = None
            self.set_status("⚠ 检测到非法文件名，已禁止执行", kind=H.STATUS_ERROR)
            msg = "检测到非法文件名，已禁止执行重命名。\n\n"
            for e in errs[:10]:
                msg += f"  · {e}\n"
            if len(errs) > 10:
                msg += f"  ……（共 {len(errs)} 条）\n"
            msg += "\n请修改「文件名前缀」或「文件扩展名」后重试。"
            Messagebox.show_error(msg, "非法文件名", parent=self.root)
            return

        directory = self.dir_path.get()
        if not directory or not os.path.exists(directory):
            Messagebox.show_error("请选择有效的目录", "错误", parent=self.root)
            return
        if not self.files:
            if self.all_files_count > 0:
                Messagebox.show_warning(
                    f"当前过滤条件下没有匹配的文件。\n\n"
                    f"目录中共有 {self.all_files_count} 个文件，但都被"
                    f"「过滤扩展名」条件排除了。\n"
                    f"请调整过滤条件，或留空以处理所有文件。",
                    "无匹配文件", parent=self.root)
            else:
                Messagebox.show_warning("目录中没有文件", "警告", parent=self.root)
            return

        mappings = []
        for index, file_info in enumerate(self.files):
            old = file_info['name']
            serial = self.build_serial(index)
            new = self.build_new_filename(serial)
            mappings.append((old, new))

        # 二次校验（含 mappings 级别）
        ok, errs = H.validate_filenames_for_preview(
            self.file_prefix.get(), self.file_extension.get(), mappings)
        if not ok:
            self.preview_data = None
            self.preview_signature = None
            self.set_status("⚠ 检测到非法文件名，已禁止执行", kind=H.STATUS_ERROR)
            msg = "检测到非法文件名，已禁止执行重命名。\n\n"
            for e in errs[:10]:
                msg += f"  · {e}\n"
            if len(errs) > 10:
                msg += f"  ……（共 {len(errs)} 条）\n"
            Messagebox.show_error(msg, "非法文件名", parent=self.root)
            return

        conflicts = self._detect_conflicts(mappings)
        conflict_targets = {os.path.normcase(c['target']) for c in conflicts}

        self.tree.delete(*self.tree.get_children())
        for (old, new), file_info in zip(mappings, self.files):
            tags = ('conflict',) if os.path.normcase(new) in conflict_targets else ()
            self.tree.insert("", END, values=(
                f"{old} -> {new}",
                H.format_file_size(file_info['size']),
                file_info['type'],
                H.format_time(file_info['mtime']),
            ), tags=tags)

        if conflicts:
            self.preview_data = None
            self.preview_signature = None
            self.set_status(
                f"⚠ 检测到 {len(conflicts)} 处命名冲突，已禁止执行",
                kind=H.STATUS_ERROR)
            self._show_conflict_warning(conflicts)
            return

        self.preview_data = mappings
        self.preview_signature = self._compute_signature()

        mismatched_count = self._count_extension_mismatches(mappings)
        if mismatched_count > 0:
            self.set_status(
                f"⚠ 预览完成：共 {len(mappings)} 个文件，"
                f"但 {mismatched_count} 个文件的扩展名将改变，请确认",
                kind=H.STATUS_WARNING)
        else:
            self.set_status(
                f"✓ 预览完成：共 {len(mappings)} 个文件，无冲突，可执行重命名 (Ctrl+Enter)",
                kind=H.STATUS_SUCCESS)

    def _count_extension_mismatches(self, mappings):
        out_ext = self.file_extension.get()
        if not out_ext.startswith('.'):
            out_ext = '.' + out_ext
        out_ext = out_ext.lower()
        count = 0
        for old, _new in mappings:
            old_ext = Path(old).suffix.lower()
            if old_ext and old_ext != out_ext:
                count += 1
        return count

    # ==================================================================
    # 执行
    # ==================================================================
    def execute_rename(self):
        try:
            self._execute_rename_impl()
        except Exception as e:
            H.log(f"execute_rename 异常：{e}\n{traceback.format_exc()}")
            Messagebox.show_error(f"执行重命名时发生异常：\n\n{e}",
                                  "异常", parent=self.root)

    def _execute_rename_impl(self):
        H.log("execute_rename 被调用")

        if not self.preview_data:
            Messagebox.show_warning(
                "请先点击「预览重命名」，确认无冲突后再执行。\n\n快捷键：Ctrl+R",
                "请先预览", parent=self.root)
            return

        if self._compute_signature() != self.preview_signature:
            self.preview_data = None
            self.preview_signature = None
            Messagebox.show_warning("文件列表或参数已发生变化，请重新预览。",
                                    "预览已失效", parent=self.root)
            return

        ok, errs = H.validate_filenames_for_preview(
            self.file_prefix.get(), self.file_extension.get(), self.preview_data)
        if not ok:
            self.preview_data = None
            self.preview_signature = None
            self.set_status("⚠ 检测到非法文件名，已禁止执行", kind=H.STATUS_ERROR)
            msg = "检测到非法文件名，已禁止执行重命名。\n\n"
            for e in errs[:10]:
                msg += f"  · {e}\n"
            if len(errs) > 10:
                msg += f"  ……（共 {len(errs)} 条）\n"
            Messagebox.show_error(msg, "非法文件名", parent=self.root)
            return

        changes = self._detect_directory_changes()
        if changes['changed']:
            self.preview_data = None
            self.preview_signature = None
            self.set_status("⚠ 目录已变化，请重新预览", kind=H.STATUS_WARNING)
            self._show_directory_changed_warning(changes)
            return

        conflicts = self._detect_conflicts(self.preview_data)
        if conflicts:
            self.preview_data = None
            self.preview_signature = None
            self._show_conflict_warning(conflicts)
            return

        mismatched_count = self._count_extension_mismatches(self.preview_data)
        confirm_msg = f"即将重命名 {len(self.preview_data)} 个文件，操作不可撤销。\n\n"
        if mismatched_count > 0:
            out_ext = self.file_extension.get()
            if not out_ext.startswith('.'):
                out_ext = '.' + out_ext
            confirm_msg += (
                f"⚠ 注意：{mismatched_count} 个文件的扩展名将被改为 {out_ext}，"
                f"但文件内容不会转换。\n"
                f"例如 .txt 文件被改成 .png 后，双击可能无法正常打开。\n\n")
        confirm_msg += "是否继续？"

        if not self._ask_yes_no(confirm_msg, "确认重命名"):
            H.log("用户取消了确认，不执行重命名")
            return

        H.log("用户确认，开始重命名")

        self._progress_queue = queue.Queue()
        directory = self.dir_path.get()
        mappings = list(self.preview_data)
        total = len(mappings)

        self._progress_dialog = dialogs.ProgressDialog(
            self.root, total,
            on_cancel=self._on_cancel_clicked,
            font=self.font, font_bold=self.font_bold, log_func=H.log,
        )
        self._set_buttons_state('disabled')
        self._cancel_event.clear()

        self.set_status(f"正在重命名 {total} 个文件...", kind=H.STATUS_INFO)

        self._worker_thread = threading.Thread(
            target=file_ops.run_rename_worker,
            args=(directory, mappings, self._progress_queue, self._cancel_event),
            daemon=True,
        )
        self._worker_thread.start()
        H.log("工作线程已启动")

        self._poll_worker_queue()

    def _on_cancel_clicked(self):
        if self._cancel_event.is_set():
            return
        self._cancel_event.set()
        H.log("用户点击了取消按钮")
        if self._progress_dialog:
            self._progress_dialog.set_cancelling()

    def _poll_worker_queue(self):
        self._poll_after_id = None
        if self._progress_queue is None:
            return

        done = False
        try:
            while True:
                msg = self._progress_queue.get_nowait()
                if msg[0] == 'progress':
                    _, stage, current, total, old, new = msg
                    if self._progress_dialog:
                        self._progress_dialog.update(stage, current, total, old, new)
                elif msg[0] == 'done':
                    _, result = msg
                    self._on_rename_complete(result)
                    done = True
                    break
        except queue.Empty:
            pass

        if not done:
            self._poll_after_id = self.root.after(100, self._poll_worker_queue)

    def _on_rename_complete(self, result):
        H.log(f"_on_rename_complete：{result}")
        if self._progress_dialog:
            self._progress_dialog.close()
        self._progress_dialog = None

        was_cancelled = result.get('cancelled', False)

        if result['success']:
            Messagebox.show_info(f"重命名完成！\n成功：{result['renamed']} 个文件",
                                 "完成", parent=self.root)
            self.set_status(f"✓ 重命名完成，成功 {result['renamed']} 个文件",
                            kind=H.STATUS_SUCCESS)
        elif was_cancelled:
            if result['rollback_errors']:
                msg = "已取消重命名，但部分文件未能自动回滚。\n\n"
                msg += f"【未回滚的文件】（共 {len(result['rollback_errors'])} 个，需手动处理）\n"
                for e in result['rollback_errors'][:10]:
                    msg += f"  · {e}\n"
                if len(result['rollback_errors']) > 10:
                    msg += f"  ……（还有 {len(result['rollback_errors']) - 10} 个未列出）\n"
                msg += "\n请根据上述「当前实际名称」在文件管理器中手动恢复。"
                Messagebox.show_error(msg, "已取消（部分未回滚）", parent=self.root)
                self.set_status("✗ 已取消，但有文件未回滚", kind=H.STATUS_ERROR)
            else:
                Messagebox.show_info("已取消重命名，所有文件已恢复到初始状态。",
                                     "已取消", parent=self.root)
                self.set_status("已取消，所有文件已回滚到初始状态",
                                kind=H.STATUS_WARNING)
        else:
            msg = self._format_failure_message(result)
            if result['rollback_errors']:
                Messagebox.show_error(msg, "失败（部分未回滚）", parent=self.root)
                self.set_status(f"✗ 重命名失败，{len(result['rollback_errors'])} 个文件未回滚",
                                kind=H.STATUS_ERROR)
            else:
                Messagebox.show_error(msg, "失败（已回滚）", parent=self.root)
                self.set_status("✗ 重命名失败，所有文件已回滚到初始状态",
                                kind=H.STATUS_ERROR)

        self.preview_data = None
        self.preview_signature = None
        self._set_buttons_state('normal')
        self.refresh_file_list()

    def _format_failure_message(self, result):
        lines = []
        if result['rollback_errors']:
            lines.append("重命名失败，且有部分文件未能自动回滚。\n")
            lines.append("【失败原因】")
            for e in result['errors'][:3]:
                lines.append(f"  · {e}")
            if len(result['errors']) > 3:
                lines.append(f"  ……（共 {len(result['errors'])} 条）")
            lines.append("")
            lines.append(f"【未回滚的文件】（共 {len(result['rollback_errors'])} 个，需手动处理）")
            for e in result['rollback_errors'][:10]:
                lines.append(f"  · {e}")
            if len(result['rollback_errors']) > 10:
                lines.append(f"  ……（还有 {len(result['rollback_errors']) - 10} 个未列出）")
            lines.append("")
            lines.append("请根据上述「当前实际名称」在文件管理器中手动恢复。")
        else:
            lines.append("重命名失败，所有文件已回滚到初始状态。\n")
            lines.append("【失败原因】")
            for e in result['errors'][:5]:
                lines.append(f"  · {e}")
            if len(result['errors']) > 5:
                lines.append(f"  ……（共 {len(result['errors'])} 条）")
        return "\n".join(lines)

    def _set_buttons_state(self, state):
        for btn in (self.execute_btn, self.preview_btn,
                    self.refresh_btn, self.browse_btn):
            try:
                btn.configure(state=state)
            except Exception:
                pass

    # ==================================================================
    # 校验入口
    # ==================================================================
    def validate_inputs(self):
        directory = self.dir_path.get()
        if not directory or not os.path.exists(directory):
            Messagebox.show_error("请选择有效的目录", "错误", parent=self.root)
            return False

        if not self.file_extension.get():
            Messagebox.show_error("请输入文件扩展名", "错误", parent=self.root)
            return False

        ok, err = H.validate_serial_inputs(
            self.start_number.get().strip(),
            self.increment.get().strip(),
            self.digits.get().strip(),
        )
        if not ok:
            Messagebox.show_error(err, "错误", parent=self.root)
            return False

        return True

    # ==================================================================
    # 窗口居中
    # ==================================================================
    def _center_window(self, win_w, win_h):
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - win_w) // 2)
        y = max(0, (screen_h - win_h) // 2 - 20)
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")


if __name__ == "__main__":
    root = ttkb.Window(title="批量重命名工具", themename="bootstrap-light")
    app = FileRenamerApp(root)
    root.mainloop()
