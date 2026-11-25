"""The command line and the .csm export."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tblade3 import paths
from tblade3.cli import main
from tblade3.io.csm import csm_text
from tblade3.model import Case

from conftest import TCT_DIR, TCT_MAIN


@pytest.fixture
def case_dir(tmp_path):
    try:
        paths.library()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    for name in (TCT_MAIN, "spancontrolinputs.2.dat"):
        shutil.copy(TCT_DIR / name, tmp_path / name)
    return tmp_path


def test_params_lists_names(case_dir, capsys):
    assert main(["params", str(case_dir), "--filter", "sweep"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 8 and out[0].startswith("row2.sweep[1]") and "analytic" in out[0]


def test_run_writes_geometry_and_derivatives(case_dir, capsys):
    out = case_dir / "geo.npz"
    saved = case_dir / "modified"
    code = main(["run", str(case_dir), "--set", "row2.sweep[4]=0.01", "--derivs", "--wrt", "row2.sweep[4]",
                 "row2.hub_offset", "--out", str(out), "--save-inputs", str(saved)])
    assert code == 0, capsys.readouterr().err
    data = np.load(out)
    assert data["row2_sections"].shape == (21, 241, 3)
    assert data["row2_jacobian"].shape == (21, 241, 3, 2)
    assert list(data["dv_names"]) == ["row2.sweep[4]", "row2.hub_offset"]
    assert list(data["dv_methods"]) == ["analytic", "fd"]
    assert data["dv_values"][0] == 0.01
    with Case.load(saved) as again:
        assert again.get("row2.sweep[4]") == 0.01
        assert np.array_equal(again.build(derivatives=False)["2"].sections, data["row2_sections"])


def test_run_with_a_design_variable_file(case_dir, capsys):
    with Case.load(case_dir) as case:
        case.dv.add("row2.sweep[4]")
        case.dv.add("row2.lean[1]")
        case.save()
    (case_dir / "x.txt").write_text("0.02\n0.04\n")
    out = case_dir / "geo.npz"
    assert main(["run", str(case_dir), "--dv-file", str(case_dir / "x.txt"), "--derivs", "--out", str(out)]) == 0
    data = np.load(out)
    assert list(data["dv_names"]) == ["row2.sweep[4]", "row2.lean[1]"]
    assert list(data["dv_values"]) == [0.02, 0.04]


def test_errors_give_exit_code_1(case_dir, capsys):
    assert main(["run", str(case_dir), "--set", "row2.nothing=1"]) == 1
    assert "nothing" in capsys.readouterr().err
    assert main(["run", str(case_dir), "--set", "row2.naca.t_te[5]=-0.5"]) == 1
    assert "thickness" in capsys.readouterr().err
    assert main(["run", str(case_dir / "missing")]) == 1


def test_csm_text(case_dir):
    with Case.load(case_dir) as case:
        assert "DESPMTR" not in csm_text(case)
        case.dv.add("row2.sweep[4]")
        case.dv.add("row2.naca.t_max[3]")
        text = csm_text(case)
        lines = text.splitlines()
        assert "DIMENSION span_del_m             1 4" in lines
        assert "DIMENSION naca_t_max             1 5" in lines
        despmtr = [ln for ln in lines if ln.startswith("DESPMTR")]
        assert len(despmtr) == 2
        values = [float(v) for v in despmtr[0].split('"')[1].replace(";", " ").split()]
        assert values == [case.get(f"row2.sweep[{i}]") for i in range(1, 5)]
        assert "$$/3dbgbinput.2.dat" in text and "$$/spancontrolinputs.2.dat" in text
        assert text.rstrip().endswith("END")
        everything = csm_text(case, all_parameters=True)
        for arg in ("cur1", "cur7", "u2", "span_del_theta", "span_in_beta", "span_chord", "naca_le_radius",
                    "span_curv_ctrl", "span_thk_ctrl", "offsets"):
            assert f"UDPARG    tblade    {arg:<22} {arg}" in everything


def test_export_csm_command(case_dir, tmp_path_factory, capsys):
    out = tmp_path_factory.mktemp("csm") / "rotor.csm"
    assert main(["export-csm", str(case_dir), "--out", str(out), "--dv", "row2.lean[1]"]) == 0
    assert out.is_file() and "span_del_theta" in out.read_text()
    assert (out.parent / TCT_MAIN).is_file() and (out.parent / "spancontrolinputs.2.dat").is_file()
    assert (out.parent / "case.tb3.yaml").is_file()


def _esp_root() -> Path:
    """ESP_ROOT if set, otherwise an ESP installed beside this repository (../ESP129)."""
    beside = Path(__file__).resolve().parents[3] / "ESP129" / "EngSketchPad"
    return Path(os.environ.get("ESP_ROOT", beside))


@pytest.mark.skipif(not (_esp_root() / "ESPenv.sh").is_file() or not (_esp_root() / "lib" / "tblade.so").is_file(),
                    reason="ESP with the T-Blade3 UDP is not installed")
def test_exported_csm_builds_the_same_blade_in_esp(case_dir):
    """ESP builds the same body from the input files alone and with every udpTblade argument exported.

    This checks that each exported argument carries the values T-Blade3 reads from the files.
    """
    from tblade3.io.csm import export_csm
    with Case.load(case_dir) as case:
        export_csm(case, case_dir / "plain.csm")
        export_csm(case, case_dir / "all.csm", all_parameters=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CONDA")}
    env["PATH"] = ":".join(p for p in env.get("PATH", "").split(":") if "miniforge" not in p and "conda" not in p)
    props = {}
    for name in ("plain", "all"):
        path = case_dir / f"{name}.csm"
        text = path.read_text()
        assert ("DESPMTR" in text) == (name == "all")
        probe = f"MESSAGE   !val2str(@volume,12)+$_+val2str(@area,12)+$_+val2str(@xcg,12)+$_+val2str(@ycg,12) _ props_{name}.txt"
        path.write_text(text.replace("\nEND", "\n" + probe + "\nEND"))
        proc = subprocess.run(["bash", "-c", f"source {_esp_root()}/ESPenv.sh >/dev/null && serveESP {name}.csm -batch"],
                              cwd=case_dir, env=env, capture_output=True, text=True, timeout=600)
        log = proc.stdout + proc.stderr
        assert proc.returncode == 0, log[-3000:]
        props[name] = np.array((case_dir / f"props_{name}.txt").read_text().split(), dtype=float)
    assert props["plain"][0] > 1000.0                   # a solid blade, mm^3
    assert np.allclose(props["all"], props["plain"], rtol=1e-9, atol=1e-9), props


def test_csm_hubwedge_text(case_dir):
    with Case.load(case_dir) as case:
        assert "hubwedge" not in csm_text(case) and "SUBTRACT" not in csm_text(case)
        text = csm_text(case, hubwedge=True, bore_radius=15.0, dump_step="rotor.step")
    lines = [ln.split() for ln in text.splitlines() if ln.strip()]
    firsts = [ln[0] for ln in lines]
    assert firsts.count("UDPRIM") == 2 and "UNION" in firsts and "SUBTRACT" in firsts
    assert ["UDPRIM", "hubwedge", "filename", "$$/3dbgbinput.2.dat", "\\"] in lines
    assert ["CYLINDER", "-100", "0", "0", "1000", "0", "0", "15"] in lines
    assert ["DUMP", "$$/rotor.step"] in lines
    assert firsts.index("UDPRIM") < firsts.index("UNION") < firsts.index("CYLINDER") < firsts.index("SUBTRACT")
    assert "revolved hub-section meanline" in text and "tblade3.brep" in text
    assert text.rstrip().endswith("END") and "ncp" in text


def test_export_csm_hubwedge_command(case_dir, capsys):
    out = case_dir / "wedge.csm"
    assert main(["export-csm", str(case_dir), "--out", str(out), "--hubwedge", "--dump-step", "w.step"]) == 0
    text = out.read_text()
    assert "UDPRIM    hubwedge" in text and "CYLINDER  -100 0 0 1000 0 0 12.7" in text and "DUMP      $$/w.step" in text


@pytest.mark.skipif(not (_esp_root() / "ESPenv.sh").is_file() or not (_esp_root() / "lib" / "hubwedge.so").is_file(),
                    reason="ESP with the hubwedge UDP is not installed")
def test_hubwedge_csm_builds_one_body_in_esp(case_dir):
    from tblade3.io.csm import export_csm
    with Case.load(case_dir) as case:
        export_csm(case, case_dir / "wedge.csm", hubwedge=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CONDA")}
    env["PATH"] = ":".join(p for p in env.get("PATH", "").split(":") if "miniforge" not in p and "conda" not in p)
    path = case_dir / "wedge.csm"
    proc = subprocess.run(["bash", "-c", f"source {_esp_root()}/ESPenv.sh >/dev/null && serveESP wedge.csm -batch"],
                          cwd=case_dir, env=env, capture_output=True, text=True, timeout=600)
    log = proc.stdout + proc.stderr
    assert proc.returncode == 0, log[-3000:]
    table = log.split("Mass properties of Bodys on stack")[1].split("Output Parameters")[0].splitlines()[2:]
    rows = [ln.split() for ln in table if ln.strip()]
    assert len(rows) == 1 and float(rows[0][1]) > 0.0       # one body on the stack, positive volume


def test_export_command(case_dir, tmp_path, capsys):
    pytest.importorskip("OCP")
    out = tmp_path / "out"
    code = main(["export", str(case_dir), "-o", str(out), "--bodies", "blade", "solid", "--formats", "step", "brep"])
    text = capsys.readouterr().out
    assert code == 0, text
    assert (out / "Case7-28-8.step").is_file() or len(list(out.glob("*.step"))) == 1
    step = next(out.glob("*.step"))
    assert sorted(p.name for p in out.glob("*.brep")) == [f"{step.stem}_blade.brep", f"{step.stem}_solid.brep"]
    assert "wrote" in text and "row 2" in text


def test_export_command_hgeom_and_sensitivities(case_dir, tmp_path, capsys):
    pytest.importorskip("OCP")
    from tblade3.brep import hgeom
    out = tmp_path / "out"
    assert main(["export", str(case_dir), "-o", str(out), "--bodies", "blade", "--formats", "hgeom",
                 "--sens", "row2.sweep[4]"]) == 0
    files = list(out.glob("*.hgeom"))
    assert len(files) == 1
    assert "blade" in hgeom.read(files[0]).bodies


def test_export_command_errors(case_dir, tmp_path, capsys):
    pytest.importorskip("OCP")
    assert main(["export", str(case_dir), "-o", str(tmp_path), "--row", "9"]) == 1
    assert "no row" in capsys.readouterr().err
    assert main(["export", str(case_dir), "-o", str(tmp_path / "o"), "--bore-radius", "1e6", "--formats", "brep"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and "Traceback" not in err
    assert main(["export", str(case_dir / "missing"), "-o", str(tmp_path)]) == 1
