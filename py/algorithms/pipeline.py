"""端到端管线：仿真 → 模板估计 → 历史学习 → 测试日在线识别 → 关怀判定。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from configs import defaults as C
from simulation.engine import RunResult, run_scenario
from .care import CareDecision, evaluate_care
from .deviation import Deviation, classify_appliance
from .event_state import CareEvent, EventStore
from .history import Window, learn_windows
from .ml_anomaly import AnomalyResult, MLAnomalyDetector
from .recognition import Recognizer, estimate_templates


@dataclass
class PipelineResult:
    run: RunResult
    templates: dict[str, float]
    history_activities: pd.DataFrame
    test_activities: pd.DataFrame
    windows: dict[str, list[Window]]
    decisions: list[CareDecision]
    events: list[CareEvent]
    store: EventStore
    ml_anomalies: list[AnomalyResult]


def _interruption_spans(observed: pd.DataFrame, test_day: pd.Timestamp,
                        sampling: float,
                        min_sec: float = C.MIN_INTERRUPTION_SEC) -> list[tuple[float, float]]:
    """从测试日观测质量推导数据中断区间（小时）。缺失≠零。

    仅把连续缺失超过 min_sec 的区段视为"数据中断"；单点丢包不算。
    """
    test = observed[observed["day"] == test_day]
    q = (test["quality"] == "missing").to_numpy()
    spans: list[tuple[int, int]] = []
    start = None
    for i, m in enumerate(q):
        if m and start is None:
            start = i
        elif not m and start is not None:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(q)))
    out: list[tuple[float, float]] = []
    for a, b in spans:
        if (b - a) * sampling >= min_sec:
            out.append((a * sampling / 3600.0, b * sampling / 3600.0))
    return out


def run_pipeline(scenario_id: str, seed: int = C.DEFAULT_SEED,
                 history_days: int = C.DEFAULT_HISTORY_DAYS,
                 away_override: bool | None = None) -> PipelineResult:
    """运行完整管线。识别只读观测总功率，模板仅用训练分表真值估计。

    away_override 可在不改变场景输入的情况下强制设置/取消外出，用于演示"外出设置"门控。
    """
    r = run_scenario(scenario_id, seed=seed, history_days=history_days)
    test_day = pd.Timestamp(C.TEST_DAY_DATE)

    hist_truth = r.truth_activities[r.truth_activities["day"] < test_day]
    templates = estimate_templates(hist_truth)
    auto = set(C.AUTO_APPLIANCES)

    rec = Recognizer(templates, auto, sampling=r.sampling_period)

    hist_obs = r.observed[r.observed["day"] < test_day]
    history_activities = rec.recognize(
        hist_obs["timestamp"], hist_obs["power_w"].to_numpy(),
        hist_obs["quality"].to_numpy())

    test_obs = r.observed[r.observed["day"] == test_day]
    test_activities = rec.recognize(
        test_obs["timestamp"], test_obs["power_w"].to_numpy(),
        test_obs["quality"].to_numpy())

    windows = learn_windows(history_activities, history_days)
    interruptions = _interruption_spans(r.observed, test_day, r.sampling_period)

    away = r.meta.away if away_override is None else away_override
    store = EventStore()
    decisions, events = evaluate_care(
        test_activities, windows, away, interruptions, test_day, store)

    detector = MLAnomalyDetector().fit(history_activities, history_days)
    ml_anomalies = detector.evaluate(test_activities)

    return PipelineResult(r, templates, history_activities, test_activities,
                          windows, decisions, events, store, ml_anomalies)


def detect_anomalies(history_activities: pd.DataFrame,
                     test_activities: pd.DataFrame,
                     history_days: int):
    """给定历史与测试日活动，返回 (规则偏离, 学习型异常)。供手动输入检测复用。

    只做"学习规律 + 判偏离"这一层，不含外出/中断门控（门控在外层 evaluate_care）。
    """
    windows = learn_windows(history_activities, history_days)
    rule: list[Deviation] = []
    for app, ws in windows.items():
        rule += classify_appliance(app, sorted(ws, key=lambda w: w.span_max),
                                   test_activities)
    ml = MLAnomalyDetector().fit(history_activities, history_days).evaluate(test_activities)
    return rule, ml
