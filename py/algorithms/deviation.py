"""偏离判断：习惯活动缺失、活动显著延迟或间隔过长。

按"窗口归属"判断：某电器的每个历史时间窗独立判定是否被当天活动填满；
未填满时，若在相邻窗口之间存在"游离活动"，判为延迟，否则判为缺失。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from configs import defaults as C
from .history import Window


@dataclass
class Deviation:
    appliance: str
    kind: str                  # "missing" | "delay"
    span_min: float
    span_max: float
    delay_hours: float | None


def _hour(t: pd.Timestamp) -> float:
    return t.hour + t.minute / 60.0 + t.second / 3600.0


def classify_appliance(appliance: str, windows: list[Window],
                       test_activities: pd.DataFrame,
                       tolerance_min: float = C.TOLERANCE_MINUTES) -> list[Deviation]:
    """对某电器按历史时间窗逐窗口判定偏离。windows 需按 span_max 升序。"""
    tol_h = tolerance_min / 60.0
    acts = test_activities[(test_activities["appliance"] == appliance) &
                           (test_activities["matched"])]
    hours = sorted(_hour(a["start"]) for _, a in acts.iterrows())

    ws = sorted(windows, key=lambda w: w.span_max)
    deviations: list[Deviation] = []
    for i, w in enumerate(ws):
        lo, hi = w.span_min, w.span_max
        filled = any(lo - 0.5 <= h <= hi + tol_h for h in hours)
        if filled:
            continue
        # 相邻窗口之间是否存在游离活动（属于本窗口但延迟出现）
        next_lo = ws[i + 1].span_min - 0.5 if i + 1 < len(ws) else 24.0
        stray = [h for h in hours if hi + tol_h < h < next_lo]
        if stray:
            deviations.append(Deviation(appliance, "delay", lo, hi, min(stray) - hi))
        else:
            deviations.append(Deviation(appliance, "missing", lo, hi, None))
    return deviations
