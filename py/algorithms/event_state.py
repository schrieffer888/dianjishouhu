"""关怀事件状态机与去重。

状态：待确认 → 已确认平安；或 待确认 → 待跟进 → 已接单 → 已完成。
同一事件（同一电器 + 窗口 + 类型 + 日期）不重复建单。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

STATUS_PENDING = "pending"       # 待确认
STATUS_CONFIRMED = "confirmed"   # 已确认平安
STATUS_FOLLOWUP = "followup"     # 待跟进
STATUS_ACCEPTED = "accepted"     # 已接单
STATUS_DONE = "done"             # 已完成

_TRANSITIONS = {
    STATUS_PENDING: {STATUS_CONFIRMED, STATUS_FOLLOWUP},
    STATUS_FOLLOWUP: {STATUS_ACCEPTED},
    STATUS_ACCEPTED: {STATUS_DONE},
}


@dataclass
class CareEvent:
    event_id: str
    household_id: str
    appliance: str
    kind: str                 # "missing" | "delay"
    reason: str               # 人类可读的提醒说明
    evidence_window: str      # 证据窗口
    status: str = STATUS_PENDING
    created_at: str = ""
    history: list[tuple] = field(default_factory=list)


class EventStore:
    """内存事件存储：去重 + 状态流转。"""

    def __init__(self) -> None:
        self._by_id: dict[str, CareEvent] = {}
        self._keys: set[str] = set()
        self._seq = 0

    @staticmethod
    def dedup_key(appliance: str, kind: str, span_min: float, span_max: float, day: str) -> str:
        return f"{appliance}|{kind}|{span_min:.2f}-{span_max:.2f}|{day}"

    def exists(self, key: str) -> bool:
        return key in self._keys

    def add(self, event: CareEvent, key: str) -> CareEvent:
        self._keys.add(key)
        self._by_id[event.event_id] = event
        return event

    def next_id(self) -> str:
        self._seq += 1
        return f"EV-{self._seq:04d}"

    def get(self, event_id: str) -> CareEvent | None:
        return self._by_id.get(event_id)

    def all(self) -> list[CareEvent]:
        return list(self._by_id.values())

    def transition(self, event_id: str, new_status: str, operator: str = "system") -> bool:
        ev = self._by_id.get(event_id)
        if ev is None:
            return False
        allowed = _TRANSITIONS.get(ev.status, set())
        if new_status not in allowed:
            return False
        ev.history.append((ev.status, new_status, operator, datetime.now().isoformat()))
        ev.status = new_status
        return True
