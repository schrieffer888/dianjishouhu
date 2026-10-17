"""关怀模型：数据有效性门控 + 偏离判断 + 事件创建。

判定顺序（计划书 6.3）：
数据是否可用 → 是否外出 → 识别证据是否足够 → 是否偏离历史 → 新建或更新事件。
自动背景负荷不计入主动活动证据。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from configs import defaults as C
from .deviation import classify_appliance
from .event_state import CareEvent, EventStore
from .history import Window, is_stable


@dataclass
class CareDecision:
    appliance: str
    window: Window
    outcome: str           # "alert" | "insufficient" | "away" | "unstable"
    reason: str


def _fmt_span(w: Window) -> str:
    def hhmm(h: float) -> str:
        hh = int(h)
        mm = int(round((h - hh) * 60))
        return f"{hh:02d}:{mm:02d}"
    return f"{hhmm(w.span_min)}-{hhmm(w.span_max)}"


def _covered_by_interruption(window: Window, interruptions: list[tuple[float, float]],
                             tolerance_h: float) -> bool:
    lo, hi = window.span_min - 0.5, window.span_max + tolerance_h
    return any(not (b <= lo or a >= hi) for a, b in interruptions)


def evaluate_care(test_activities: pd.DataFrame, windows: dict[str, list[Window]],
                  away: bool, interruptions: list[tuple[float, float]],
                  test_day: pd.Timestamp, store: EventStore | None = None,
                  tolerance_min: float = C.TOLERANCE_MINUTES,
                  household_id: str = C.HOUSEHOLD_ID) -> tuple[list[CareDecision], list[CareEvent]]:
    """按时间顺序评估每个稳定窗口，返回 (判定, 新建事件)。"""
    store = store or EventStore()
    tol_h = tolerance_min / 60.0
    decisions: list[CareDecision] = []
    events: list[CareEvent] = []

    for app, ws in windows.items():
        ws_sorted = sorted(ws, key=lambda w: w.span_max)
        deviations = classify_appliance(app, ws_sorted, test_activities, tolerance_min)
        if not deviations:
            continue  # 所有窗口都正常出现，无需提醒

        for dev in deviations:
            w = next(w for w in ws_sorted
                     if abs(w.span_min - dev.span_min) < 1e-6 and abs(w.span_max - dev.span_max) < 1e-6)
            span_label = _fmt_span(w)

            if not is_stable(w):
                decisions.append(CareDecision(app, w, "unstable",
                                              "历史不足或出现比例不足，暂不提醒"))
                continue
            if _covered_by_interruption(w, interruptions, tol_h):
                decisions.append(CareDecision(app, w, "insufficient",
                                              f"数据中断跨越窗口 {span_label}，证据不足，暂缓判断"))
                continue
            if away:
                decisions.append(CareDecision(app, w, "away", "已设置外出，抑制行为提醒"))
                continue

            if dev.kind == "missing":
                reason = (f"过去 {w.valid_days} 个有效日有 {int(round(w.appearance_ratio * w.valid_days))} 日出现"
                          f"{app}，常见窗口 {span_label}，今天超过通常窗口 {tolerance_min} 分钟仍未观察到，建议确认。")
            else:
                delay_min = int(round((dev.delay_hours or 0.0) * 60))
                reason = (f"{app} 常见窗口 {span_label}，今天延迟约 {delay_min} 分钟后才出现，偏离历史规律，建议确认。")

            decisions.append(CareDecision(app, w, "alert", reason))
            key = store.dedup_key(app, dev.kind, w.span_min, w.span_max,
                                  test_day.strftime("%Y-%m-%d"))
            if store.exists(key):
                continue
            event = CareEvent(
                event_id=store.next_id(),
                household_id=household_id,
                appliance=app,
                kind=dev.kind,
                reason=reason,
                evidence_window=span_label,
                created_at=test_day.strftime("%Y-%m-%d"),
            )
            store.add(event, key)
            events.append(event)

    return decisions, events
