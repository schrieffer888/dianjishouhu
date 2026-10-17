"""仿真时钟：区分数据时间、仿真时间与真实通知时间。"""
from __future__ import annotations

import time


class SimulationClock:
    """业务时钟。

    - data_time: 场景内数据时间（随回放推进）。
    - sim_time:  仿真时间（== data_time，可被加速）。
    - real_time: 墙钟时间（真实通知时间，不随加速而加速）。

    约束：加速倍率只加速数据/仿真时间，不加速手机发信频率。
    """

    def __init__(self) -> None:
        self._speed = 1.0
        self._paused = False
        self._base_real = time.time()
        self._base_data = 0.0          # data_time 起点（秒）
        self._paused_data = 0.0

    # -- 时间 --
    @property
    def speed(self) -> float:
        return self._speed

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def data_time(self) -> float:
        if self._paused:
            return self._paused_data
        return self._base_data + (time.time() - self._base_real) * self._speed

    @property
    def sim_time(self) -> float:
        return self.data_time

    @property
    def real_time(self) -> float:
        return time.time()

    # -- 控制 --
    def set_speed(self, speed: float) -> None:
        if speed <= 0:
            raise ValueError("speed 必须为正")
        if self._paused:
            self._speed = speed
            return
        self._base_data = self.data_time
        self._base_real = time.time()
        self._speed = speed

    def pause(self) -> None:
        if self._paused:
            return
        self._paused_data = self.data_time
        self._paused = True

    def resume(self) -> None:
        if not self._paused:
            return
        self._base_data = self._paused_data
        self._base_real = time.time()
        self._paused = False

    def reset(self) -> None:
        self._base_data = 0.0
        self._base_real = time.time()
        self._paused = False
        self._paused_data = 0.0
