"""Where the split threshold came from.

`SEPARATION` decides whether a folder is proposed for splitting, and it is the
one number in the pass that cannot be argued for from first principles. It was
measured here first and written into the constant afterwards.

The measurement has to answer a specific question, and it is not "does this
find two subjects". Two-means *always* returns two clusters — hand it a folder
about one thing and it will still hand back two halves and a positive number.
So the question is how large that spurious number gets, because the threshold
has to sit above every value a single subject can produce and below the values
a real division produces.

Vectors are synthetic, and parametrised by the two quantities anyone can
observe from a real embedder: the mean cosine between two entries about the
same subject, and the mean cosine between two entries about different ones. The
planting is stated rather than hidden — what this proves is that the statistic
separates the two cases by an order of magnitude, not that a real journal
divides where a real embedder would put it. That measurement needs a key and a
corpus and is written down in `upcoming.md` as owed.
"""

from __future__ import annotations

import math
import random
import statistics

import pytest

from tilt.jobs.split import SEPARATION, dot, normalise, separation, two_means

DIMS = 64
"""Enough room for two subjects to sit apart. A real embedder uses 768; the
statistic is dimensionless and the extra 704 only makes the estimates steadier,
which would flatter the result rather than test it."""

# Noise levels bisected offline for a target mean within-subject cosine. Named
# by what they produce, because the raw number means nothing.
TIGHT = 0.0723  # entries about one subject, mean cosine ≈ 0.75
LOOSE = 0.1376  # a broad subject, mean cosine ≈ 0.45


def unit(rng: random.Random) -> list[float]:
    return normalise([rng.gauss(0, 1) for _ in range(DIMS)])


def cluster(rng: random.Random, centre: list[float], spread: float, n: int) -> list[list[float]]:
    """Entries about one subject: a centre, plus how far people wander from it."""
    out = []
    for _ in range(n):
        noise = [rng.gauss(0, 1) for _ in range(DIMS)]
        out.append(normalise([c + spread * g for c, g in zip(centre, noise, strict=True)]))
    return out


def two_centres(rng: random.Random, cosine: float) -> tuple[list[float], list[float]]:
    """Two subject centres a chosen cosine apart, by Gram-Schmidt."""
    a = unit(rng)
    b = unit(rng)
    perp = normalise([x - dot(a, b) * y for x, y in zip(b, a, strict=True)])
    tilt = math.sqrt(max(0.0, 1 - cosine * cosine))
    return a, normalise([cosine * x + tilt * y for x, y in zip(a, perp, strict=True)])


def measure(vectors: list[list[float]]) -> float:
    return separation(vectors, two_means(vectors))


def mean_cosine(vectors: list[list[float]]) -> float:
    return statistics.fmean(
        dot(vectors[i], vectors[j])
        for i in range(len(vectors))
        for j in range(i + 1, len(vectors))
    )


# --------------------------------------------------------- the false positive


def test_one_subject_never_reaches_the_threshold() -> None:
    """The case that matters. A false split is the expensive error: it names
    two halves distinctly, so the merge pass will never look at them again.

    Measured across folder sizes from the minimum to a decade of writing, and
    across subjects tight and broad. Worst observed value: 0.06.
    """
    rng = random.Random(3)
    worst = 0.0
    for spread in (TIGHT, LOOSE):
        for size in (12, 20, 30, 60, 120, 240):
            for _ in range(6):
                worst = max(worst, measure(cluster(rng, unit(rng), spread, size)))

    assert worst < SEPARATION / 2, f"one subject scored {worst:.3f} against {SEPARATION}"


def drifting(rng: random.Random, stretch: float, n: int) -> list[list[float]]:
    """One subject, stretched along a single axis.

    Somebody circling a topic and moving steadily as they do — the entries are
    still one subject, but they lie along a line rather than in a ball. This is
    the shape that fools a clustering statistic, because two-means will cut the
    line in half and both halves will genuinely be more alike than they are to
    each other.
    """
    centre = unit(rng)
    axis = unit(rng)
    axis = normalise([x - dot(axis, centre) * y for x, y in zip(axis, centre, strict=True)])
    out = []
    for _ in range(n):
        noise = [rng.gauss(0, 1) for _ in range(DIMS)]
        drawn = [c + TIGHT * g for c, g in zip(centre, noise, strict=True)]
        along = TIGHT * (stretch - 1) * rng.gauss(0, 1)
        out.append(normalise([x + along * a for x, a in zip(drawn, axis, strict=True)]))
    return out


