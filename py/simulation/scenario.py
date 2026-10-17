"""场景库 S0—S7。

场景只修改输入（日程或信号），不直接创建预定告警。
返回的 meta 含真值标签，仅用于评估，识别模块不能读取。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .schedule_model import ActivityEvent


@dataclass
class ScenarioMeta:
    scenario: str
    description: str = ""
    away: bool = False                    # 已知外出设置
    interruption: tuple[float, float] | None = None  # 数据中断 (起, 止) 小时
    notify_failure: bool = False          # 通知失败注入
    removed: list[str] = field(default_factory=list)   # 被删除活动描述
    moved: list[dict] = field(default_factory=list)    # 被移动活动描述
    added_unknown: list[str] = field(default_factory=list)  # 新增未知负荷描述


SCENARIOS: dict[str, dict] = {
    "S0": {"description": "正常波动：活动在通常时段内，不应产生预设行为异常"},
    "S1": {"description": "习惯活动缺失：删除一次目标活动，保留背景负荷"},
    "S2": {"description": "延迟/长间隔：把活动移动到通常窗口之外"},
    "S3": {"description": "已知外出：缺少活动同时设置外出，抑制行为提醒"},
    "S4": {"description": "数据中断：区段标为缺失而非零，暂缓行为判断"},
    "S5": {"description": "仅自动负荷：保留背景、删除主动活动"},
    "S6": {"description": "相似/重叠负荷：叠加相近功率负荷，记录未知"},
    "S7": {"description": "通知失败：注入网络/渠道失败响应，记录重试与失败"},
}


def _describe_event(ev: ActivityEvent) -> str:
    return f"{ev.appliance}@{ev.start.strftime('%H:%M')}"


def apply_scenario(scenario_id: str, events: list[ActivityEvent],
                   rng: np.random.Generator) -> tuple[list[ActivityEvent], ScenarioMeta]:
    """对测试日活动应用场景修改，返回 (修改后活动, meta)。"""
    events = list(events)
    meta = ScenarioMeta(scenario_id, description=SCENARIOS[scenario_id]["description"])

    # 习惯活动：电水壶早晨使用（通常 07:00-09:00）
    morning_kettle = next((e for e in events
                           if e.appliance == "kettle" and 7.0 <= e.start.hour + e.start.minute / 60 < 10.0), None)
    # 主动活动（非自动）
    active = [e for e in events if not e.is_auto]

    if scenario_id == "S0":
        pass  # 正常波动，日程采样已提供

    elif scenario_id == "S1":
        if morning_kettle:
            events.remove(morning_kettle)
            meta.removed.append(_describe_event(morning_kettle))

    elif scenario_id == "S2":
        if morning_kettle:
            events.remove(morning_kettle)
            new_start = morning_kettle.start.replace(hour=14, minute=0)
            new_end = new_start + (morning_kettle.end - morning_kettle.start)
            moved = ActivityEvent(morning_kettle.appliance, new_start, new_end, False)
            events.append(moved)
            meta.moved.append({"from": _describe_event(morning_kettle),
                               "to": _describe_event(moved)})

    elif scenario_id == "S3":
        if morning_kettle:
            events.remove(morning_kettle)
            meta.removed.append(_describe_event(morning_kettle))
        meta.away = True

    elif scenario_id == "S4":
        meta.interruption = (7.0, 10.0)

    elif scenario_id == "S5":
        for e in active:
            events.remove(e)
            meta.removed.append(_describe_event(e))

    elif scenario_id == "S6":
        # 叠加一个与已知模板不匹配的未知负荷（错开 3 分钟开启，与电水壶时段重叠）
        if morning_kettle:
            unknown = ActivityEvent("unknown_heater",
                                    morning_kettle.start + pd.Timedelta(minutes=3),
                                    morning_kettle.start + pd.Timedelta(minutes=12), False)
            events.append(unknown)
            meta.added_unknown.append(_describe_event(unknown))
        events.sort(key=lambda e: e.start)

    elif scenario_id == "S7":
        if morning_kettle:
            events.remove(morning_kettle)
            meta.removed.append(_describe_event(morning_kettle))
        meta.notify_failure = True

    else:
        raise ValueError(f"未知场景: {scenario_id}")

    events.sort(key=lambda e: e.start)
    return events, meta
