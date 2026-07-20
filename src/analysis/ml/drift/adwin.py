from __future__ import annotations

import math
from collections import deque


class ADWINDetector:
    def __init__(self, delta: float = 0.05) -> None:
        self.delta = delta
        self._window: deque[float] = deque()

    def add_element(self, value: float) -> bool:
        self._window.append(value)
        return self._detect()

    def get_width(self) -> int:
        return len(self._window)

    def get_mean(self) -> float:
        if not self._window:
            return 0.0
        return sum(self._window) / len(self._window)

    def reset(self) -> None:
        self._window.clear()

    def detect_batch(self, values: list[float]) -> list[int]:
        indices: list[int] = []
        for i, v in enumerate(values):
            if self.add_element(v):
                indices.append(i)
        return indices

    def _detect(self) -> bool:
        n = len(self._window)
        if n < 5:
            return False

        for cut in range(1, n):
            left = list(self._window)[:cut]
            right = list(self._window)[cut:]
            n0 = len(left)
            n1 = len(right)
            if n0 == 0 or n1 == 0:
                continue
            mean0 = sum(left) / n0
            mean1 = sum(right) / n1
            diff = abs(mean0 - mean1)

            m = 1.0 / (1.0 / n0 + 1.0 / n1)
            eps = math.sqrt(1.0 / (2.0 * m) * math.log(4.0 * n / self.delta))

            if diff > eps:
                self._window = deque(right)
                return True

        return False
