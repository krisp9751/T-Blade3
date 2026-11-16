"""The GUI: controller logic (edits, undo, background builds) and a main-window smoke test.

Runs without a display (QT_QPA_PLATFORM=offscreen); the 3D view then renders off screen.
"""
from __future__ import annotations

import os
import shutil

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from tblade3 import paths                              # noqa: E402
from tblade3.gui.controller import Controller          # noqa: E402

from conftest import TCT_DIR, TCT_MAIN                 # noqa: E402

CASE7 = paths.INPUTS_DIR / "OpenCSM" / "Case7-28-8"
BUILD = 30000                                          # ms, generous: one build takes about a second


@pytest.fixture
def case_dir(tmp_path):
    try:
        paths.library()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    for name in (TCT_MAIN, "spancontrolinputs.2.dat"):
        shutil.copy(TCT_DIR / name, tmp_path / name)
    return tmp_path


@pytest.fixture
def controller(qtbot, case_dir):
    c = Controller()
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        c.load(case_dir)
    yield c
    c.shutdown()


def test_load_builds_every_row(controller):
    row = controller.row("2")
    assert row.geometry is not None and row.is_current and row.geometry.derivatives is not None
    assert not controller.is_building("2") and controller.error("2") == ""
    assert controller.undo_stack.isClean()


def test_edit_rebuilds_and_undo_restores(qtbot, controller):
    row = controller.row("2")
    before = row.geometry.sections.copy()
    with qtbot.waitSignal(controller.buildFinished, timeout=BUILD), qtbot.waitSignal(controller.inputsChanged):
        controller.set_value("2", "sweep[4]", 0.05)
    assert row.get("sweep[4]") == 0.05 and not controller.undo_stack.isClean()
    assert np.abs(row.geometry.sections - before).max() > 0.1
    with qtbot.waitSignal(controller.buildFinished, timeout=BUILD):
        controller.undo_stack.undo()
    assert row.get("sweep[4]") == 0.0 and np.array_equal(row.geometry.sections, before)
    with qtbot.waitSignal(controller.buildFinished, timeout=BUILD):
        controller.undo_stack.redo()
    assert row.get("sweep[4]") == 0.05


def test_setting_the_same_value_is_not_an_edit(controller):
    controller.set_value("2", "sweep[4]", controller.row("2").get("sweep[4]"))
    assert controller.undo_stack.count() == 0


def test_a_drag_is_one_undo_step(qtbot, controller):
    row = controller.row("2")
    x0, r0 = row.get("le_te.x_le[3]"), row.get("le_te.r_le[3]")
    controller.auto_run = False
    controller.begin_drag()
    for k in range(1, 6):
        controller.set_values("2", {"le_te.x_le[3]": x0 + 0.001 * k, "le_te.r_le[3]": r0 + 0.002 * k}, drag=True)
    assert controller.undo_stack.count() == 1
    controller.begin_drag()
    controller.set_values("2", {"le_te.x_le[3]": x0 + 0.02}, drag=True)
    assert controller.undo_stack.count() == 2
    controller.undo_stack.undo()
    controller.undo_stack.undo()
    assert (row.get("le_te.x_le[3]"), row.get("le_te.r_le[3]")) == (x0, r0)


def test_failed_build_keeps_the_last_geometry(qtbot, controller):
    row = controller.row("2")
    good = row.geometry
    with qtbot.waitSignal(controller.buildFailed, timeout=BUILD) as blocker:
        controller.set_value("2", "naca.t_te[5]", -0.5)
    assert blocker.args[0] == "2" and "thickness" in blocker.args[1]
    assert row.geometry is good and controller.error("2")
    with qtbot.waitSignal(controller.buildFinished, timeout=BUILD):
        controller.undo_stack.undo()
    assert controller.error("2") == "" and row.is_current


def test_run_on_edit_off_waits_for_run(qtbot, controller):
    controller.auto_run = False
    controller.set_value("2", "lean[1]", 0.06)
    qtbot.wait(600)
    assert not controller.row("2").is_current and not controller.is_building("2")
    with qtbot.waitSignal(controller.buildFinished, timeout=BUILD):
        controller.build_all()
    assert controller.row("2").is_current


def test_structural_edit_is_undoable(qtbot, controller):
    row = controller.row("2")
    main = row.main
    assert main.n_blades == 16
    with qtbot.waitSignal(controller.buildFinished, timeout=BUILD):
        controller.set_attribute("2", main, "n_blades", 18)
    assert row.get("n_blades") == 18
    controller.undo_stack.undo()
    assert row.get("n_blades") == 16


def test_sensitivities(qtbot, controller):
    with qtbot.waitSignal(controller.sensitivityReady, timeout=BUILD) as blocker:
        controller.request_sensitivity("2", "sweep[4]")                # analytic: available at once
    assert blocker.args == ["2", "sweep[4]"]
    with qtbot.waitSignal(controller.sensitivityReady, timeout=BUILD):
        controller.request_sensitivity("2", "hub_offset")              # two background runs
    row = controller.row("2")
    assert np.abs(row.dxyz("hub_offset")).max() > 1.0
    with qtbot.waitSignal(controller.sensitivityFailed, timeout=BUILD):
        controller.request_sensitivity("2", "n_blades")


def test_save_marks_clean(qtbot, controller, tmp_path):
    with qtbot.waitSignal(controller.buildFinished, timeout=BUILD):
        controller.set_value("2", "sweep[4]", 0.01)
    out = tmp_path / "out"
    controller.save(out)
    assert controller.undo_stack.isClean() and (out / TCT_MAIN).is_file()
    from tblade3.model import Case
    with Case.load(out, engine="executable") as again:
        assert again.get("row2.sweep[4]") == 0.01


def test_main_window(qtbot, tmp_path):
    """Open a three-row case in the main window: rows listed, geometry in the 3D view, row selection, edit."""
    pytest.importorskip("pyvistaqt")
    try:
        paths.library()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    for sub in ("IGV", "Rotor", "OGV"):
        for path in (CASE7 / sub).glob("*input*.dat"):
            shutil.copy(path, tmp_path / path.name)
    from tblade3.gui.main_window import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    c = window.controller
    assert window.open_case(tmp_path)
    qtbot.waitUntil(lambda: all(c.row(r).geometry is not None for r in c.case.rows), timeout=BUILD)
    qtbot.wait(100)
    assert window.row_list.count() == 3 and window.current_row == "1"
    assert set(window.view._surfaces) == {"1", "2", "3"}
    assert window.tabs.count() >= 1
    assert "up to date" in window.status.text() and "failed" not in window.status.text()
    window.row_list.setCurrentRow(1)
    assert window.current_row == "2" and all(tab.row_id == "2" for tab in window.tab_widgets)
    for i in range(window.tabs.count()):                 # every tab can be shown
        window.tabs.setCurrentIndex(i)
        qtbot.wait(50)
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        c.set_value("2", "sweep[4]", 0.05)
    assert window.windowTitle().endswith("*")
    window.all_blades_action.trigger()
    assert window.view._surfaces["2"][0].copies == 16
    c.undo_stack.undo()
    c.undo_stack.setClean()
    window.close()
