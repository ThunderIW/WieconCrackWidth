"""Defect 3 regression — creep must act on the section, and never reduce strain.

What the fix guarantees, and what it deliberately does not:

  IT DOES     phi reaches the cracked-section solve (step 4), so sigma_s and the mean
              strain esm-ecm both rise with creep. That was the defect: phi only ever
              touched the tension-stiffening term of Eq 7.9, where it pushed the strain
              DOWN, and then went inert at the 0.6*sigma_s/Es floor.

  IT DOESN'T  guarantee w_k rises with phi for every section. w_k = sr_max * esm, and
              EN 1992-1-1 ties sr_max to the neutral axis: Eq 7.14 is 1.3*(h-x) outright,
              and Eq 7.11 runs through rho_p,eff, which hc_eff = min(2.5(h-d), (h-x)/3,
              h/2) sets. Creep deepens x, so both shrink sr_max. Where that beats the
              strain gain, w_k eases off. That is the code's geometry, not this
              implementation, so no test asserts otherwise.

Run:  .venv/Scripts/python -m pytest
"""

import random

import pytest

from WieconTools.crack_width_formula import crack_analyze

# The Wadi benchmark from the engine's own docstring.
BENCH = dict(
    section_width=1000,
    section_thickness=525,
    cover_to_bar_surface=40,
    opposite_face_bar_diameter=20,
    opposite_face_bar_spacing=150,
    tension_face_bar_diameter=16,
    tension_face_bar_spacing=150,
    concrete_strength=50,
    concrete_modulus=34,
    steel_modulus=200,
)

PHIS = [i * 0.125 for i in range(25)]  # 0.0 .. 3.0
SERVICE_SIGMA = 50.0  # MPa — below this the tension face is
# barely stressed and there is no crack


def analyse(phi=0.0, N=529.0, M=116.0, **overrides):
    """One run of the benchmark section, with overrides."""
    return crack_analyze(creep_coeff=phi, **{**BENCH, **overrides}).run(
        N_kN=N, M_kNm=M, w_max=0.30
    )


def _random_sections(n, seed):
    """Plausible-ish RC sections and service loads, deterministic per seed."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        kw = dict(
            section_width=rng.choice([300, 500, 1000]),
            section_thickness=rng.uniform(200, 900),
            cover_to_bar_surface=rng.uniform(25, 60),
            opposite_face_bar_diameter=rng.choice([10, 12, 16, 20, 25]),
            opposite_face_bar_spacing=rng.uniform(75, 300),
            tension_face_bar_diameter=rng.choice([10, 12, 16, 20, 25, 32]),
            tension_face_bar_spacing=rng.uniform(75, 300),
            concrete_strength=rng.choice([25, 30, 35, 40, 50, 60, 70]),
            concrete_modulus=rng.choice([0, 30, 34, 38]),
            steel_modulus=200,
            bar_type=rng.choice(["ribbed", "plain"]),
            load_duration=rng.choice(["long", "short"]),
        )
        out.append((kw, rng.uniform(-200, 900), rng.uniform(0, 300)))
    return out


# Swept once at import (~15k engine runs, a couple of seconds) and shared by the
# invariant tests, rather than re-swept per test.
_SECTIONS = _random_sections(600, 20260717)
_SWEEPS = [
    [crack_analyze(creep_coeff=p, **kw).run(N_kN=N, M_kNm=M) for p in PHIS]
    for kw, N, M in _SECTIONS
]

# Only sections actually cracked in tension carry the invariant. On a compression-
# dominated section creep deepens x and pushes the near-zero tension steel toward
# compression, so sigma_s correctly FALLS — and w_k is 0 throughout, because there
# is no crack to widen.
CRACKED = [
    pytest.param(rs, id=f"sec{i:03d}")
    for i, rs in enumerate(_SWEEPS)
    if rs[0].mode == "N+M" and rs[0].sigma_s >= SERVICE_SIGMA
]


# --- the benchmark must not move -----------------------------------------


@pytest.mark.parametrize(
    "field, expected, tol",
    [
        ("alpha_e", 5.88, 0.01),
        ("x", 25.1, 0.05),
        ("sigma_s", 395.7, 0.05),
        ("rho_p_eff", 0.0112, 0.0001),
        ("sr_max", 565.0, 0.5),
        ("wk", 0.678, 0.0005),
    ],
)
def test_benchmark_reproduces_reference_tool(field, expected, tol):
    """The creep fix is inert at phi=0, so the Wadi benchmark must be untouched."""
    assert getattr(analyse(), field) == pytest.approx(expected, abs=tol)


def test_benchmark_verdict_is_fail():
    assert analyse().ok is False


# --- the defect itself ----------------------------------------------------


@pytest.mark.parametrize("field", ["x", "sigma_s", "esm_minus_ecm"])
def test_creep_reaches_the_section_solve(field):
    """The bug: phi never moved x or sigma_s off their phi=0 values."""
    before, after = analyse(phi=0.0), analyse(phi=2.0)
    assert getattr(after, field) > getattr(before, field)


def test_creep_widens_the_crack_on_the_benchmark_section():
    assert analyse(phi=2.0).wk > analyse(phi=0.0).wk


@pytest.mark.parametrize("phi", [0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
def test_creep_is_never_inert(phi):
    """The bug's second half: w_k pinned at 0.670 for every phi >= 0.5."""
    assert abs(analyse(phi=phi).wk - analyse(phi=0.0).wk) > 1e-9


