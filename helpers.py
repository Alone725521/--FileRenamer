"""通用工具函数：常量、日志、校验、命名、格式化、UI 样式。"""
import os
import re
from datetime import datetime
from pathlib import Path

import ttkbootstrap as ttkb


# ======================================================================
# 常量
# ======================================================================
STATUS_IDLE = "secondary"
STATUS_INFO = "info"
STATUS_SUCCESS = "success"
STATUS_WARNING = "warning"
STATUS_ERROR = "danger"

SHORTCUTS = [
    ("Ctrl+O",     "打开目录"),
    ("F5",         "刷新文件列表"),
    ("Ctrl+R",     "预览重命名"),
    ("Ctrl+Enter", "执行重命名"),
    ("Ctrl+S",     "应用排序"),
    ("Ctrl+1",     "排序依据 → 名称"),
    ("Ctrl+2",     "排序依据 → 修改时间"),
    ("Ctrl+3",     "排序依据 → 大小"),
    ("Ctrl+4",     "排序依据 → 类型"),
    ("Ctrl+D",     "切换排序方向（升序 / 降序）"),
    ("F1",         "显示快捷键帮助"),
    ("Ctrl+Q",     "退出程序"),
]

INVALID_CHARS = '<>:"/\\|?*'
RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
}
MAX_NAME_BYTES = 255

THEME_EXCLUDE = {'default', 'classic', 'vista', 'xpnative',
                 'winnative', 'clam', 'alt'}
THEME_BASE_NAMES_CN = {
    'bootstrap': '引导', 'pydata': '派数据', 'nord': '北欧',
    'solarized': '日光', 'catppuccin': '卡布奇诺', 'gruvbox': '格鲁夫',
    'dracula': '德古拉', 'tokyo-night': '东京夜', 'one': '一',
    'everforest': '常绿森林', 'vapor': '蒸汽', 'minty': '薄荷',
    'pulse': '脉冲', 'united': '联合', 'sandstone': '砂岩',
    'litera': '文学', 'morph': '形态', 'journal': '日志',
    'darkly': '暗黑', 'superhero': '超级英雄', 'cyborg': '赛博格',
    'flatly': '扁平', 'simplex': '简约', 'cerculean': '蔚蓝',
    'cosmo': '宇宙', 'lumen': '流明', 'yeti': '雪人',
}


# ======================================================================
# 日志
# ======================================================================
LOG_PATH = os.path.join(os.path.expanduser("~"), "rename_debug.log")


def log(msg: str):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ======================================================================
# 校验
# ======================================================================
def validate_component(s, name="字段"):
    if s is None or s == "":
        return True, ""
    for ch in s:
        if ch in INVALID_CHARS:
            return False, f"「{name}」包含非法字符「{ch}」"
        if ord(ch) < 32:
            return False, f"「{name}」包含控制字符（ASCII {ord(ch)}）"
    return True, ""


def validate_output_name(filename):
    if not filename:
        return False, "文件名为空"
    for ch in filename:
        if ch in INVALID_CHARS:
            return False, f"包含非法字符「{ch}」"
        if ord(ch) < 32:
            return False, f"包含控制字符（ASCII {ord(ch)}）"
    byte_len = len(filename.encode('utf-8'))
    if byte_len > MAX_NAME_BYTES:
        return False, f"文件名过长（{byte_len} 字节，超过 {MAX_NAME_BYTES} 字节上限）"
    if filename.endswith(' ') or filename.endswith('.'):
        return False, "文件名不能以空格或点号结尾"
    stem = Path(filename).stem.upper()
    if stem in RESERVED_NAMES:
        return False, f"使用了系统保留名称「{stem}」"
    return True, ""


def validate_extension(ext):
    ok, err = validate_component(ext, "文件扩展名")
    if not ok:
        return False, err
    ext_stripped = ext.lstrip('.')
    if '.' in ext_stripped:
        return False, "「文件扩展名」中只能有一个点号（如 png 或 .png，不能是 a.b）"
    return True, ""


def validate_serial_inputs(start_str, inc_str, digits_str):
    try:
        start = float(start_str) if '.' in start_str else int(start_str)
        if start < 0:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        return False, "起始序号必须是有效的数字（如 1 或 1.1）"

    try:
        inc = float(inc_str) if '.' in inc_str else int(inc_str)
        if inc <= 0:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        return False, "每次增加必须是有效的正数（如 1 或 0.1）"

    try:
        digits = int(digits_str)
        if digits <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return False, "序号位数必须是有效的正整数"

    return True, ""


def validate_filenames_for_preview(prefix, ext, mappings=None):
    errors = []
    ok, err = validate_component(prefix, "文件名前缀")
    if not ok:
        errors.append(err)
    ok, err = validate_extension(ext)
    if not ok:
        errors.append(err)
    if errors:
        return False, errors
    if mappings is None:
        return True, []

    seen_err = set()
    for _old, new in mappings:
        ok, err = validate_output_name(new)
        if not ok:
            key = err.split('（')[0]
            if key not in seen_err:
                errors.append(f"目标名「{new}」：{err}")
                seen_err.add(key)
    return (len(errors) == 0), errors


