"""机器学习异常检测：对每个电器拟合"使用时刻"的高斯混合模型（GMM）。

与 history.py 的规则窗口并列，作为学习型对照：
- 训练（fit）：只用历史正常日的活动开始时刻，用 EM 迭代拟合 GMM 参数（权重/均值/方差），
  并用 BIC 自动选择分量数 k。不使用场景标签、不使用未来信息。
- 推理（evaluate）：测试日每个活动按 -log 概率密度打"异常分数"；
  某个历史"模式"（高斯分量）附近无当日活动 → 判"习惯活动缺失"；
  活动落在低密度区（分数超训练阈值）→ 判"活动延迟"。

判定口径与 classify_appliance 对齐，便于对照：每个分量独立判定 filled/stray/missing。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from configs import defaults as C


@dataclass
class AnomalyResult:
    appliance: str
    kind: str            # "missing" | "delay"
    hour: float | None   # missing：缺失模式的中心时刻；delay：异常活动时刻
    score: float         # -log 密度（缺失时为 inf）
    reason: str


def _hour(t: pd.Series) -> np.ndarray:
    return (t.dt.hour + t.dt.minute / 60.0 + t.dt.second / 3600.0).to_numpy()


class TimeGMM:
    """一维高斯混合模型，EM 拟合。对某电器的开始时刻分布建模。"""

    def __init__(self, k: int = 1, max_iter: int = 200, tol: float = 1e-5,
                 seed: int = 0) -> None:
        self.k = k
        self.max_iter = max_iter
        self.tol = tol
        self.seed = seed
        self.weights: np.ndarray | None = None
        self.means: np.ndarray | None = None
        self.stds: np.ndarray | None = None

    # -- 内部：对数密度与责任度 --
    def _log_components(self, x: np.ndarray) -> np.ndarray:
        """返回 (n, k) 的每分量对数密度。"""
        x = np.asarray(x, dtype=float)[:, None]
        z = (x - self.means) / self.stds
        return -0.5 * z * z - np.log(self.stds) - 0.5 * np.log(2 * np.pi)

    def _responsibilities(self, x: np.ndarray) -> np.ndarray:
        logp = self._log_components(x) + np.log(self.weights)
        logp -= logp.max(axis=1, keepdims=True)
        p = np.exp(logp)
        p /= p.sum(axis=1, keepdims=True)
        return p

    def log_density(self, x) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        logp = self._log_components(x) + np.log(self.weights)
        return np.logaddexp.reduce(logp, axis=1)

    def score(self, x) -> np.ndarray:
        """异常分数 = -log 概率密度（越大越异常）。"""
        s = -self.log_density(x)
        return float(s) if np.ndim(s) == 0 else s

    def fit(self, x) -> "TimeGMM":
        x = np.asarray(x, dtype=float)
        n = len(x)
        rng = np.random.default_rng(self.seed)
        self.weights = np.full(self.k, 1.0 / self.k)
        if self.k == 1:
            self.means = np.array([x.mean()])
        else:
            q = np.linspace(0, 100, self.k + 2)[1:-1]
            self.means = np.asarray([np.percentile(x, p) for p in q], dtype=float)
        self.stds = np.full(self.k, max(x.std(), 0.2))

        for _ in range(self.max_iter):
            resp = self._responsibilities(x)
            nk = resp.sum(axis=0) + 1e-12
            new_means = (resp * x[:, None]).sum(axis=0) / nk
            diff = (x[:, None] - new_means) ** 2
            new_stds = np.clip(np.sqrt((resp * diff).sum(axis=0) / nk), 0.1, None)
            new_weights = nk / n
            if np.max(np.abs(new_means - self.means)) < self.tol:
                self.means, self.stds, self.weights = new_means, new_stds, new_weights
                break
            self.means, self.stds, self.weights = new_means, new_stds, new_weights
        return self


def _fit_select_k(x: np.ndarray, k_max: int = 4, seed: int = 0,
                  merge_gap: float = 2.0) -> TimeGMM:
    """用 BIC 在 1..k_max 间选择分量数，再合并相距 < merge_gap 的相邻分量。

    宽而平坦的"习惯窗口"（如 7:00-9:00 均匀出现）会被 GMM 过拆成多个窄高斯，
    合并步骤把间距小于 gap 的分量并回一个习惯，与规则的单链聚类口径一致。
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    k_max = max(1, min(k_max, n // 4))
    best: TimeGMM | None = None
    best_bic = np.inf
    for k in range(1, k_max + 1):
        m = TimeGMM(k=k, seed=seed).fit(x)
        ll = float(m.log_density(x).sum())
        n_params = 3 * k - 1  # 权重和为 1，减 1 自由度
        bic = -2 * ll + n_params * np.log(max(n, 2))
        if bic < best_bic:
            best_bic, best = bic, m
    return _merge_close(best, merge_gap)


def _merge_close(model: TimeGMM, gap: float) -> TimeGMM:
    """按均值升序合并相距 ≤ gap 的相邻高斯分量，返回合并后的新模型。"""
    order = np.argsort(model.means)
    m = model.means[order].copy()
    s = model.stds[order].copy()
    w = model.weights[order].copy()

    out_m, out_s, out_w = [], [], []
    i, n = 0, len(m)
    while i < n:
        j = i
        wsum = w[i]
        msum = m[i] * w[i]
        while j + 1 < n and m[j + 1] - m[i] <= gap:
            j += 1
            wsum += w[j]
            msum += m[j] * w[j]
        mean = msum / wsum
        var = sum(w[k] * (s[k] ** 2 + (m[k] - mean) ** 2) for k in range(i, j + 1)) / wsum
        out_m.append(mean)
        out_s.append(float(np.sqrt(var)))
        out_w.append(wsum)
        i = j + 1

    merged = TimeGMM(k=len(out_m), seed=model.seed)
    merged.weights = np.asarray(out_w) / sum(out_w)
    merged.means = np.asarray(out_m)
    merged.stds = np.asarray(out_s)
    return merged


class MLAnomalyDetector:
    """对每个稳定出现的目标电器拟合 GMM，并判定测试日缺失/延迟。"""

    def __init__(self, min_days: int = C.MIN_HISTORY_DAYS,
                 min_ratio: float = C.MIN_APPEARANCE_RATIO,
                 tolerance_min: float = C.TOLERANCE_MINUTES) -> None:
        self.min_days = min_days
        self.min_ratio = min_ratio
        self.tol_h = tolerance_min / 60.0
        self.models: dict[str, TimeGMM] = {}
        self.thresholds: dict[str, float] = {}
        self.appearance: dict[str, float] = {}

    def fit(self, history_activities: pd.DataFrame, valid_days: int) -> "MLAnomalyDetector":
        act = history_activities[history_activities["matched"] & ~history_activities["is_auto"]]
        if act.empty:
            return self
        for app, grp in act.groupby("appliance"):
            days_present = grp["day"].nunique()
            ratio = days_present / valid_days if valid_days else 0.0
            if valid_days < self.min_days or ratio < self.min_ratio:
                continue  # 历史不足或出现比例不足，不建模（与 is_stable 对齐）
            hours = _hour(grp["start"])
            model = _fit_select_k(hours)
            self.models[app] = model
            self.appearance[app] = ratio
            # 阈值：训练样本的 95 分位异常分数，越界即"低密度"
            self.thresholds[app] = float(np.percentile(model.score(hours), 95))
        return self

    def evaluate(self, test_activities: pd.DataFrame) -> list[AnomalyResult]:
        results: list[AnomalyResult] = []
        for app, model in self.models.items():
            acts = test_activities[(test_activities["appliance"] == app) &
                                   (test_activities["matched"])]
            hours = sorted(_hour(acts["start"]).tolist())

            order = np.argsort(model.means)
            centers = model.means[order]
            radii = np.maximum(1.0, 2.0 * model.stds[order])

            for i, c in enumerate(centers):
                r = float(radii[i])
                filled = any(c - r <= h <= c + r + self.tol_h for h in hours)
                if filled:
                    continue
                next_lo = float(centers[i + 1] - radii[i + 1]) if i + 1 < len(centers) else 24.0
                stray = [h for h in hours if c + r + self.tol_h < h < next_lo]
                if stray:
                    h0 = min(stray)
                    results.append(AnomalyResult(
                        app, "delay", h0, float(model.score(np.array([h0]))[0]),
                        f"{app} 常见 {c:.1f} 时附近，今日 {h0:.1f} 时才出现（异常分数超阈值），偏离历史分布。"))
                else:
                    results.append(AnomalyResult(
                        app, "missing", float(c), float("inf"),
                        f"{app} 常见 {c:.1f} 时附近今日无活动（历史出现比例 {self.appearance[app]:.0%}），建议确认。"))
        return results
