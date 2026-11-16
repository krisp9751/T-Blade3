"""Parser and writer of the T-Blade3 input files (io/maininput.py, io/spancontrol.py)."""
from __future__ import annotations

import copy
import dataclasses
import re
from pathlib import Path

import numpy as np
import pytest
from conftest import TCT_DIR, TCT_MAIN, load_case

from tblade3 import TBlade3Error, paths
from tblade3.errors import InputFormatError
from tblade3.io import maininput, spancontrol
from tblade3.io.maininput import ControlTable, MainInput
from tblade3.io.spancontrol import ControlInputs, SpanControl

CASES = sorted(paths.INPUTS_DIR.rglob("3dbgbinput.*.dat"))
CASE_IDS = [str(p.relative_to(paths.INPUTS_DIR)) for p in CASES]


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------

def assert_same(a, b, where: str = "") -> None:
    """Exact equality of dataclasses, dicts, lists and arrays (arrays: shape, dtype kind, values)."""
    if dataclasses.is_dataclass(a):
        assert type(a) is type(b), where
        for f in dataclasses.fields(a):
            assert_same(getattr(a, f.name), getattr(b, f.name), f"{where}.{f.name}")
    elif isinstance(a, dict):
        assert isinstance(b, dict) and list(a) == list(b), f"{where}: keys {list(a)} != {list(b)}"
        for k in a:
            assert_same(a[k], b[k], f"{where}[{k!r}]")
    elif isinstance(a, (list, tuple)):
        assert isinstance(b, (list, tuple)) and len(a) == len(b), f"{where}: {a!r} != {b!r}"
        for i, (x, y) in enumerate(zip(a, b)):
            assert_same(x, y, f"{where}[{i}]")
    elif isinstance(a, np.ndarray):
        assert isinstance(b, np.ndarray), where
        assert a.shape == b.shape and a.dtype.kind == b.dtype.kind, f"{where}: {a.shape} {b.shape}"
        np.testing.assert_array_equal(a, b, err_msg=where)
    else:
        assert type(a) is type(b) and a == b, f"{where}: {a!r} != {b!r}"


def aux_name(files: dict[str, str]) -> str | None:
    return next((n for n in files if not n.startswith("3dbgbinput")), None)


def parse_files(files: dict[str, str], main: str) -> tuple[MainInput, SpanControl | ControlInputs | None]:
    m = maininput.parse(files[main])
    name = aux_name(files)
    if name is None:
        return m, None
    if name.startswith("controlinputs"):
        return m, spancontrol.parse_controlinputs(files[name], m.n_streamlines)
    return m, spancontrol.parse_spancontrol(files[name], m.thickness_distribution,
                                            thickness_multiplier=m.thickness_multiplier, le_spline=m.le_spline)


def format_files(main_name: str, m: MainInput, aux, name: str | None) -> dict[str, str]:
    out = {main_name: maininput.format(m)}
    if isinstance(aux, SpanControl):
        out[name] = spancontrol.format_spancontrol(aux)
    elif isinstance(aux, ControlInputs):
        out[name] = spancontrol.format_controlinputs(aux)
    return out


def regenerate(files: dict[str, str], main: str) -> dict[str, str]:
    m, aux = parse_files(files, main)
    return format_files(main, m, aux, aux_name(files))


def case_files(path: Path) -> dict[str, str]:
    return load_case(path.parent, path.name)


@pytest.fixture(scope="module")
def session_engine():
    try:
        paths.executable()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    from tblade3.engine import ExecutableEngine
    eng = ExecutableEngine()
    yield eng
    eng.close()


@pytest.fixture(scope="module")
def original_runs(session_engine):
    """Lazily filled cache: case id -> Geometry (or TBlade3Error) of a run on the original files."""
    cache: dict[str, object] = {}

    def get(case_id: str):
        if case_id not in cache:
            path = paths.INPUTS_DIR / case_id
            try:
                cache[case_id] = session_engine.run(case_files(path), path.name, derivatives=False)
            except TBlade3Error as exc:
                cache[case_id] = exc
        result = cache[case_id]
        if isinstance(result, TBlade3Error):
            raise result
        return result
    return get


@pytest.fixture(scope="module")
def tct():
    files = load_case(TCT_DIR, TCT_MAIN)
    m, aux = parse_files(files, TCT_MAIN)
    return files, m, aux


