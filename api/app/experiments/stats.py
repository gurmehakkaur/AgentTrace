"""The two statistics an experiment reports. Hand-written (no scipy): small N, exact answers.

Small N is about direction and effect size, not proof. Callers label results "directional".
"""

from math import comb, sqrt


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for the 2x2 table [[a, b], [c, d]].

    For an experiment: [[treatment_pass, treatment_fail], [control_pass, control_fail]].
    Sums the probability of every table with the same margins that is no more likely than the
    observed one (the standard definition; matches scipy's fisher_exact).
    """
    row1, row2, col1 = a + b, c + d, a + c
    total = row1 + row2

    def prob(x: int) -> float:  # P(top-left cell == x) under the hypergeometric null
        return comb(col1, x) * comb(total - col1, row1 - x) / comb(total, row1)

    observed = prob(a)
    lo, hi = max(0, row1 - (total - col1)), min(row1, col1)
    # 1e-9 tolerance: floating point must not separate tables that are exactly as likely.
    p = sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= observed * (1 + 1e-9))
    return min(1.0, p)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for k successes in n trials (95% by default); None if n == 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)
