"""Crack-width check to EN 1992-1-1 (Eurocode 2) cl. 7.3.4.

Computes the characteristic crack width w_k of a reinforced-concrete section under
a service axial force N and bending moment M, and checks it against a limit.

Pure maths: no UI, no database, no file I/O, no globals, no randomness. The same
inputs always give the same report_result. That is deliberate — it is what lets
the engine be regression-tested without launching anything (`uv run pytest`), and
reused outside the app.

    from WieconTools.crack_width_formula import crack_analyze

    r = crack_analyze(
            section_width=1000, section_thickness=525, cover_to_bar_surface=40,
            tension_face_bar_diameter=16, tension_face_bar_spacing=150,
            opposite_face_bar_diameter=20, opposite_face_bar_spacing=150,
            concrete_strength=50, concrete_modulus=34, steel_modulus=200,
        ).run(N_kN=529, M_kNm=116, w_max=0.30)

    r.wk, r.ok      # 0.678 mm, False


UNITS
    In      lengths mm · strengths/stresses MPa · moduli GPa · N in kN · M in kNm
    Out     w_k and s_r,max in mm · stresses MPa · areas mm^2 · strains dimensionless
    Inside  everything is N and mm, so moduli become MPa (= N/mm^2) and M becomes
            N·mm. The GPa->MPa and kN->N conversions happen once, at the boundary.

    Every quantity is PER SECTION WIDTH b: A_s is the steel within b, not per bar.
    With b = 1000 the whole check reads "per metre run", which is how a wall or a
    slab is normally assessed.

SIGN CONVENTION
    N > 0 is TENSION, N < 0 compression. Compression is handled rather than
    rejected: where the tension face ends up in compression, sigma_s comes out
    negative and step 9 returns w_k = 0, because steel in compression cannot open
    a crack.

THE NINE STEPS — run() executes them in this order
    1   A_s, both faces, from bar diameter and spacing
    2   f_ctm, E_cm, E_c,eff, alpha_e                        Table 3.1
    3   sigma_ct vs f_ctm — is the section cracked?           reported, not acted on
    4   neutral axis x, then sigma_s                          the hard one
    5   h_c,eff, A_c,eff, rho_p,eff, k2                       cl. 7.3.2(3), Eq 7.13
    7   esm - ecm, the mean strain difference                 Eq 7.9
    8   s_r,max, the maximum crack spacing                    Eq 7.11 or Eq 7.14
    9   w_k = s_r,max * (esm - ecm), and the verdict          Eq 7.8

    There is no step_6: steps 5 and 6 are the one method, step_5_6_effective_area.

VERIFICATION — the "Wadi" benchmark, reproduced against an independent tool
    1000 x 525 mm · cover 40 · Ø16 @ 150 tension face · Ø20 @ 150 opposite face
    C50/60 · E_c 34 GPa · E_s 200 GPa · creep 0 · N = 529 kN · M = 116 kNm

    alpha_e 5.88 · x 25.1 mm · sigma_s 395.7 MPa · rho_p,eff 1.12 %
    s_r,max 565 mm (Eq 7.11) · w_k 0.678 mm  ->  FAIL against w_max = 0.30 mm

    tests/test_creep.py pins all six. Re-run it after touching this file.

KNOWN LIMITATIONS — read before trusting a number
    * k3 = 3.4 and k4 = 0.425 are EC2's recommended values, but both are Nationally
      Determined Parameters. Some National Annexes differ — the UK NA, for one,
      makes k3 depend on cover instead of fixing it at 3.4. Override them through
      the constructor if your NA says otherwise.
    * `cracked` (step 3) is computed and reported but never acted on: the check
      runs whether or not sigma_ct reaches f_ctm. By that test the benchmark is
      itself uncracked (3.53 < 4.07 MPa), yet the reference tool computes a crack
      width for it regardless — so the flag's intent is unresolved. Technical
      briefing, defect 4.
    * Two bar layers only, one per face, each a single diameter at uniform spacing.
      No bundled bars, no mixed diameters (Eq 7.12), no prestress — the xi_1*A_p'
      term of Eq 7.10 is not implemented.
    * The check assumes service-level stress in elastic steel. Nothing stops you
      entering loads that yield the bars; the formulas will still return a number,
      and it will not mean anything.
"""

import math
from dataclasses import dataclass