# ======================================================================
# 命名 / 序号
# ======================================================================
def is_decimal_mode(start_str, inc_str):
    return ('.' in start_str.strip()) or ('.' in inc_str.strip())


def build_serial(index, start_str, inc_str, digits):
    start_str = start_str.strip()
    inc_str = inc_str.strip()
    if is_decimal_mode(start_str, inc_str):
        start = float(start_str)
        inc = float(inc_str)
        return f"{start + index * inc:.{digits}f}"
    else:
        start = int(start_str)
        inc = int(inc_str)
        return f"{start + index * inc:0{digits}d}"


def build_new_filename(serial, prefix, ext):
    prefix_stripped = prefix.strip()
    if not ext.startswith('.'):
        ext = '.' + ext
    if prefix_stripped == "":
        return f"{serial}{ext}"
    return f"{prefix}_{serial}{ext}"


def natural_sort_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def find_min_decimal_digits(start_str, inc_str, count):
    start_str = start_str.strip()
    inc_str = inc_str.strip()
    if not is_decimal_mode(start_str, inc_str):
        return None
    if count <= 1:
        return 0
    try:
        start = float(start_str)
        inc = float(inc_str)
    except ValueError:
        return None
    for d in range(0, 11):
        seen = set()
        ok = True
        for k in range(count):
            s = f"{start + inc * k:.{d}f}"
            if s in seen:
                ok = False
                break
            seen.add(s)
        if ok:
            return d
    return 10


# ======================================================================
# 格式化
# ======================================================================
def format_file_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"


def format_time(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


# ======================================================================
# 过滤
# ======================================================================
def parse_filter(raw):
    """把用户输入的过滤字符串解析为扩展名集合，或 None。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    exts = set()
    for part in re.split(r'[,;\s]+', raw):
        part = part.strip().lower()
        if not part:
            continue
        if not part.startswith('.'):
            part = '.' + part
        exts.add(part)
    return exts or None


def matches_filter(name, raw_filter):
    exts = parse_filter(raw_filter)
    if exts is None:
        return True
    return Path(name).suffix.lower() in exts


# ======================================================================
# UI 辅助
# ======================================================================
def all_widgets(parent):
    """递归遍历所有子控件。"""
    result = []
    for child in parent.winfo_children():
        result.append(child)
        result.extend(all_widgets(child))
    return result


def apply_custom_styles(style, fonts):
    style.configure("Title.TLabel", font=fonts['title_font'])
    style.configure("Hint.TLabel", font=fonts['hint_font'], foreground="gray")
    style.configure("Section.TLabelframe", font=fonts['font_bold'], padding=(10, 10))
    style.configure("Section.TLabelframe.Label", font=fonts['font_bold'])
    style.configure("Treeview", font=fonts['font'], rowheight=26)
    style.configure("Treeview.Heading", font=fonts['font_bold'])
    style.configure("ParamHint.TLabel", font=fonts['font'],
                    foreground=style.colors.warning)


def refresh_combobox_style(style, root):
    """修复切换主题后 Combobox 的灰色残留。"""
    colors = style.colors
    field_bg = getattr(colors, "inputbg", colors.bg)
    field_fg = getattr(colors, "inputfg", colors.fg)
    border = getattr(colors, "border", colors.bg)

    try:
        style.configure(
            "TCombobox",
            fieldbackground=field_bg, background=colors.bg,
            foreground=field_fg, arrowcolor=colors.fg,
            bordercolor=border, lightcolor=field_bg, darkcolor=field_bg,
            selectbackground=field_bg, selectforeground=field_fg,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", field_bg), ("focus", field_bg),
                             ("!disabled", field_bg)],
            foreground=[("readonly", field_fg), ("focus", field_fg)],
            selectbackground=[("readonly", field_bg), ("focus", field_bg)],
            selectforeground=[("readonly", field_fg), ("focus", field_fg)],
            background=[("active", colors.bg), ("pressed", colors.bg)],
        )
    except Exception:
        pass

    try:
        root.option_add("*TCombobox*Listbox.background", field_bg)
        root.option_add("*TCombobox*Listbox.foreground", field_fg)
        root.option_add("*TCombobox*Listbox.selectBackground", colors.selectbg)
        root.option_add("*TCombobox*Listbox.selectForeground", colors.selectfg)
    except Exception:
        pass


def force_refresh_comboboxes(root):
    """切换主题后强制重绘所有 Combobox。"""
    root.update_idletasks()
    for w in all_widgets(root):
        if isinstance(w, ttkb.Combobox):
            try:
                if str(w.cget("state")) == "readonly":
                    w.configure(state="normal")
                    w.configure(state="readonly")
                w.update_idletasks()
            except Exception:
                pass
