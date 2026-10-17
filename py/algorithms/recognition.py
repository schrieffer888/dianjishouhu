"""活动识别基线：模板估计 + 因果在线识别。

- 仅接收截至当前时刻的总功率，估计活动与未知状态。
- 相似功率、同时启停、未覆盖负荷允许输出"unknown"。
- 自动背景负荷（冰箱）被识别但不计入主动活动证据。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from configs import defaults as C
from .detection import find_edges


def estimate_templates(truth_activities: pd.DataFrame) -> dict[str, float]:
    """从训练期分表真值估计每类电器的功率模板（仅用于训练标签/模板估计）。"""
    return truth_activities.groupby("appliance")["power_w"].mean().to_dict()


def match_magnitude(mag: float, templates: dict[str, float],
                    tol_rel: float = C.TOL_REL,
                    tol_abs: float = C.TOL_ABS_W) -> str | None:
    """把跳变幅度匹配到最近的已知模板，容差内返回电器名，否则 None（未知）。"""
    best: str | None = None
    best_err = np.inf
    for app, p in templates.items():
        tol = max(tol_abs, p * tol_rel)
        if abs(mag - p) <= tol:
            err = abs(mag - p)
            if err < best_err:
                best = app
                best_err = err
    return best


class Recognizer:
    def __init__(self, templates: dict[str, float], auto_appliances: set[str],
                 edge_min: float = C.EDGE_MIN_W,
                 min_on_dur: float = C.MIN_ON_DURATION_SEC,
                 sampling: float = C.SAMPLING_PERIOD_SEC) -> None:
        self.templates = templates
        self.auto = auto_appliances
        self.edge_min = edge_min
        self.min_on_dur = min_on_dur
        self.sampling = sampling

    def recognize(self, timestamps, power: np.ndarray,
                  quality: np.ndarray) -> pd.DataFrame:
        """在线识别，返回活动 DataFrame(appliance,start,end,matched,is_auto,day)。"""
        ts = np.asarray(timestamps)  # 按位置取值
        ok = quality == "ok"
        idx = np.flatnonzero(ok)
        p = power[ok]
        edges = find_edges(idx, p, self.edge_min)

        on: dict[str, int | None] = {app: None for app in self.templates}
        unknown_start: int | None = None
        unknown_level = 0
        activities: list[dict] = []

        def close(app: str, s: int, e: int, matched: bool, is_auto: bool) -> None:
            if (e - s) * self.sampling >= self.min_on_dur:
                activities.append({
                    "appliance": app,
                    "start": pd.Timestamp(ts[s]),
                    "end": pd.Timestamp(ts[e]),
                    "matched": matched,
                    "is_auto": is_auto,
                    "day": pd.Timestamp(ts[s]).normalize(),
                })

        for e in edges:
            app = match_magnitude(e.magnitude, self.templates)
            if e.sign > 0:
                if app is not None:
                    if on[app] is not None:
                        unknown_level += 1
                        if unknown_start is None:
                            unknown_start = e.index
                    else:
                        on[app] = e.index
                else:
                    unknown_level += 1
                    if unknown_start is None:
                        unknown_start = e.index
            else:  # off
                if app is not None:
                    s = on[app]
                    if s is not None:
                        close(app, s, e.index, True, app in self.auto)
                        on[app] = None
                else:
                    unknown_level -= 1
                    if unknown_level <= 0:
                        if unknown_start is not None:
                            close("unknown", unknown_start, e.index, False, False)
                        unknown_start = None
                        unknown_level = 0

        # 收尾：仍未关闭的活动，关闭到最后 ok 样本
        last_ok = int(idx[-1]) if len(idx) else 0
        for app, s in on.items():
            if s is not None:
                close(app, s, last_ok, True, app in self.auto)
        if unknown_start is not None:
            close("unknown", unknown_start, last_ok, False, False)

        return pd.DataFrame(activities)