@pytest.mark.parametrize("phi", [0.5, 1.0, 2.0, 3.0])
def test_creep_is_inert_under_short_duration(phi):
    """Creep develops under sustained stress only: 'short' must force phi = 0,
    so every result field matches the un-crept run exactly."""
    crept = analyse(phi=phi, load_duration="short")
    uncrept = analyse(phi=0.0, load_duration="short")
    assert crept == uncrept


@pytest.mark.parametrize("phi", [0.0, 0.5, 1.0, 2.0, 3.0])
def test_short_duration_changes_nothing_but_the_creep_gate(phi):
    """Duration's ONLY influence is gating creep: a 'short' run at any phi must
    equal the 'long' run at phi = 0 in every field. This pins kt at 0.4 for both
    durations — a deliberate deviation from EC2, which prescribes 0.6 short-term."""
    assert analyse(phi=phi, load_duration="short") == analyse(
        phi=0.0, load_duration="long"
    )


# --- the invariant, over randomised sections ------------------------------


@pytest.mark.parametrize("sweep", CRACKED)
def test_steel_stress_never_falls_with_creep(sweep):
    for before, after, phi in zip(sweep, sweep[1:], PHIS[1:]):
        assert after.sigma_s >= before.sigma_s - 1e-9, (
            f"sigma_s fell at phi={phi}: {before.sigma_s:.4f} -> {after.sigma_s:.4f}"
        )


@pytest.mark.parametrize("sweep", CRACKED)
def test_mean_strain_never_falls_with_creep(sweep):
    for before, after, phi in zip(sweep, sweep[1:], PHIS[1:]):
        assert after.esm_minus_ecm >= before.esm_minus_ecm - 1e-15, (
            f"esm fell at phi={phi}: "
            f"{before.esm_minus_ecm:.6e} -> {after.esm_minus_ecm:.6e}"
        )


def test_the_sweep_actually_covers_something():
    """Guards the two tests above from silently passing on an empty parameter set."""
    assert len(CRACKED) > 300, f"only {len(CRACKED)} of {len(_SWEEPS)} sections cracked"


def test_engine_never_raises_on_a_valid_section():
    """Every sweep above ran at import; reaching here means none of them raised."""
    assert len(_SWEEPS) == len(_SECTIONS)