def test_a_drifting_subject_stays_under_it() -> None:
    """Up to a fourfold stretch, which is already a subject four times wider in
    one direction than in every other. Worst observed value: 0.11 — under, but
    by less than the isotropic case, and this is where the margin actually goes.
    """
    rng = random.Random(5)
    worst = 0.0
    for stretch in (2, 3, 4):
        for size in (12, 30):
            for _ in range(6):
                worst = max(worst, measure(drifting(rng, stretch, size)))

    assert worst < SEPARATION, f"a drifting subject scored {worst:.3f}"


def test_a_subject_that_drifted_far_enough_is_indistinguishable() -> None:
    """The limit of the statistic, pinned rather than left to be discovered.

    Stretch a single subject eight times and it scores like two subjects — 0.19
    typical, well over the threshold. That is not a bug in the number and no
    threshold fixes it: at some point "one subject that moved a long way" and
    "two subjects" are the same arrangement of points, and which one it is, is a
    question about meaning rather than geometry.

    This is exactly the case the model veto is for, and the reason the pass ends
    at a proposal instead of a rename. Geometry finds the candidate; it was
    never going to be what decides.
    """
    rng = random.Random(23)
    scores = [measure(drifting(rng, 8, 30)) for _ in range(8)]

    assert statistics.median(scores) > SEPARATION


# ---------------------------------------------------------- the true positive


def test_two_subjects_clear_it_comfortably() -> None:
    """Including two that are barely distinct — centres a cosine of 0.65 apart,
    which is two facets of one preoccupation rather than two preoccupations.
    Weakest observed value: 0.23, four times the worst false positive.
    """
    rng = random.Random(7)
    weakest = 1.0
    for apart in (0.65, 0.45, 0.20):
        for _ in range(6):
            left, right = two_centres(rng, apart)
            vectors = cluster(rng, left, TIGHT, 15) + cluster(rng, right, TIGHT, 15)
            weakest = min(weakest, measure(vectors))

    assert weakest > SEPARATION * 1.5, f"two subjects scored only {weakest:.3f}"


def test_a_smaller_second_subject_still_shows() -> None:
    """22 entries and 8, which is the shape this actually arrives in — a folder
    that has been one thing for a year and something else for a month."""
    rng = random.Random(11)
    weakest = 1.0
    for apart in (0.55, 0.35):
        for _ in range(6):
            left, right = two_centres(rng, apart)
            weakest = min(
                weakest,
                measure(cluster(rng, left, TIGHT, 22) + cluster(rng, right, TIGHT, 8)),
            )

    assert weakest > SEPARATION * 1.5


# ---------------------------------------------------- what the planting means


def test_the_planted_corpus_is_what_it_claims_to_be() -> None:
    """Guards the guard. If `TIGHT` drifted, every threshold above would still
    pass while measuring a corpus nobody described."""
    rng = random.Random(13)
    assert 0.70 < mean_cosine(cluster(rng, unit(rng), TIGHT, 40)) < 0.80
    assert 0.40 < mean_cosine(cluster(rng, unit(rng), LOOSE, 40)) < 0.50

    # Centres 0.45 apart, but entries are not their centre: each is pulled off
    # it by the same noise that sets the within-subject cosine, so the observed
    # cosine between two entries in different halves lands near 0.45 × 0.75.
    left, right = two_centres(rng, 0.45)
    across = statistics.fmean(
        dot(a, b)
        for a in cluster(rng, left, TIGHT, 20)
        for b in cluster(rng, right, TIGHT, 20)
    )
    assert 0.28 < across < 0.38


def test_the_statistic_agrees_with_counting_every_pair() -> None:
    """`separation` computes an O(n²) quantity in O(n) from the cluster sums.
    That is an identity, not an approximation, and this is the check that it
    was implemented as one."""
    rng = random.Random(17)
    left, right = two_centres(rng, 0.3)
    vectors = cluster(rng, left, TIGHT, 9) + cluster(rng, right, TIGHT, 7)
    assignment = [0] * 9 + [1] * 7

    within = statistics.fmean(
        dot(vectors[i], vectors[j])
        for i in range(len(vectors))
        for j in range(i + 1, len(vectors))
        if assignment[i] == assignment[j]
    )
    between = statistics.fmean(dot(a, b) for a in vectors[:9] for b in vectors[9:])

    assert separation(vectors, assignment) == pytest.approx(within - between, abs=1e-9)
