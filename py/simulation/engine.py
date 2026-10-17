"""仿真引擎：给定场景与种子，生成聚合功率观测与真值。

流程：历史日（概率日程）+ 测试日（典型日程）→ 场景修改 →
负荷渲染（活动 + 冰箱周期 + 背景）→ 求和得真值功率 → 计量得观测。

真值（activities / truth_power）与观测（observed）分开存放，
识别模块只能读 observed。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from configs import defaults as C
from .load_model import APPLIANCES, render_base, render_cyclic, render_event
from .metering import meter
from .schedule_model import (
    ActivityEvent,
    generate_canonical_day_events,
    generate_day_events,
)
from .scenario import ScenarioMeta, apply_scenario


@dataclass
class RunResult:
    observed: pd.DataFrame          # household_id, timestamp, power_w, source, quality, day
    truth_activities: pd.DataFrame  # appliance, start, end, power_w, is_auto, day
    truth_power: np.ndarray         # 每样本真值功率（计量前）
    meta: ScenarioMeta
    start_date: pd.Timestamp
    n_history_days: int
    sampling_period: float
    seed: int

    @property
    def timestamps(self) -> pd.DatetimeIndex:
        return pd.date_range(self.start_date, periods=len(self.truth_power),
                             freq=f"{int(self.sampling_period)}s")

    @property
    def samples_per_day(self) -> int:
        return int(C.SECONDS_PER_DAY // self.sampling_period)


def _auto_events(start_date: pd.Timestamp, n_samples: int,
                 sampling: float, phase: float = 0.0) -> list[ActivityEvent]:
    """生成冰箱周期开关的自动事件（仅用于真值/训练标签，不参与活动证据）。"""
    spec = APPLIANCES["refrigerator"]
    cycle = spec.on_dur + spec.off_dur
    total = n_samples * sampling
    events: list[ActivityEvent] = []
    t = -phase
    while t < total:
        on_start = max(t, 0.0)
        on_end = t + spec.on_dur
        if on_end > 0:
            events.append(ActivityEvent(
                "refrigerator",
                start_date + pd.Timedelta(seconds=on_start),
                start_date + pd.Timedelta(seconds=on_end),
                is_auto=True,
            ))
        t += cycle
    return events


def _render_power(events: list[ActivityEvent], n_samples: int,
                  start_date: pd.Timestamp, sampling: float,
                  phase: float = 0.0) -> np.ndarray:
    """把活动事件 + 自动背景渲染为每样本功率。"""
    power = np.zeros(n_samples, dtype=float)
    # 背景 + 冰箱周期
    power += render_base(APPLIANCES["base"], n_samples)
    power += render_cyclic(APPLIANCES["refrigerator"], n_samples, sampling, phase)

    for ev in events:
        a = int((ev.start - start_date) / pd.Timedelta(seconds=sampling))
        b = int((ev.end - start_date) / pd.Timedelta(seconds=sampling))
        a = max(0, a)
        b = min(n_samples, b)
        if b <= a:
            continue
        spec = APPLIANCES.get(ev.appliance)
        if spec is None:
            # 未知负荷（如 S6 叠加的 unknown_heater），给一个与模板不匹配的功率
            power[a:b] += C.UNKNOWN_APPLIANCE_POWER_W
        else:
            power[a:b] += spec.power_w
    return power


def run_scenario(scenario_id: str, seed: int = C.DEFAULT_SEED,
                 history_days: int = C.DEFAULT_HISTORY_DAYS,
                 sampling_period: float = C.SAMPLING_PERIOD_SEC,
                 noise_sigma: float = C.NOISE_SIGMA_W,
                 dropout_prob: float = C.DROPOUT_PROB) -> RunResult:
    """运行一个场景，返回观测与真值。"""
    rng = np.random.default_rng(seed)
    test_day = pd.Timestamp(C.TEST_DAY_DATE)
    start_date = test_day - pd.Timedelta(days=history_days)
    total_days = history_days + 1
    n_samples = total_days * C.SAMPLES_PER_DAY

    # 历史日活动（概率采样）
    history_events: list[ActivityEvent] = []
    for i in range(history_days):
        d = start_date + pd.Timedelta(days=i)
        history_events.extend(generate_day_events(d, rng))

    # 测试日活动（确定性典型日程）+ 场景修改
    test_events = generate_canonical_day_events(test_day)
    test_events, meta = apply_scenario(scenario_id, test_events, rng)

    all_events = history_events + test_events
    phase = C.REFRIGERATOR_PHASE_SEC
    truth_power = _render_power(all_events, n_samples, start_date, sampling_period, phase)

    # 中断：只作用于测试日（转成样本区间）
    interruptions: list[tuple[int, int]] = []
    if meta.interruption is not None:
        a_h, b_h = meta.interruption
        a = int((test_day + pd.Timedelta(hours=a_h) - start_date)
                / pd.Timedelta(seconds=sampling_period))
        b = int((test_day + pd.Timedelta(hours=b_h) - start_date)
                / pd.Timedelta(seconds=sampling_period))
        interruptions.append((a, b))

    obs, quality = meter(truth_power, rng, noise_sigma, dropout_prob, interruptions)

    timestamps = pd.date_range(start_date, periods=n_samples,
                               freq=f"{int(sampling_period)}s")
    day_of = timestamps.normalize()

    observed = pd.DataFrame({
        "household_id": C.HOUSEHOLD_ID,
        "timestamp": timestamps,
        "power_w": obs,
        "source": C.SOURCE_SYNTHETIC,
        "quality": quality,
        "day": day_of,
    })

    auto_events = _auto_events(start_date, n_samples, sampling_period, phase)
    truth_rows = []
    for e in all_events + auto_events:
        truth_rows.append({
            "appliance": e.appliance,
            "start": e.start, "end": e.end,
            "power_w": APPLIANCES[e.appliance].power_w if e.appliance in APPLIANCES else C.UNKNOWN_APPLIANCE_POWER_W,
            "is_auto": e.is_auto, "day": e.start.normalize(),
        })
    truth_activities = pd.DataFrame(truth_rows)

    return RunResult(
        observed=observed,
        truth_activities=truth_activities,
        truth_power=truth_power,
        meta=meta,
        start_date=start_date,
        n_history_days=history_days,
        sampling_period=sampling_period,
        seed=seed,
    )
