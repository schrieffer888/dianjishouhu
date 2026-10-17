"""全局默认参数。所有可复现参数集中于此，实验与报告据此引用。

这些是初始设置，验证后冻结，不用测试集调参。
"""
from __future__ import annotations

# --- 采样 ---
SAMPLING_PERIOD_SEC = 6            # 1/6 Hz，每 6 秒一次（UK-DALE 子表采样周期）
SECONDS_PER_DAY = 86400
SAMPLES_PER_DAY = SECONDS_PER_DAY // SAMPLING_PERIOD_SEC  # 14400

# --- 家庭（虚构编号，不识别具体个人） ---
HOUSEHOLD_ID = "H01"
SOURCE_SYNTHETIC = "synthetic_scenario"

# --- 默认日程与种子 ---
DEFAULT_HISTORY_DAYS = 21          # 有效历史日
DEFAULT_SEED = 20261008
TEST_DAY_DATE = "2026-09-22"       # 测试日（历史为 09-01 至 09-21）

# --- 计量噪声 ---
NOISE_SIGMA_W = 5.0                # 高斯噪声标准差 (W)
DROPOUT_PROB = 0.005               # 单点丢包概率（缺失，非零）

# --- 历史学习门槛（初始设置，验证后冻结） ---
MIN_HISTORY_DAYS = 7               # 至少 7 个有效历史日
MIN_APPEARANCE_RATIO = 0.70        # 出现比例至少 70%

# --- 提醒容忍窗（初始设置） ---
TOLERANCE_MINUTES = 30             # 超过通常窗口后多久才提醒

# --- 目标电器与自动背景 ---
TARGET_APPLIANCES = ["kettle", "tv", "microwave"]
AUTO_APPLIANCES = ["refrigerator", "base"]

# --- 识别基线参数 ---
EDGE_MIN_W = 50.0                  # 功率变化检测阈值 (W)
TOL_REL = 0.20                     # 模板匹配相对容差
TOL_ABS_W = 50.0                   # 模板匹配绝对容差 (W)
MIN_ON_DURATION_SEC = 60.0         # 去抖：最短活动时长 (s)

# --- 未知负荷（S6 叠加） ---
UNKNOWN_APPLIANCE_POWER_W = 1500.0  # 与已知模板不匹配，落在识别间隙

# --- 冰箱周期相位偏移（避免与整点边界对齐导致边沿叠加） ---
REFRIGERATOR_PHASE_SEC = 137.0

# --- 数据中断：连续缺失超过此时长才算中断（单点丢包不算） ---
MIN_INTERRUPTION_SEC = 300.0