def run(engine, m: MainInput, aux, files: dict[str, str]):
    return engine.run(format_files(TCT_MAIN, m, aux, aux_name(files)), TCT_MAIN, derivatives=False)


# --------------------------------------------------------------------------------------------
# Round trips over every shipped case
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", CASES, ids=CASE_IDS)
def test_parse_format_parse(path):
    files = case_files(path)
    m, aux = parse_files(files, path.name)
    regenerated = format_files(path.name, m, aux, aux_name(files))
    m2, aux2 = parse_files(regenerated, path.name)
    assert_same(m, m2)
    assert_same(aux, aux2)
    # formatting is stable and keeps the label lines of the original
    assert regenerate(regenerated, path.name) == regenerated
    original = [line.rstrip("\r") for line in files[path.name].splitlines()]
    for key, text in m.labels.items():
        for line in text.split("\n"):
            assert line in original


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_regenerated_files_give_identical_geometry(case_id, session_engine, original_runs):
    path = paths.INPUTS_DIR / case_id
    reference = original_runs(case_id)
    geo = session_engine.run(regenerate(case_files(path), path.name), path.name, derivatives=False)
    assert geo.sections.shape == reference.sections.shape
    assert np.max(np.abs(geo.sections - reference.sections)) == 0.0


def test_default_labels_give_identical_geometry(tct, session_engine, original_runs):
    files, m, aux = tct
    bare, bare_aux = copy.deepcopy(m), copy.deepcopy(aux)
    bare.labels, bare_aux.labels = {}, {}
    text = maininput.format(bare)
    assert_same(dataclasses.replace(maininput.parse(text), labels={}), bare)
    geo = run(session_engine, bare, bare_aux, files)
    ref = original_runs(str((TCT_DIR / TCT_MAIN).relative_to(paths.INPUTS_DIR)))
    assert np.max(np.abs(geo.sections - ref.sections)) == 0.0


# --------------------------------------------------------------------------------------------
# Values of the TCT rotor
# --------------------------------------------------------------------------------------------

def test_tct_values(tct):
    _, m, aux = tct
    assert (m.casename, m.row, m.n_blades, m.scale_factor, m.units) == ("Case7-28-8", 2, 16, 152.4, "mm")
    assert m.theta_offset is None
    assert m.n_streamlines == 21 and len(m.sections["chord"]) == 21 and len(m.airfoil_type) == 21
    assert (m.angle_switch, m.angle_spline) == (0, "inci_dev_spline")
    assert (m.curvature_control, m.spanwise_spline) == (1, True)
    assert (m.thickness_distribution, m.thickness_multiplier, m.le_spline) == (5, 0, 0)
    assert (m.chord_switch, m.true_lean_sweep) == (2, 0)
    assert (m.clustering_switch, m.clustering_parameter) == (4, 15.0)
    assert len(m.sweep) == 4 and m.sweep.values["delta_m"][0] == 0.019
    assert m.lean.values["delta_theta"][0] == 0.05125
    assert len(m.in_beta) == 8 and m.in_beta.values["in_beta*"][0] == 4.39458173439
    assert len(m.out_beta) == 7 and len(m.chord_multiplier) == 4
    assert list(m.thickness.values) == ["tm/c"]
    assert m.le_te.shape == (27, 4) and m.le_te[0, 0] == 0.00619
    assert m.grid_columns is not None and m.grid_columns.shape == (21, 3)
    assert m.stacking_axis == 55000 and m.airfoil_type[0] == "sect1"
    assert len(m.blending) == 4 and m.blending.values["bf1"].dtype.kind == "i"
    assert (m.hub_offset, m.hub_inflation_offset, m.tip_offset, m.tip_inflation_offset) == (0.0, 0.0, 0.0, None)
    assert m.streamlines[0].shape == (22, 2) and m.streamlines[0][0, 0] == -0.503602667

    assert isinstance(aux, SpanControl) and aux.naca
    assert (aux.casename, aux.row, aux.ncp_chord) == ("Case7-28-8", 2, 7)
    assert aux.curvature.columns == (["span"] + [f"u{k}" for k in range(2, 7)] + [f"cur{k}" for k in range(1, 8)])
    assert aux.curvature.data.shape == (8, 13)
    assert aux.thickness.columns == ["span", "LE_radius", "u_max", "t_max", "t_TE"]
    assert aux.thickness.data.shape == (5, 5) and aux.thickness_switch == 1
    assert aux.thickness.column("t_max")[0] == 0.12546


