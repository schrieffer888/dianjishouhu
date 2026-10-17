"""Pyodide 桥接层：把算法核心暴露给浏览器 JS 调用。

JS 通过 handle_json(action, payload_json) 传 JSON 字符串进来，
得到 JSON 字符串返回，避免 PyProxy / 类型转换问题。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from configs import defaults as C
from algorithms.history import is_stable
from algorithms.pipeline import detect_anomalies, run_pipeline

_last = None  # 最近一次 PipelineResult（每个浏览器标签页各自独立）


def _fmt_hhmm(h: float) -> str:
    hh = int(h)
    mm = int(round((h - hh) * 60))
    return f"{hh:02d}:{mm:02d}"


def _serialize(p) -> dict:
    """把 PipelineResult 序列化为可 JSON 的字典（与 app/main.py 同款）。"""
    windows = {}
    for app_name, ws in p.windows.items():
        windows[app_name] = [
            {"span_min": round(w.span_min, 2), "span_max": round(w.span_max, 2),
             "appearance_ratio": round(w.appearance_ratio, 3),
             "valid_days": w.valid_days, "count": w.count, "stable": is_stable(w)}
            for w in ws
        ]

    acts = [
        {"appliance": a["appliance"], "start": str(a["start"]), "end": str(a["end"]),
         "matched": bool(a["matched"]), "is_auto": bool(a["is_auto"])}
        for _, a in p.test_activities.iterrows()
    ]

    decisions = [
        {"appliance": d.appliance, "outcome": d.outcome, "reason": d.reason,
         "span": f"{d.window.span_min:.2f}-{d.window.span_max:.2f}"}
        for d in p.decisions
    ]

    events = [
        {"event_id": e.event_id, "household_id": e.household_id,
         "appliance": e.appliance, "kind": e.kind, "reason": e.reason,
         "evidence_window": e.evidence_window, "status": e.status,
         "created_at": e.created_at}
        for e in p.events
    ]

    ml_anomalies = [
        {"appliance": a.appliance, "kind": a.kind, "hour": a.hour,
         "score": round(a.score, 2) if a.score != float("inf") else None,
         "reason": a.reason}
        for a in p.ml_anomalies
    ]

    power_comparison = []
    observed = p.run.observed
    test_day = pd.Timestamp(observed["day"].max())
    test_observed = observed[(observed["day"] == test_day) &
                             (observed["quality"] == "ok") &
                             observed["power_w"].notna()]
    for app_name in ("kettle", "microwave", "tv"):
        app_acts = (p.test_activities[p.test_activities["appliance"] == app_name]
                    if not p.test_activities.empty else p.test_activities)
        samples = []
        for _, activity in app_acts.iterrows():
            start, end = pd.Timestamp(activity["start"]), pd.Timestamp(activity["end"])
            readings = test_observed[(test_observed["timestamp"] >= start) &
                                     (test_observed["timestamp"] <= end)]["power_w"]
            if not readings.empty:
                samples.extend(readings.astype(float).tolist())
        day_w = round(float(np.median(samples)), 1) if samples else None
        regular_w = p.templates.get(app_name)
        power_comparison.append({
            "appliance": app_name,
            "regular_w": round(float(regular_w), 1) if regular_w is not None else None,
            "day_w": day_w,
            "activity_count": int(len(app_acts)),
        })

    return {
        "scenario": p.run.meta.scenario,
        "description": p.run.meta.description,
        "seed": p.run.seed,
        "history_days": p.run.n_history_days,
        "away": p.run.meta.away,
        "templates": {k: round(float(v), 1) for k, v in p.templates.items()},
        "power_comparison": power_comparison,
        "windows": windows,
        "test_activities": acts,
        "decisions": decisions,
        "events": events,
        "ml_anomalies": ml_anomalies,
    }


def _handle(action: str, payload: dict):
    global _last

    if action == "run":
        scenario = payload.get("scenario", "S1")
        seed = int(payload.get("seed", 42))
        history_days = int(payload.get("history_days", 21))
        away = payload.get("away")
        p = run_pipeline(scenario, seed=seed, history_days=history_days,
                         away_override=away)
        _last = p
        result = _serialize(p)
        result["notify_channel"] = "mock"
        result["notifications_sent"] = len(p.events)
        return result

    if action == "power":
        p = _last
        if p is None:
            return {"error": "请先运行仿真"}
        resample_min = int(payload.get("resample_min", 1))
        r = p.run
        test_day = pd.Timestamp(r.observed["day"].max())
        test = r.observed[r.observed["day"] == test_day]
        df = test.set_index("timestamp")
        n = int(60 / r.sampling_period) * resample_min
        out = []
        for _, grp in df.groupby(np.arange(len(df)) // n):
            missing = int((grp["quality"] == "missing").sum())
            out.append({
                "t": str(grp.index[0]),
                "power": round(float(grp["power_w"].mean()), 1) if grp["power_w"].notna().any() else None,
                "missing": missing,
            })
        return out

    if action == "detect":
        p = _last
        if p is None:
            return {"error": "请先运行仿真"}

        test_day = pd.Timestamp(C.TEST_DAY_DATE)
        zh = {"kettle": "电水壶", "microwave": "微波炉", "tv": "电视"}
        rows = []
        for app in ("kettle", "microwave", "tv"):
            for t in payload.get(app, []):
                try:
                    hh, mm = t.strip().split(":")
                    start = test_day + pd.Timedelta(hours=int(hh), minutes=int(mm))
                except (ValueError, AttributeError):
                    return {"error": f"时间格式错误：{t}（应为 HH:MM，如 07:30）"}
                rows.append({"appliance": app, "start": start, "end": start,
                             "matched": True, "is_auto": False, "day": test_day})
        test_activities = pd.DataFrame(rows)

        rule, ml = detect_anomalies(p.history_activities, test_activities,
                                    p.run.n_history_days)

        rule_out = []
        for d in rule:
            span = f"{_fmt_hhmm(d.span_min)}-{_fmt_hhmm(d.span_max)}"
            if d.kind == "missing":
                reason = f"{zh.get(d.appliance, d.appliance)} 常见 {span}，今天没有出现。"
            else:
                delay_min = int(round((d.delay_hours or 0.0) * 60))
                reason = f"{zh.get(d.appliance, d.appliance)} 常见 {span}，今天延迟约 {delay_min} 分钟。"
            rule_out.append({"appliance": d.appliance, "kind": d.kind,
                             "normal": span, "reason": reason})

        ml_out = []
        for a in ml:
            if a.kind == "missing":
                reason = f"{zh.get(a.appliance, a.appliance)} 常见 {_fmt_hhmm(a.hour)} 附近，今天没有出现。"
            else:
                reason = (f"{zh.get(a.appliance, a.appliance)} 今天 {_fmt_hhmm(a.hour)} 才出现，"
                          f"偏离历史分布（异常分数 {a.score:.1f}）。")
            ml_out.append({"appliance": a.appliance, "kind": a.kind,
                           "hour": round(a.hour, 2) if a.hour is not None else None,
                           "score": round(a.score, 2) if a.score != float("inf") else None,
                           "reason": reason})

        return {"rule": rule_out, "ml": ml_out}

    return {"error": f"未知操作：{action}"}


def handle_json(action: str, payload_json: str) -> str:
    """JS 入口：接收 (action, payload_json)，返回 JSON 字符串。"""
    try:
        payload = json.loads(payload_json) if payload_json else {}
        result = _handle(action, payload)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": str(e)}, ensure_ascii=False)
