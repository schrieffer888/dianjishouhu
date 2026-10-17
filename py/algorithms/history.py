"""个体历史规律：从历史日识别结果学习使用时间窗、出现比例与稳定性。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from configs import defaults as C


@dataclass
class Window:
    appliance: str
    span_min: float          # 通常窗口起始（小时）
    span_max: float          # 通常窗口结束（小时）
    appearance_ratio: float  # 出现比例
    valid_days: int          # 有效历史日
    count: int               # 窗口内活动次数


def _hour(t: pd.Series) -> np.ndarray:
    return (t.dt.hour + t.dt.minute / 60.0 + t.dt.second / 3600.0).to_numpy()


def learn_windows(hist_activities: pd.DataFrame, valid_days: int,
                  gap_hours: float = 2.0) -> dict[str, list[Window]]:
    """从历史日匹配活动学习每个目标电器的使用时间窗。

    只学习"匹配到已知模板且非自动"的目标活动。
    用单链聚类把相邻开始时刻合并为时间窗。
    """
    windows: dict[str, list[Window]] = {}
    act = hist_activities[hist_activities["matched"] & ~hist_activities["is_auto"]]
    if act.empty:
        return windows

    for app, grp in act.groupby("appliance"):
        starts = _hour(grp["start"])
        order = np.argsort(starts)
        sorted_starts = starts[order]
        sorted_days = grp["day"].to_numpy()[order]

        clusters: list[list[float]] = []
        cur = [float(sorted_starts[0])]
        for s in sorted_starts[1:]:
            if s - cur[-1] <= gap_hours:
                cur.append(float(s))
            else:
                clusters.append(cur)
                cur = [float(s)]
        clusters.append(cur)

        app_windows: list[Window] = []
        for cl in clusters:
            lo, hi = min(cl), max(cl)
            in_range = (starts >= lo) & (starts <= hi)
            days_with = grp.loc[in_range, "day"].nunique()
            ratio = days_with / valid_days if valid_days else 0.0
            app_windows.append(Window(app, lo, hi, ratio, valid_days, len(cl)))
        windows[app] = app_windows

    return windows


def is_stable(w: Window,
              min_days: int = C.MIN_HISTORY_DAYS,
              min_ratio: float = C.MIN_APPEARANCE_RATIO) -> bool:
    """仅对较稳定活动提醒（≥7 有效历史日且出现比例 ≥70%）。"""
    return w.valid_days >= min_days and w.appearance_ratio >= min_ratio
