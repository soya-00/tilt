"""Where the mis-filing margin came from.

`MARGIN` decides whether an entry is worth mentioning, and it was measured here
before it was written into the constant — the same discipline as `SEPARATION`,
and for the same reason: a threshold chosen by taste is a threshold nobody can
argue with later.

The statistic is a difference of two cosines:

    margin = how well the entry sits in the nearest folder it is NOT in
           − how well it sits in its own, with itself left out

which means a correctly filed entry does not merely score low. It scores
**negative**, because being inside a subject and being outside it are opposite
signs of the same quantity. That is why the two cases here separate further
apart than anything else measured in this app.

Vectors are planted, parametrised by how far apart two folders are. What this
proves is that the statistic separates; what it does not prove is where a real
embedder puts a real journal, which needs a key and somebody's writing.
"""

from __future__ import annotations

import math
import random

from tilt.jobs.misfiled import MARGIN, affinity, belonging, summed
from tilt.jobs.split import dot, normalise

DIMS = 64
TIGHT = 0.0723
"""Noise level for a mean within-subject cosine of about 0.75 — the same corpus
shape the split threshold was measured against, so the two numbers are talking
about the same kind of journal."""


def unit(rng: random.Random) -> list[float]:
    return normalise([rng.gauss(0, 1) for _ in range(DIMS)])


def near(rng: random.Random, centre: list[float]) -> list[float]:
    return normalise([c + TIGHT * rng.gauss(0, 1) for c in centre])


def two_centres(rng: random.Random, cosine: float) -> tuple[list[float], list[float]]:
    a = unit(rng)
    b = unit(rng)
    perp = normalise([x - dot(a, b) * y for x, y in zip(b, a, strict=True)])
    tilt = math.sqrt(max(0.0, 1 - cosine * cosine))
    return a, normalise([cosine * x + tilt * y for x, y in zip(a, perp, strict=True)])


def margin(vector: list[float], own: list[list[float]], other: list[list[float]]) -> float:
    return affinity(vector, summed(other)) - belonging(vector, summed(own), len(own))


# --------------------------------------------------------- the false positive


def test_a_correctly_filed_entry_scores_negative() -> None:
    """Not merely below the threshold — the wrong side of zero. An entry inside
    its subject is closer to that subject than to any other, and the statistic
    says so with a sign rather than with a margin."""
    rng = random.Random(3)
    worst = -1.0
    for apart in (0.0, 0.3, 0.5, 0.65):
        for size in (5, 8, 15, 40):
            for _ in range(4):
                a, b = two_centres(rng, apart)
                own = [near(rng, a) for _ in range(size)]
                other = [near(rng, b) for _ in range(size)]
                worst = max(worst, max(margin(v, own, other) for v in own))

    assert worst < 0, f"a correctly filed entry scored {worst:+.3f}"
    assert worst < MARGIN / 2


# ---------------------------------------------------------- the true positive


def test_a_mis_filed_entry_clears_it() -> None:
    """Including between two folders only 0.65 apart, which is two facets of one
    preoccupation rather than two preoccupations."""
    rng = random.Random(7)
    weakest = 1.0
    for apart in (0.0, 0.3, 0.5, 0.65):
        for size in (5, 8, 15, 40):
            for _ in range(4):
                a, b = two_centres(rng, apart)
                stray = near(rng, b)
                own = [near(rng, a) for _ in range(size - 1)] + [stray]
                other = [near(rng, b) for _ in range(size)]
                weakest = min(weakest, margin(stray, own, other))

    assert weakest > MARGIN, f"a mis-filed entry scored only {weakest:+.3f}"


def test_the_threshold_sits_in_the_gap() -> None:
    """Stated as the property rather than left implicit in two other tests: the
    worst false positive and the weakest true positive are on opposite sides of
    it, with room."""
    assert 0 < MARGIN < 0.17


# ------------------------------------------- what leave-one-out actually buys


def test_leaving_the_entry_out_buys_recall_where_the_evidence_is_thin() -> None:
    """The claim worth being careful about.

    The obvious argument — that without leave-one-out an entry drags its own
    folder's centroid towards itself and so always looks correctly filed — is
    too strong, and the measurement says so: the naive version still finds most
    planted mis-filings. Where it loses is the hard case, a small folder whose
    subject is barely distinct from its neighbour's.

    So this asserts what is true rather than what would be tidier: both find the
    easy ones, and only leave-one-out finds all of the hard ones.
    """
    rng = random.Random(11)
    found = missed = 0
    for _ in range(60):
        a, b = two_centres(rng, 0.65)
        stray = near(rng, b)
        own = [near(rng, a) for _ in range(4)] + [stray]
        other = [near(rng, b) for _ in range(5)]

        assert margin(stray, own, other) >= MARGIN, "leave-one-out finds it"

        naive = affinity(stray, summed(other)) - affinity(stray, summed(own))
        if naive >= MARGIN:
            found += 1
        else:
            missed += 1

    assert missed > 0, "if the naive version never misses, this is not worth doing"
    assert found > missed, "and the difference is a minority of cases, not most"