@dataclass
class report_result:
    """Every quantity the cl. 7.3.4 check produces — not just the answer.

    Returned by crack_analyze.run(). The full set is here so that one run can feed
    the detail view, the PDF report and the database row without recomputing, and
    so an intermediate can be inspected when a result looks wrong.

    Mutable: nothing currently reshapes one, but nothing stops it either.
    """

    As_b: float  # tension-face steel area [mm^2]
    As_t: float  # opposite-face steel area [mm^2]
    d: float  # effective depth [mm]
    fctm: float  # mean tensile strength [MPa]
    Ec_GPa: float  # concrete modulus [GPa]
    alpha_e: float  # modular ratio Es / Ec,eff
    sigma_ct: float  # concrete tensile stress [MPa]
    cracked: bool  # sigma_ct >= fctm
    mode: str  # "N+M" or "pure-tension"
    x: float  # neutral-axis depth [mm]
    sigma_s: float  # tension-face steel stress [MPa]
    sigma_s_top: float  # opposite-face steel stress [MPa]
    hc_eff: float  # effective tension-zone height [mm]
    Ac_eff: float  # effective concrete area [mm^2]
    rho_p_eff: float  # effective reinforcement ratio
    k2: float  # strain-distribution coefficient
    esm_minus_ecm: float  # mean strain difference
    sr_max: float  # maximum crack spacing [mm]
    sr_equation: str  # "Eq 7.11" or "Eq 7.14"
    wk: float  # crack width [mm]
    w_max: float  # crack-width limit [mm]
    ok: bool  # wk <= w_max