# --------------------------------------------------------------------------------------------
# Editing
# --------------------------------------------------------------------------------------------

def test_edit_sweep_value_changes_geometry(tct, session_engine, original_runs):
    files, m, aux = tct
    m = copy.deepcopy(m)
    m.sweep.values["delta_m"][1] = 0.01
    geo = run(session_engine, m, aux, files)
    ref = original_runs(str((TCT_DIR / TCT_MAIN).relative_to(paths.INPUTS_DIR)))
    assert np.max(np.abs(geo.sections - ref.sections)) > 1e-4


def test_add_sweep_control_point(tct, session_engine, original_runs):
    files, m, aux = tct
    m = copy.deepcopy(m)
    span, dm = m.sweep.span, m.sweep.values["delta_m"]
    s_new = 0.75
    v_new = float(np.interp(s_new, span, dm))
    k = int(np.searchsorted(span, s_new))
    m.sweep = ControlTable(np.insert(span, k, s_new), {"delta_m": np.insert(dm, k, v_new)})
    text = maininput.format(m)
    assert re.search(r"Control points for sweep:\n {11}5\n", text)
    assert len(maininput.parse(text).sweep) == 5
    geo = run(session_engine, m, aux, files)
    ref = original_runs(str((TCT_DIR / TCT_MAIN).relative_to(paths.INPUTS_DIR)))
    assert geo.sections.shape == ref.sections.shape
    assert np.isfinite(geo.sections).all()
    assert np.max(np.abs(geo.sections - ref.sections)) < 0.02      # similar blade (span ~0.7)


def test_add_streamline_point_and_le_te_point(tct):
    _, m, _ = tct
    m = copy.deepcopy(m)
    s = m.streamlines[3]
    m.streamlines[3] = np.vstack([s, [s[-1, 0] + 0.05, s[-1, 1]]])
    m.le_te = np.vstack([m.le_te, m.le_te[-1] + [0.001, 0.001, 0.0, 0.001]])
    m2 = maininput.parse(maininput.format(m))
    assert_same(m, m2)


def test_too_many_sweep_points_is_refused(tct):
    _, m, _ = tct
    m = copy.deepcopy(m)
    m.sweep = ControlTable(np.linspace(0, 1, 10), {"delta_m": np.zeros(10)})
    with pytest.raises(ValueError, match="0 to 9"):
        maininput.format(m)


def test_inconsistent_lengths_are_refused(tct):
    _, m, _ = tct
    m = copy.deepcopy(m)
    m.stk_u = m.stk_u[:-1]
    with pytest.raises(ValueError, match="stk_u"):
        maininput.format(m)


@pytest.mark.parametrize("units, label_units", [("mm", "mm"), ("cm", "cm"), ("m", "m)")])
def test_units(tct, units, label_units):
    _, m, _ = tct
    m = copy.deepcopy(m)
    m.units = units
    text = maininput.format(m)
    label = text.splitlines()[6]
    assert label[23:25] == label_units
    assert maininput.parse(text).units == units
    if units == "mm":
        assert label == m.labels["scale_factor"]          # original label kept when consistent


def test_shipped_units():
    assert {maininput.parse(p.read_text()).units for p in CASES} == {"mm"}


def test_bad_units_label(tct):
    files, _, _ = tct
    text = files[TCT_MAIN].replace("Blade Scaling factor (mm):", "Blade Scaling factor [in]:")
    with pytest.raises(InputFormatError, match="line 7"):
        maininput.parse(text)


# --------------------------------------------------------------------------------------------
# Variants no shipped case covers
# --------------------------------------------------------------------------------------------

def test_theta_offset(tct, session_engine, original_runs):
    files, m, aux = tct
    m = copy.deepcopy(m)
    m.theta_offset = 0.0
    text = maininput.format(m)
    assert text.splitlines()[7].split() == ["152.4", "0.0"]
    assert_same(maininput.parse(text), m)
    m.theta_offset = 0.125
    assert maininput.parse(maininput.format(m)).theta_offset == 0.125
    # T-Blade3 reads the two-number line; theta offset 0 is its default
    m.theta_offset = 0.0
    ref = original_runs(str((TCT_DIR / TCT_MAIN).relative_to(paths.INPUTS_DIR)))
    assert np.max(np.abs(run(session_engine, m, aux, files).sections - ref.sections)) == 0.0


