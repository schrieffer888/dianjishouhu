"""功率变化检测：边沿检测（跨缺失间隔不计算跳变）。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Edge:
    index: int         # 跳变后的样本索引
    sign: int          # +1 开启，-1 关闭
    magnitude: float   # |ΔP|


def find_edges(indices: np.ndarray, power: np.ndarray, edge_min: float) -> list[Edge]:
    """在 ok 样本序列上检测功率跳变。

    仅比较相邻 ok 样本；跨缺失（索引间隔 > 1）不计算跳变，
    因此中断/丢包不会产生虚假的恢复边沿。
    """
    idx = np.asarray(indices, dtype=int)
    p = np.asarray(power, dtype=float)
    if len(idx) < 2:
        return []
    d = np.diff(p)
    adjacent = np.diff(idx) <= 1
    mask = (np.abs(d) > edge_min) & adjacent
    ks = np.flatnonzero(mask)
    return [Edge(int(idx[k + 1]), int(np.sign(d[k])), float(abs(d[k]))) for k in ks]