class crack_analyze:
    """One reinforced-concrete section. The loads come later, at run().

    Split that way on purpose: a section is checked against several load cases
    (base, mid, top of a wall), so building it once and calling run() per case
    avoids re-deriving the geometry each time.

        section = crack_analyze(...)          # geometry + materials
        base    = section.run(529, 116)       # load case 1
        mid     = section.run(300, 80)        # load case 2
    """

    def __init__(
        self,
        section_width,
        section_thickness,
        cover_to_bar_surface,
        opposite_face_bar_diameter,
        opposite_face_bar_spacing,
        tension_face_bar_diameter,
        tension_face_bar_spacing,
        concrete_strength,
        concrete_modulus,
        steel_modulus,
        creep_coeff=0.0,
        bar_type="ribbed",
        load_duration="long",
        k3=3.4,
        k4=0.425,
    ):
        """Define the section. Everything is per section width b.

        WARNING: the OPPOSITE face comes before the tension face in this signature.
        Pass by keyword — positionally it is easy to swap the two faces silently,
        and the check will happily return a plausible, wrong answer.

        Geometry
        :param section_width:  b — the width the steel areas are counted over [mm].
                               1000 gives a per-metre check.
        :param section_thickness: h — overall thickness [mm].
        :param cover_to_bar_surface: c — clear cover to the BAR SURFACE [mm], not
                               to the bar centre. Feeds s_r,max directly (k3*c).

        Reinforcement — "tension face" is the face the crack is checked on.
        :param tension_face_bar_diameter: bar Ø on the tension face [mm].
        :param tension_face_bar_spacing:  centre-to-centre spacing there [mm].
                               Whether this exceeds 5(c + Ø/2) decides which
                               s_r,max equation applies — see step 8.
        :param opposite_face_bar_diameter: bar Ø on the opposite face [mm].
        :param opposite_face_bar_spacing:  centre-to-centre spacing there [mm].

        Materials
        :param concrete_strength: f_ck — characteristic cylinder strength [MPa].
                               The f_ctm formula changes branch above C50/60.
        :param concrete_modulus: E_cm — secant modulus [GPa]. Pass 0 to derive it
                               from f_ck via Table 3.1 (the app's "auto").
        :param steel_modulus:  E_s [GPa]. 200 for reinforcement.
        :param creep_coeff:    φ — creep coefficient [-]. Softens the concrete to
                               E_c,eff = E_cm/(1 + φ) for the section analysis, so
                               the neutral axis deepens and the steel works harder.
                               Only applied when load_duration is 'long': creep
                               develops under sustained stress, so a short-term
                               check runs with φ = 0 whatever is passed here.
                               EC2 Annex B / Fig 3.1 gives φ from humidity,
                               notional size and loading age; typically 1.5–3 for
                               a sustained load on normal-weight concrete.
        :param bar_type:       'ribbed' (high bond, k1 = 0.8) or 'plain'
                               (k1 = 1.6). Poorer bond, wider cracks.
        :param load_duration:  'long' or 'short'. Its ONLY effect is gating
                               creep_coeff: 'short' forces φ = 0, so a
                               short-duration run reproduces the φ = 0 result
                               exactly. Deliberate deviation from EC2: Eq 7.9's
                               k_t stays 0.4 for both durations, where the code
                               prescribes 0.6 for short-term loading.

        National Annex parameters — recommended values; check yours.
        :param k3: coefficient on the cover term of Eq 7.11. Recommended 3.4.
        :param k4: coefficient on the Ø/rho term of Eq 7.11. Recommended 0.425.
        """

        self.b = section_width
        self.h = section_thickness
        self.c = cover_to_bar_surface
        self.dia_t = opposite_face_bar_diameter
        self.spac_t = opposite_face_bar_spacing
        self.dia_b = tension_face_bar_diameter
        self.spac_b = tension_face_bar_spacing
        self.fck = concrete_strength
        self.Ec_input = concrete_modulus
        self.Es_gpa = steel_modulus
        # Creep is strain under SUSTAINED stress: a short-duration check is a
        # first loading, where no creep has had time to develop. Gating phi here
        # (not at the usage sites) keeps steps 2 and 4 seeing the same concrete.
        self.phi = creep_coeff if load_duration == "long" else 0.0
        self.bar_type = bar_type
        self.load_duration = load_duration
        self.k3 = k3
        self.k4 = k4

        # Here are some Derived geometry, used in later calculations
        self.d1 = self.c + self.dia_t / 2
        self.d2 = self.h - self.c - self.dia_b / 2
        self.d = self.d2

    def step_1_steel_area(self):
        """Here we return As_b-> Tension-face and As_t->Opposite-face steel area
        in mm^2 per section width b."""
        As_b = math.pi / 4 * self.dia_b**2 * (self.b / self.spac_b)
        As_t = math.pi / 4 * self.dia_t**2 * (self.b / self.spac_t)
        return As_b, As_t

    def step_2_material_properties(self):

        # Mean tensile Strength
        if self.fck <= 50:
            fctm = 0.30 * self.fck ** (2 / 3)
        else:
            fctm = 2.12 * math.log(1 + (self.fck + 8) / 10)

        # Concrete modulus
        if self.Ec_input > 0:
            Ec = self.Ec_input * 1000
        else:
            Ec = 22 * ((self.fck + 8) / 10) ** 0.3 * 1000

        # Creep-adjusted modulus and modular ratio
        Ec_eff = Ec / (1 + self.phi)
        Es = self.Es_gpa * 1000
        alpha_e = Es / Ec_eff

        return fctm, Ec, Es, alpha_e

    def step_3_cracking_check(self, N_kN, M_kNm):
        fctm, *_ = self.step_2_material_properties()
        N = N_kN * 1e3
        M = M_kNm * 1e6
        sigma_ct = N / (self.b * self.h) + M / (self.b * self.h**2 / 6)
        return sigma_ct, sigma_ct >= fctm

    @staticmethod
    def _bracket_and_bisect(F, hi_limit, samples=400):
        """Smallest x in (0, hi_limit] where F changes sign, or None if it never does."""
        lo = 1e-6
        f_lo = F(lo)
        step = hi_limit / samples
        x = lo
        while x < hi_limit:
            hi = min(x + step, hi_limit)
            f_hi = F(hi)
            if f_lo == 0.0:
                return x
            if f_lo * f_hi < 0.0:
                a, b, f_a = x, hi, f_lo
                for _ in range(200):
                    mid = 0.5 * (a + b)
                    f_mid = F(mid)
                    if f_a * f_mid <= 0.0:
                        b = mid
                    else:
                        a, f_a = mid, f_mid
                return 0.5 * (a + b)
            x, f_lo = hi, f_hi
        return None

    def step_4_steel_stress(self, N_kN, M_kNm):
        As_b, As_t = self.step_1_steel_area()
        _, Ec, _, _ = self.step_2_material_properties()
        Es = self.Es_gpa * 1000
        b, h, d1, d2 = self.b, self.h, self.d1, self.d2
        N = N_kN * 1e3
        M = M_kNm * 1e6

        # Solve the section with the CREEP-ADJUSTED modulus, not the raw Ec.
        # Creep softens the concrete, so under sustained load the compression zone
        # deepens and the steel picks up more stress -- which is the whole reason
        # phi belongs in a crack check. Using the raw Ec here left phi reaching
        # only the tension-stiffening term (1 + alpha_e*rho) in step 7, where a
        # rising alpha_e *reduces* the strain: phi made w_k smaller, then stopped
        # doing anything at all once esm hit its 0.6*sigma_s/Es floor.
        # Ec_eff mirrors step 2, which already defines alpha_e = Es / Ec_eff --
        # the two steps now describe the same concrete. At phi = 0 (the default,
        # and the benchmark) Ec_eff == Ec, so nothing else moves.
        Ec_eff = Ec / (1 + self.phi)

        def Pf(x):
            """Net axial force on the cracked section, per unit curvature."""
            return Ec_eff * b * x**2 / 2 + Es * (As_t * (x - d1) + As_b * (x - d2))

        def Qf(x):
            """Moment of those same forces about mid-depth, per unit curvature."""
            return Es * (
                As_t * (d1 - x) * (d1 - h / 2) + As_b * (d2 - x) * (d2 - h / 2)
            ) + Ec_eff * b * x**2 / 2 * (h / 2 - x / 3)

        def F(x):
            # Equilibrium: the internal and external resultants must be collinear.
            # Stated as M*Pf + N*Qf = 0 rather than Mf(x)/Pf(x) = h/2 + M/N, which
            # is the same condition wherever both are valid but divides by N --
            # undefined in pure bending, and sign-flipped under compression.
            return M * Pf(x) + N * Qf(x)

        x = self._bracket_and_bisect(F, h)

        if x is None:
            # No neutral axis inside the depth: the section is wholly in tension
            # (only the bar layers carry the load) or wholly in compression, in
            # which case sigma_s comes out negative and step 9 reports no crack.
            sigma_s = N / (As_t + As_b)
            return {
                "mode": "pure-tension" if N >= 0 else "pure-compression",
                "x": 0.0,
                "sigma_s": sigma_s,
                "sigma_s_top": sigma_s,
            }

        # Curvature from whichever equilibrium equation is better conditioned.
        p, q = Pf(x), Qf(x)
        kappa = M / q if abs(q) >= abs(p) else -N / p

        return {
            "mode": "N+M",
            "x": x,
            "sigma_s": Es * kappa * (d2 - x),
            "sigma_s_top": Es * kappa * (d1 - x),
        }

    def step_5_6_effective_area(self, mode, x):
        As_b, _ = self.step_1_steel_area()
        h, c, d = self.h, self.c, self.d

        # x == 0 means no neutral axis inside the section, i.e. one of the two
        # no-compression-zone modes. Keyed on x, not the label, so pure-compression
        # follows the same path.
        if x <= 0:
            hc_eff = min(2.5 * (c + self.dia_b / 2), h / 2)
            k2 = 1.0

        else:
            hc_eff = min(2.5 * (h - d), (h - x) / 3, h / 2)
            e1 = h - x
            e2 = (h - hc_eff) - x
            k2 = max(0.5, min(1.0, (e1 + e2) / (2 * e1))) if e1 > 0 else 0.5

        Ac_eff = self.b * hc_eff
        rho = As_b / Ac_eff
        return hc_eff, Ac_eff, rho, k2

    def step_7_mean_stain(self, sigma_s, rho):

        fctm, Ec, _, _ = self.step_2_material_properties()
        Es = self.Es_gpa * 1000
        # Eq 7.9 defines alpha_e as Es/Ecm -- the SHORT-TERM secant modulus. Creep
        # does not belong in this term: duration enters through sigma_s, which
        # step 4 already solves on the creep-adjusted section.
        #
        # Feeding the creep-adjusted ratio in here instead (Es/Ec_eff, which is
        # what report_result reports) inverted the whole coefficient: a rising phi
        # inflates (1 + alpha_e*rho), which SUBTRACTS more from sigma_s, so more
        # creep produced a smaller w_k -- until esm hit its 0.6*sigma_s/Es floor
        # and phi stopped mattering at all.
        alpha_e = Es / Ec
        # Deliberate deviation from EC2, which switches kt to 0.6 for short-term
        # loading: kt is pinned at 0.4 for both durations so that selecting
        # 'short' changes NOTHING but the creep gate (phi = 0). A short run must
        # equal the long run at phi = 0 exactly — tests/test_creep.py pins this.
        kt = 0.4
        esm = (sigma_s - kt * fctm / rho * (1 + alpha_e * rho)) / Es
        # Floored at zero as well as at 0.6*sigma_s/Es: steel in compression gives
        # a negative sigma_s, and a negative mean strain is not a crack.
        return max(esm, 0.6 * sigma_s / Es, 0.0)

    def step_8_crack_spacing(self, mode, x, rho, k2):
        k1 = 0.8 if self.bar_type == "ribbed" else 1.6
        cond = 5 * (self.c + self.dia_b / 2)
        if self.spac_b <= cond or x <= 0:
            sr = self.k3 * self.c + k1 * k2 * self.k4 * self.dia_b / rho
            return sr, "Eq 7.11"
        return 1.3 * (self.h - x), "Eq 7.14"

    def step_9_crack_width(self, sr_max, esm, sigma_s):
        # Steel in compression cannot open a crack. Without this the check reports
        # a negative w_k, which then silently satisfies w_k <= w_max.
        if sigma_s <= 0:
            return 0.0
        return sr_max * esm

    def run(self, N_kN, M_kNm, w_max=0.30):
        """Runs all steps in order and returns every result as a report_result."""
        As_b, As_t = self.step_1_steel_area()
        fctm, Ec, _Es, alpha_e = self.step_2_material_properties()
        sigma_ct, cracked = self.step_3_cracking_check(N_kN, M_kNm)
        s4 = self.step_4_steel_stress(N_kN, M_kNm)
        hc_eff, Ac_eff, rho, k2 = self.step_5_6_effective_area(s4["mode"], s4["x"])
        esm = self.step_7_mean_stain(s4["sigma_s"], rho)
        sr_max, sr_eq = self.step_8_crack_spacing(s4["mode"], s4["x"], rho, k2)
        wk = self.step_9_crack_width(sr_max, esm, s4["sigma_s"])

        return report_result(
            As_b=As_b,
            As_t=As_t,
            d=self.d,
            fctm=fctm,
            Ec_GPa=Ec / 1000,
            alpha_e=alpha_e,
            sigma_ct=sigma_ct,
            cracked=cracked,
            mode=s4["mode"],
            x=s4["x"],
            sigma_s=s4["sigma_s"],
            sigma_s_top=s4["sigma_s_top"],
            hc_eff=hc_eff,
            Ac_eff=Ac_eff,
            rho_p_eff=rho,
            k2=k2,
            esm_minus_ecm=esm,
            sr_max=sr_max,
            sr_equation=sr_eq,
            wk=wk,
            w_max=w_max,
            ok=wk <= w_max,
        )

    def report(self, N_kN, M_kNm, w_max=0.30):
        """Prints a readable summary of the full check."""
        r = self.run(N_kN, M_kNm, w_max)
        print("=" * 56)
        print("Crack-Width Check -- EN 1992-1-1 cl. 7.3.4")
        print("=" * 56)
        print(self.section_sketch())
        print("-" * 56)
        print(f"  As tension face       {r.As_b:9.0f} mm^2")
        print(f"  As opposite face      {r.As_t:9.0f} mm^2")
        print(f"  Effective depth d     {r.d:9.1f} mm")
        print(f"  f_ctm                 {r.fctm:9.2f} MPa")
        print(f"  Modular ratio a_e     {r.alpha_e:9.2f}")
        print(
            f"  sigma_ct              {r.sigma_ct:9.2f} MPa"
            f"   cracked: {'yes' if r.cracked else 'no'}"
        )
        print(f"  Mode                  {r.mode:>9}")
        if r.mode != "pure-tension":
            print(f"  Neutral axis x        {r.x:9.1f} mm")
        print(f"  sigma_s tension face  {r.sigma_s:9.1f} MPa")
        print(f"  h_c,eff               {r.hc_eff:9.1f} mm")
        print(f"  rho_p,eff             {r.rho_p_eff * 100:9.2f} %")
        print(f"  k2                    {r.k2:9.2f}")
        print(f"  esm - ecm             {r.esm_minus_ecm * 1e3:9.3f} x10^-3")
        print(f"  s_r,max               {r.sr_max:9.0f} mm ({r.sr_equation})")
        print("-" * 56)
        print(f"  CRACK WIDTH w_k       {r.wk:9.3f} mm")
        print(f"  Limit w_max           {r.w_max:9.2f} mm")
        print(f"  VERDICT               {'PASS' if r.ok else 'FAIL':>9}")
        print("=" * 56)
        return r


"""
if __name__ == "__main__":
    # Wadi example -- regression test against the HTML tool
    ca = crack_analyze(
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
    ca.report(N_kN=529, M_kNm=116, w_max=0.30)
    # Expected: alpha_e 5.88, x 25.1 mm, sigma_s 395.7 MPa,
    #           rho 1.12 %, s_r,max 565 mm (Eq 7.11), w_k 0.678 mm -> FAIL

"""
