"""负荷模型：电器规格与功率曲线渲染。

电器按 kind 分为三类：
- event:  人为触发（电水壶/电视/微波炉），由日程模型生成活动事件。
- cyclic: 自动周期（冰箱），on/off 循环，不计入主动活动证据。
- base:   恒定背景（路由器/待机），不计入主动活动证据。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ApplianceSpec:
    name: str
    kind: str                 # "event" | "cyclic" | "base"
    is_auto: bool             # 自动负荷不计入主动活动证据
    power_w: float = 0.0      # event: 单次活动功率；cyclic: on 功率；base: 恒定功率
    on_dur: float = 0.0       # cyclic: 开时长（秒）
    off_dur: float = 0.0      # cyclic: 关时长（秒）


APPLIANCES: dict[str, ApplianceSpec] = {
    "kettle": ApplianceSpec("kettle", "event", False, power_w=2000.0),
    "microwave": ApplianceSpec("microwave", "event", False, power_w=1200.0),
    "tv": ApplianceSpec("tv", "event", False, power_w=250.0),
    "refrigerator": ApplianceSpec("refrigerator", "cyclic", True,
                                  power_w=100.0, on_dur=600.0, off_dur=1800.0),
    "base": ApplianceSpec("base", "base", True, power_w=40.0),
}


def render_event(spec: ApplianceSpec, duration: float, sampling: float) -> np.ndarray:
    """单个活动周期的功率曲线（恒定功率）。"""
    n = max(1, int(round(duration / sampling)))
    return np.full(n, spec.power_w, dtype=float)


def render_cyclic(spec: ApplianceSpec, n_samples: int, sampling: float,
                  phase: float = 0.0) -> np.ndarray:
    """周期负荷（冰箱）的功率曲线，on/off 循环（含相位偏移）。"""
    t = np.arange(n_samples) * sampling + phase
    cycle = spec.on_dur + spec.off_dur
    ph = t % cycle
    return np.where(ph < spec.on_dur, spec.power_w, 0.0)


def render_base(spec: ApplianceSpec, n_samples: int) -> np.ndarray:
    """恒定背景负荷。"""
    return np.full(n_samples, spec.power_w, dtype=float)
