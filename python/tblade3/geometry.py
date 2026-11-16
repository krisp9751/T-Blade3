"""Result of one T-Blade3 run for one blade row."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Derivative groups, numbered as in T-Blade3 (derivative_files/xyz_ders_<group>_<field>_<cp>.dat)
DERIV_GROUPS = {1: "sweep", 2: "lean", 3: "in_beta", 4: "out_beta",
                5: "chord_multiplier", 6: "curvature", 7: "naca_thickness"}


@dataclass
class Derivatives:
    """Analytic derivatives written by T-Blade3. All indices are 1-based, as in the file names.

    xyz[(group, field, cp)]  -> (nsec, npt, 3)  d(x, y, z)/d(control point), mm per unit
    stagger[(group, field)]  -> (nsec, ncp)     d(stagger of each section)/d(each control point)
    throat[(group, field)]   -> (nsec, ncp)     d(minimum throat)/d(each control point)
    """
    xyz: dict[tuple[int, int, int], np.ndarray] = field(default_factory=dict)
    stagger: dict[tuple[int, int], np.ndarray] = field(default_factory=dict)
    throat: dict[tuple[int, int], np.ndarray] = field(default_factory=dict)


@dataclass
class Geometry:
    """Everything T-Blade3 produced for one blade row. Lengths are in mm (after the scale factor)."""
    casename: str
    row: int
    sections: np.ndarray                     # (nsec, npt, 3) x, y, z of each blade section
    meanlines: np.ndarray | None = None      # (nsec, nmean, 3) x, y, z of each meanline
    sections_2d: list[np.ndarray] = field(default_factory=list)   # per section (npt, 2): m-prime, theta
    section_table: dict[str, np.ndarray] = field(default_factory=dict)  # per-section columns (span, chord, ...)
    hub: np.ndarray | None = None            # (n, 3) hub curve
    casing: np.ndarray | None = None         # (n, 3) casing curve
    le_te: np.ndarray | None = None          # LE/TE intersection data, as written by T-Blade3
    # per section (n, 2): chord fraction u, full thickness / chord (thickness_data.<i>.<cn>); an empty
    # (0, 2) array for a section T-Blade3 wrote no thickness file for (airfoil type other than sect1)
    thickness: list[np.ndarray] = field(default_factory=list)
    # Camber line by curvature control (None otherwise):
    camber_data: np.ndarray | None = None    # (nsec, n, 4): chord fraction u, camber v, slope dv/du, curvature
    curvature_controls: np.ndarray | None = None   # (nsec, 2*ncp): u1..u<ncp>, cur1..cur<ncp> at each section
    curvature_scale: np.ndarray | None = None      # (nsec,): factor T-Blade3 applies to cur1.. to meet the blade angles
    derivatives: Derivatives | None = None
    log: str = ""                            # T-Blade3_run.log
    warnings: str = ""                       # error.log (warnings of a successful run)

    @property
    def nsec(self) -> int:
        return self.sections.shape[0]

    @property
    def npt(self) -> int:
        return self.sections.shape[1]
