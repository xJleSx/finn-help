from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class _Bucket:
    size: int = 0
    total: float = 0.0


class ADWINDetector:
    def __init__(self, delta: float = 0.05) -> None:
        self.delta = delta
        self._buckets: list[_Bucket] = []
        self._total: float = 0.0
        self._width: int = 0

    def add_element(self, value: float) -> bool:
        self._buckets.insert(0, _Bucket(size=1, total=value))
        self._total += value
        self._width += 1
        self._merge_buckets()
        return self._detect()

    def get_width(self) -> int:
        return self._width

    def get_mean(self) -> float:
        if self._width == 0:
            return 0.0
        return self._total / self._width

    def reset(self) -> None:
        self._buckets.clear()
        self._total = 0.0
        self._width = 0

    def detect_batch(self, values: list[float]) -> list[int]:
        indices: list[int] = []
        for i, v in enumerate(values):
            if self.add_element(v):
                indices.append(i)
        return indices

    def _merge_buckets(self) -> None:
        i = 0
        while i < len(self._buckets) - 1:
            if self._buckets[i].size == self._buckets[i + 1].size:
                sz = self._buckets[i].size + self._buckets[i + 1].size
                tot = self._buckets[i].total + self._buckets[i + 1].total
                self._buckets[i] = _Bucket(size=sz, total=tot)
                del self._buckets[i + 1]
            i += 1

    def _detect(self) -> bool:
        if self._width < 5:
            return False

        left_total = 0.0
        left_width = 0

        for i in range(len(self._buckets) - 1):
            left_total += self._buckets[i].total
            left_width += self._buckets[i].size
            right_total = self._total - left_total
            right_width = self._width - left_width

            mean0 = left_total / left_width
            mean1 = right_total / right_width
            diff = abs(mean0 - mean1)

            m = left_width * right_width / (left_width + right_width)
            delta_prime = self.delta / math.log(max(self._width, math.e))
            eps = math.sqrt(2.0 / m * math.log(2.0 / delta_prime))

            if diff > eps:
                self._width = right_width
                self._total = right_total
                self._buckets = self._buckets[i + 1:]
                return True

        return False
