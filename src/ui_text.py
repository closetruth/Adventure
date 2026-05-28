"""界面文案格式化（避免 emoji 在 Windows 默认字体下显示为方框）。"""


def format_pending(gold: int, diamond: int) -> str:
    """待领取奖励一行文案。"""
    parts = []
    if gold:
        parts.append(f"金币 {gold}")
    if diamond:
        parts.append(f"钻石 {diamond}")
    if not parts:
        return "待领 无"
    return "待领 " + " · ".join(parts)


def format_reward_gain(gold: int, diamond: int) -> str:
    """完成任务时的奖励说明。"""
    parts = []
    if gold:
        parts.append(f"{gold} 金币")
    if diamond:
        parts.append(f"{diamond} 钻石")
    if not parts:
        return "无奖励"
    return "、".join(parts)
