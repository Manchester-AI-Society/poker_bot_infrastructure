"""Small statistics helpers (no numpy needed)."""

from __future__ import annotations

import math
from typing import Optional, Sequence, Tuple

# Two-sided 95% Student-t critical values by degrees of freedom.
_T95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
}


def t95(degrees_of_freedom: int) -> float:
    """95% two-sided critical value; normal approximation from df 30."""
    if degrees_of_freedom < 1:
        return float("inf")
    return _T95.get(degrees_of_freedom, 1.96)


def mean_and_se(values: Sequence[float]) -> Tuple[Optional[float], float]:
    """Returns (mean, standard error of the mean).

    With fewer than two values the standard error is infinite: one
    observation says nothing about the spread.
    """
    count = len(values)
    if count == 0:
        return None, float("inf")
    mean = sum(values) / count
    if count < 2:
        return mean, float("inf")
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    return mean, math.sqrt(variance / count)


def ci95(standard_error: float, samples: int) -> float:
    """Half-width of the 95% confidence interval for a mean."""
    return t95(samples - 1) * standard_error