def test_no_theta_offset_needs_nonblank_header_labels(tct):
    _, m, _ = tct
    m = copy.deepcopy(m)
    m.labels["title"] = ""
    m.labels["n_streamlines"] = " 3 streamlines follow"
    text = maininput.format(m)
    lines = text.splitlines()
    assert lines[0] == maininput.DEFAULT_LABELS["title"][0]
    assert lines[8] == maininput.DEFAULT_LABELS["n_streamlines"][0]
    assert maininput.parse(text).theta_offset is None
    m.theta_offset = 1.0                                  # then the labels can be anything
    lines = maininput.format(m).splitlines()
    assert lines[0] == "" and lines[8] == " 3 streamlines follow"


@pytest.mark.parametrize("switch", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("spline", maininput.ANGLE_SPLINES)
def test_angle_spline_variants(tct, switch, spline):
    _, m, _ = tct
    m = copy.deepcopy(m)
    m.angle_switch, m.angle_spline = switch, spline
    text = maininput.format(m)
    if switch == 4 and not spline:          # Fortran: wing switch needs a spline keyword
        with pytest.raises(InputFormatError, match="line 12"):
            maininput.parse(text)
        return
    assert_same(maininput.parse(text), m)


@pytest.mark.parametrize("line, switch, spline", [
    ("0", 0, ""), ("   2   ", 2, ""), ("\t1 inletspline", 1, "inletspline"), ("3  outletspline", 3, "outletspline"),
    ("4 inoutspline", 4, "inoutspline"), (" 0  inci_dev_spline ", 0, "inci_dev_spline")])
def test_angle_line_parsing(tct, line, switch, spline):
    files, _, _ = tct
    lines = files[TCT_MAIN].splitlines()
    lines[11] = line
    m = maininput.parse("\n".join(lines))
    assert (m.angle_switch, m.angle_spline) == (switch, spline)


@pytest.mark.parametrize("line", ["5", "0 1", "1 splinez", "2 inletspline outletspline"])
def test_bad_angle_line(tct, line):
    files, _, _ = tct
    lines = files[TCT_MAIN].splitlines()
    lines[11] = line
    with pytest.raises(InputFormatError, match="line 12"):
        maininput.parse("\n".join(lines))


@pytest.mark.parametrize("columns", [("tm/c",), ("u_max",), ("tm/c", "u_max"), ("u_max", "tm/c")])
def test_thickness_table_columns(tct, columns):
    _, m, _ = tct
    m = copy.deepcopy(m)
    span = np.array([0.0, 0.5, 1.0])
    m.thickness = ControlTable(span, {c: np.array([0.1, 0.2, 0.3]) * (k + 1) for k, c in enumerate(columns)})
    text = maininput.format(m)
    m2 = maininput.parse(text)
    assert list(m2.thickness.values) == list(columns)
    assert_same(dataclasses.replace(m2, labels={}), dataclasses.replace(m, labels={}))
    header = text.splitlines()[text.splitlines().index(" Control points for tm/c:") + 2]
    assert maininput._thickness_columns(header) == columns


def test_thickness_header_orders_parse(tct):
    files, _, _ = tct
    text = files[TCT_MAIN]
    block = ("           2\n        span     u_max    tm/c\n  0.0  0.3  0.1\n  1.0  0.4  0.2\n")
    old = re.search(r"(?<= Control points for tm/c:\n)(.*?)(?=\n\n Hub offset)", text, re.S).group(1)
    m = maininput.parse(text.replace(old + "\n", block))
    assert list(m.thickness.values) == ["u_max", "tm/c"]
    assert m.thickness.values["u_max"].tolist() == [0.3, 0.4] and m.thickness.values["tm/c"].tolist() == [0.1, 0.2]


@pytest.mark.parametrize("hub, tip", [(None, None), (0.01, None), (None, 0.02), (0.01, 0.02)])
def test_inflation_offsets(tct, hub, tip):
    _, m, _ = tct
    m = copy.deepcopy(m)
    m.hub_offset, m.tip_offset = 0.001, -0.002
    m.hub_inflation_offset, m.tip_inflation_offset = hub, tip
    assert_same(maininput.parse(maininput.format(m)), m)


def test_offset_line_quirks(tct):
    files, _, _ = tct
    lines = files[TCT_MAIN].splitlines()
    i = lines.index(" Hub offset") + 1
    lines[i] = "  0.5\t0.25  "                  # a TAB is not a blank for index(): no inflation offset
    lines[i + 2] = " 0.1  ignored  0.3"           # first and last blank-separated pieces
    m = maininput.parse("\n".join(lines))
    assert (m.hub_offset, m.hub_inflation_offset) == (0.5, None)
    assert (m.tip_offset, m.tip_inflation_offset) == (0.1, 0.3)


@pytest.mark.parametrize("grid", [True, False])
def test_grid_columns(tct, grid):
    _, m, _ = tct
    m = copy.deepcopy(m)
    if not grid:
        m.grid_columns = None
    else:
        m.grid_columns = np.tile([13.0, 8.5, 1.0], (m.n_streamlines, 1))
    text = maininput.format(m)
    header = next(line for line in text.splitlines() if "stk_u" in line)
    assert ("Jcells" in header) == grid
    assert_same(dataclasses.replace(maininput.parse(text), labels={}), dataclasses.replace(m, labels={}))


def test_camber_and_thickness_line_variants(tct):
    files, m, _ = tct
    lines = files[TCT_MAIN].splitlines()
    # "0" alone: the next label must start with 'Airfoil'
    lines_a = list(lines)
    lines_a[13] = "           0"
    ma = maininput.parse("\n".join(lines_a))
    assert (ma.curvature_control, ma.spanwise_spline) == (0, False)
    assert ma.labels["thickness_distribution"] == lines[14]
    lines_b = list(lines_a)
    lines_b[14] = " Thickness distribution:"
    with pytest.raises(InputFormatError, match="line 15"):
        maininput.parse("\n".join(lines_b))
    # format repairs a label that does not start with 'Airfoil'
    ma.labels["thickness_distribution"] = " Thickness distribution:"
    assert maininput.format(ma).splitlines()[14] == maininput.DEFAULT_LABELS["thickness_distribution"][0]
    # "0 Airfoil" on one line: no thickness label follows
    lines_c = lines[:13] + ["  0  Airfoil"] + lines[15:]
    mc = maininput.parse("\n".join(lines_c))
    assert (mc.curvature_control, mc.spanwise_spline, mc.thickness_distribution) == (0, False, 5)
    # A second token on the thickness line: the multiplier label must be absent
    lines_d = lines[:15] + ["           5  NACA"] + lines[17:]
    md = maininput.parse("\n".join(lines_d))
    assert (md.thickness_distribution, md.thickness_multiplier) == (5, 0)
    assert "thickness_multiplier" not in md.labels
    for variant in (mc, md):
        assert_same(dataclasses.replace(variant, labels={}), dataclasses.replace(m, labels={},
                    curvature_control=variant.curvature_control, spanwise_spline=variant.spanwise_spline))


def test_list_directed_reads_skip_blank_lines(tct):
    files, m, _ = tct
    lines = files[TCT_MAIN].splitlines()
    i = lines.index(" Control points for in_beta*:")
    lines.insert(i + 1, "")                          # blank line before a list-directed count
    lines[i + 4] = lines[i + 4].replace("        ", " ,  ", 1)
    m2 = maininput.parse("\n".join(lines))
    assert_same(m2.in_beta, m.in_beta)


def test_sweep_count_column_12(tct):
    files, m, _ = tct
    lines = files[TCT_MAIN].splitlines()
    i = lines.index(" Control points for sweep:") + 1
    lines[i] = "4"
    with pytest.raises(InputFormatError, match=f"line {i + 1}.*column 12"):
        maininput.parse("\n".join(lines))
    lines[i] = "           4   (count)"
    assert len(maininput.parse("\n".join(lines)).sweep) == 4


def test_streamline_header_search(tct):
    files, m, _ = tct
    text = files[TCT_MAIN].replace("  Streamline Data\n", "  Streamline Data\n comment\n\n")
    m2 = maininput.parse(text)
    assert_same(m2.streamlines, m.streamlines)
    assert m2.labels["streamlines"].split("\n")[2:] == [" comment", "", "        x_s                     r_s"]
    # a stored block without an x_s line is replaced by the default
    m2.labels["streamlines"] = "\n  Streamline Data\n x r"
    assert "        x_s" in maininput.format(m2)
    assert_same(maininput.parse(maininput.format(m2)).streamlines, m.streamlines)


def test_parse_errors_name_the_line(tct):
    files, _, _ = tct
    lines = files[TCT_MAIN].splitlines()
    with pytest.raises(InputFormatError, match="end of file"):
        maininput.parse("\n".join(lines[:300]))
    bad = list(lines)
    bad[5] = "  sixteen"
    with pytest.raises(InputFormatError, match="line 6.*number of blades"):
        maininput.parse("\n".join(bad))
    bad = list(lines)
    bad[30] = " 3  abc  1 2 3 4 5 6 7 8"
    with pytest.raises(InputFormatError, match="line 31.*sectionwise"):
        maininput.parse("\n".join(bad))


def test_crlf_input(tct):
    files, m, _ = tct
    assert_same(maininput.parse(files[TCT_MAIN].replace("\n", "\r\n")), m)


# --------------------------------------------------------------------------------------------
# Auxiliary files
# --------------------------------------------------------------------------------------------

def test_spancontrol_edits(tct):
    _, m, aux = tct
    aux = copy.deepcopy(aux)
    # one more chordwise curvature point: ncp_chord comes from the columns
    ncp = aux.ncp_chord + 1
    data = aux.curvature.data
    u = np.column_stack([data[:, 1:ncp - 2], np.full(len(data), 0.97)])
    cur = np.column_stack([data[:, ncp - 2:], data[:, -1]])
    aux.curvature = spancontrol.Table(spancontrol.curvature_columns(ncp), np.column_stack([data[:, :1], u, cur]))
    # TE derivative column added: header must name it
    t = aux.thickness
    aux.thickness = spancontrol.Table(t.columns + ["dy_dx_norm"], np.column_stack([t.data, np.ones(len(t.data))]))
    text = spancontrol.format_spancontrol(aux)
    assert "dy_dx_norm" in text and "        8   8" in text
    aux2 = spancontrol.parse_spancontrol(text, 5)
    assert aux2.ncp_chord == ncp
    aux.ncp_chord = ncp
    assert_same(dataclasses.replace(aux2, labels={}), dataclasses.replace(aux, labels={}))


def test_spancontrol_without_cur1_and_spline_thickness():
    aux = SpanControl(casename="demo", row=3, ncp_chord=5,
                      curvature=spancontrol.Table(spancontrol.curvature_columns(5, cur1=False),
                                                  np.arange(16, dtype=float).reshape(2, 8) / 10),
                      thickness=spancontrol.Table(["span", "thk1", "thk2", "thk3"],
                                                  np.arange(8, dtype=float).reshape(2, 4) / 7),
                      thickness_switch=4, trailing_text="\nLE control block\n 1 2 3")
    text = spancontrol.format_spancontrol(aux)
    assert "cur1" not in text and "cur2" in text
    back = spancontrol.parse_spancontrol(text, 1, thickness_multiplier=1)
    assert_same(dataclasses.replace(back, labels={}), aux)
    with pytest.raises(InputFormatError, match="cur1"):
        spancontrol.parse_spancontrol(text, 5)
    # thickness multiplier off: T-Blade3 does not read the thickness block, kept as text
    skipped = spancontrol.parse_spancontrol(text, 1)
    assert skipped.thickness is None and "thk1" in skipped.trailing_text
    assert spancontrol.format_spancontrol(skipped) == text


def test_spancontrol_guess_without_switches(tct):
    files, _, aux = tct
    guessed = spancontrol.parse_spancontrol(files["spancontrolinputs.2.dat"])
    assert_same(guessed, aux)


def test_controlinputs_round_trip():
    rng = np.random.default_rng(1)
    aux = ControlInputs(casename="oldcase",
                        curvature=[rng.random((n, 2)) for n in (3, 4, 5)],
                        thickness=[rng.random((n, 2)) for n in (6, 2, 3)])
    text = spancontrol.format_controlinputs(aux)
    back = spancontrol.parse_controlinputs(text, 3)
    assert_same(dataclasses.replace(back, labels={}), aux)
    assert spancontrol.format_controlinputs(back) == text
    with pytest.raises(InputFormatError):
        spancontrol.parse_controlinputs(text, 4)
