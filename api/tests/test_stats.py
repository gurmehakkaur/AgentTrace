"""Phase 6: statistics against known values (the guide's 0/5 vs 4/5 example included)."""

import pytest

from app.experiments.stats import fisher_exact_two_sided, wilson


def test_fisher_zero_of_five_vs_four_of_five_is_about_0_048():
    # [[treat_pass, treat_fail], [ctrl_pass, ctrl_fail]]
    assert fisher_exact_two_sided(4, 1, 0, 5) == pytest.approx(0.0476, abs=5e-4)


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        ((5, 0, 0, 5), 0.0079365),  # 1/126 * 2
        ((3, 2, 3, 2), 1.0),  # no difference
        ((8, 0, 0, 8), 0.0001554),  # N=8 hero experiment, extreme split
        ((7, 1, 0, 8), 18 / 12870),  # 0/8 vs 7/8: 2 * 9/C(16,8)
        ((3, 0, 0, 3), 0.1),  # tiny N can never reach p < 0.05
    ],
)
def test_fisher_known_values(table, expected):
    assert fisher_exact_two_sided(*table) == pytest.approx(expected, rel=2e-2)


def test_fisher_is_symmetric_and_a_valid_probability():
    for table in [(4, 1, 0, 5), (2, 3, 4, 1), (0, 5, 5, 0), (1, 4, 4, 1)]:
        a, b, c, d = table
        p = fisher_exact_two_sided(*table)
        assert 0 < p <= 1
        assert p == pytest.approx(fisher_exact_two_sided(c, d, a, b))  # swap the arms
        assert p == pytest.approx(fisher_exact_two_sided(b, a, d, c))  # swap pass/fail


def test_wilson_matches_the_guides_values():
    lo, hi = wilson(0, 5)
    assert lo == 0 and hi == pytest.approx(0.434, abs=2e-3)
    lo, hi = wilson(4, 5)
    assert (lo, hi) == pytest.approx((0.376, 0.964), abs=2e-3)


def test_wilson_at_n_eight_no_longer_overlaps_for_the_hero_split():
    assert wilson(0, 8)[1] < wilson(7, 8)[0]
    assert wilson(0, 5)[1] > wilson(4, 5)[0]  # at N=5 they overlap: hence "directional"


def test_wilson_edges():
    assert wilson(0, 0) is None
    lo, hi = wilson(5, 5)
    assert hi == 1.0 and lo == pytest.approx(0.5655, abs=2e-3)
