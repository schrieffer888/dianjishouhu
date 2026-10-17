"""日程模型：生成各电器的每日使用活动（含出现概率与每日波动）。

历史日使用概率采样，产生真实的"有时出现、有时不出现"；
测试日使用确定性的"典型日程"，保证场景修改有可验证的真值。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .load_model import APPLIANCES


@dataclass(frozen=True)
class WindowSpec:
    start_hour: float
    end_hour: float
    p_use: float              # 该窗口出现一次活动的概率
    dur_min: float            # 活动时长下限（秒）
    dur_max: float            # 活动时长上限（秒）


@dataclass(frozen=True)
class ActivityEvent:
    appliance: str
    start: pd.Timestamp
    end: pd.Timestamp
    is_auto: bool


# 各目标电器在一天内的"通常使用时段"
SCHEDULE: dict[str, list[WindowSpec]] = {
    "kettle": [
        WindowSpec(7.0, 9.0, 0.90, 180, 360),
        WindowSpec(18.0, 20.0, 0.80, 180, 360),
    ],
    "microwave": [
        WindowSpec(12.0, 13.0, 0.85, 120, 300),
        WindowSpec(18.0, 19.5, 0.75, 120, 300),
    ],
    "tv": [
        WindowSpec(19.0, 22.5, 0.85, 3600, 10800),
    ],
}


def _sample_event(appliance: str, day: pd.Timestamp, w: WindowSpec,
                  rng: np.random.Generator) -> ActivityEvent | None:
    if rng.random() > w.p_use:
        return None
    start_hour = rng.uniform(w.start_hour, w.end_hour)
    duration = rng.uniform(w.dur_min, w.dur_max)
    start = day + pd.Timedelta(hours=float(start_hour))
    end = start + pd.Timedelta(seconds=float(duration))
    return ActivityEvent(appliance, start, end, is_auto=False)


def generate_day_events(day: pd.Timestamp, rng: np.random.Generator) -> list[ActivityEvent]:
    """生成某一天各目标电器的人为活动事件（概率采样，用于历史日）。"""
    events: list[ActivityEvent] = []
    for appliance, windows in SCHEDULE.items():
        for w in windows:
            ev = _sample_event(appliance, day, w, rng)
            if ev is not None:
                events.append(ev)
    events.sort(key=lambda e: e.start)
    return events


def generate_canonical_day_events(day: pd.Timestamp) -> list[ActivityEvent]:
    """生成测试日的确定性"典型日程"（活动保证出现在通常时段）。"""
    def at(hour: float) -> pd.Timestamp:
        return day + pd.Timedelta(hours=hour)

    events = [
        ActivityEvent("kettle", at(7.5), at(7.5) + pd.Timedelta(minutes=5), False),
        ActivityEvent("microwave", at(12.5), at(12.5) + pd.Timedelta(minutes=3), False),
        ActivityEvent("microwave", at(18.5), at(18.5) + pd.Timedelta(minutes=3), False),
        ActivityEvent("kettle", at(19.0), at(19.0) + pd.Timedelta(minutes=5), False),
        ActivityEvent("tv", at(20.0), at(22.0), False),
    ]
    return events
