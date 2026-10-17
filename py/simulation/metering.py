"""计量模型：采样、噪声、丢包、中断。零功率与缺失值分开。"""
from __future__ import annotations

import numpy as np

QUALITY_OK = "ok"
QUALITY_MISSING = "missing"


def meter(truth_power: np.ndarray, rng: np.random.Generator,
          noise_sigma: float, dropout_prob: float,
          interruptions: list[tuple[int, int]] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """对真值功率做计量，返回 (观测功率, 质量标签)。

    - 观测功率 = 真值 + 高斯噪声，并做非负截断（物理合理）。
    - 丢包与中断的样本：power = NaN，quality = "missing"（缺失，不是零）。
    - 其余样本 quality = "ok"，即使功率为 0 也保持 0（零与缺失分开）。
    """
    n = len(truth_power)
    obs = np.maximum(truth_power + rng.normal(0.0, noise_sigma, n), 0.0)
    quality = np.full(n, QUALITY_OK, dtype=object)

    drop = rng.random(n) < dropout_prob
    if interruptions:
        for a, b in interruptions:
            a = max(0, min(a, n))
            b = max(0, min(b, n))
            drop[a:b] = True

    obs[drop] = np.nan
    quality[drop] = QUALITY_MISSING
    return obs, quality
