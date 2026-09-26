"""文件系统操作：两阶段重命名 + 回滚。无 UI 依赖。"""
import os
import uuid


def two_phase_rename(directory, mappings,
                     progress_callback=None, cancel_check=None):
    """
    两阶段重命名：
      阶段 1：源名 → 唯一临时名
      阶段 2：临时名 → 最终名

    返回 dict: {success, renamed, errors, rollback_errors, cancelled}
    """
    actual = [(old, new) for old, new in mappings if old != new]
    if not actual:
        return {
            'success': True, 'renamed': 0,
            'errors': [], 'rollback_errors': [], 'cancelled': False,
        }

    total = len(actual)

    # 生成唯一临时名前缀
    tmp_prefix = None
    for _ in range(10):
        candidate = f".__rn_tmp_{uuid.uuid4().hex[:8]}__"
        clash = False
        for i in range(total):
            if os.path.exists(os.path.join(directory, f"{candidate}{i:05d}")):
                clash = True
                break
        if not clash:
            tmp_prefix = candidate
            break

    if tmp_prefix is None:
        return {
            'success': False, 'renamed': 0,
            'errors': ["无法生成唯一的临时文件名前缀，请检查目录权限或重试"],
            'rollback_errors': [], 'cancelled': False,
        }

    # 阶段 1：源名 → 临时名
    stage1_done = []
    stage1_errors = []
    for i, (old, new) in enumerate(actual):
        if cancel_check and cancel_check():
            stage1_errors.append("用户取消操作")
            break

        src = os.path.join(directory, old)
        temp_name = f"{tmp_prefix}{i:05d}"
        temp_path = os.path.join(directory, temp_name)

        if not os.path.exists(src):
            stage1_errors.append(f"源文件不存在：「{old}」")
            break
        try:
            os.rename(src, temp_path)
            stage1_done.append((old, temp_name, new))
            if progress_callback:
                progress_callback(1, i + 1, total, old, temp_name)
        except Exception as e:
            stage1_errors.append(f"「{old}」改临时名失败：{e}")
            break

    if stage1_errors:
        _, rb_fail = rollback(directory, stage1_done)
        cancelled = any("取消" in e for e in stage1_errors)
        return {
            'success': False, 'renamed': 0,
            'errors': stage1_errors,
            'rollback_errors': rb_fail,
            'cancelled': cancelled,
        }

    # 阶段 2：临时名 → 最终名
    stage2_done = []
    stage2_errors = []
    for i, (old, temp_name, new) in enumerate(stage1_done):
        if cancel_check and cancel_check():
            stage2_errors.append("用户取消操作")
            break

        temp_path = os.path.join(directory, temp_name)
        final_path = os.path.join(directory, new)

        if os.path.exists(final_path) and \
           os.path.abspath(final_path) != os.path.abspath(temp_path):
            stage2_errors.append(f"「{old} → {new}」目标名已被其他文件占用")
            break
        try:
            os.rename(temp_path, final_path)
            stage2_done.append((old, temp_name, new))
            if progress_callback:
                progress_callback(2, i + 1, total, old, new)
        except Exception as e:
            stage2_errors.append(f"「{old} → {new}」失败：{e}")
            break

    if stage2_errors:
        _, rb_fail = rollback(directory, stage1_done)
        cancelled = any("取消" in e for e in stage2_errors)
        return {
            'success': False, 'renamed': 0,
            'errors': stage2_errors,
            'rollback_errors': rb_fail,
            'cancelled': cancelled,
        }

    return {
        'success': True,
        'renamed': len(stage2_done),
        'errors': [],
        'rollback_errors': [],
        'cancelled': False,
    }


def rollback(directory, stage1_done):
    """把 stage1_done 中的文件恢复原名。返回 (成功数, 失败列表)。"""
    success = 0
    failures = []

    for old, temp_name, new_name in stage1_done:
        src = os.path.join(directory, old)
        temp_path = os.path.join(directory, temp_name)
        final_path = os.path.join(directory, new_name)

        if os.path.exists(temp_path):
            current_path = temp_path
        elif os.path.exists(final_path):
            current_path = final_path
        elif os.path.exists(src):
            success += 1
            continue
        else:
            failures.append(f"「{old}」：文件已不在预期位置（可能被外部程序移动或删除）")
            continue

        try:
            os.rename(current_path, src)
            success += 1
        except Exception as e:
            current_basename = os.path.basename(current_path)
            failures.append(
                f"「{old}」：当前实际名称为「{current_basename}」，改回原名失败：{e}"
            )

    return success, failures


def run_rename_worker(directory, mappings, progress_queue, cancel_event):
    """工作线程入口。通过 queue 与主线程通信。"""
    def progress_callback(stage, current, total, old, new):
        progress_queue.put(('progress', stage, current, total, old, new))

    def cancel_check():
        return cancel_event.is_set()

    try:
        result = two_phase_rename(
            directory, mappings,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
    except Exception as e:
        result = {
            'success': False,
            'renamed': 0,
            'errors': [f"未预期的内部错误：{e}"],
            'rollback_errors': [],
            'cancelled': False,
        }

    progress_queue.put(('done', result))
