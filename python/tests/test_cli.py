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
    return Path(os.environ.get("ESP_ROOT", Path.home() / "opt/ESP129/EngSketchPad"))


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
