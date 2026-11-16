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


def _window(qtbot, folder):
    from tblade3.gui.main_window import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.open_case(folder)
    c = window.controller
    qtbot.waitUntil(lambda: all(c.row(r).geometry is not None for r in c.case.rows), timeout=BUILD)
    qtbot.wait(100)
    return window


def _tab(window, title):
    tab = next(t for t in window.tab_widgets if t.title == title)
    window.tabs.setCurrentWidget(tab)
    return tab


def test_sensitivities_tab(qtbot, case_dir):
    window = _window(qtbot, case_dir)
    c, view = window.controller, window.view
    tab = _tab(window, "Sensitivities")
    qtbot.wait(50)
    tab.select("naca.t_max[3]")                                         # analytic: shown at once
    assert view._scalar["2"] is not None and "naca.t_max[3]" in view._scalar["2"][1]
    assert view._scalar["2"][0].shape == view._surfaces["2"][0].points.shape[:2]
    assert "Analytic" in tab.method_label.text() and "section" in tab.peak_label.text()
    assert not tab.throat_plot.isHidden()
    normal = view._scalar["2"][0].copy()
    tab.component_box.setCurrentIndex(tab.component_box.findData("x"))
    assert not np.array_equal(view._scalar["2"][0], normal)

    with qtbot.waitSignal(c.sensitivityReady, timeout=BUILD):
        tab.select("hub_offset")                                        # finite difference in the background
    assert "finite difference" in tab.method_label.text().lower()
    assert "hub_offset" in view._scalar["2"][1] and tab.throat_plot.isHidden()

    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):              # an edit: the contour follows the new blade
        c.set_value("2", "sweep[4]", 0.03)
    with qtbot.waitSignal(c.sensitivityReady, timeout=BUILD):
        pass
    assert "hub_offset" in view._scalar["2"][1]

    tab.picker.filter_edit.setText("cur3")
    assert tab.picker._items["sweep[1]"].isHidden() and not tab.picker._items["cur3[4]"].isHidden()
    window.tabs.setCurrentIndex(0)                                      # leaving the tab removes the contour
    assert view._scalar["2"] is None
    c.undo_stack.setClean()
    window.close()


def test_design_variables_tab(qtbot, case_dir, tmp_path):
    window = _window(qtbot, case_dir)
    c = window.controller
    tab = _tab(window, "Design variables")
    qtbot.wait(50)
    assert tab.table.rowCount() == 0
    from PySide6.QtCore import Qt
    tab.picker._items["sweep[4]"].setCheckState(0, Qt.Checked)          # tick in the tree
    tab.picker._items["hub_offset"].setCheckState(0, Qt.Checked)
    assert c.case.dv.names == ["row2.hub_offset", "row2.sweep[4]"] and tab.table.rowCount() == 2
    assert tab.table.item(1, 0).text() == "row2.sweep[4]" and tab.table.item(1, 4).text() == "analytic"
    assert tab.table.item(1, 5).text() == "span_del_m[4]" and tab.table.item(0, 4).text() == "finite difference"
    tab.table.item(1, 2).setText("-0.05")                               # bounds
    tab.table.item(1, 3).setText("0.05")
    assert c.case.dv.bounds[1] == (-0.05, 0.05)
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        tab.table.item(1, 1).setText("0.02")                            # value
    assert c.row("2").get("sweep[4]") == 0.02
    assert not c.undo_stack.isClean()

    tab.export_values(tmp_path / "dv.txt")
    assert list(np.loadtxt(tmp_path / "dv.txt", ndmin=1)) == [0.0, 0.02]
    out = tmp_path / "esp" / "rotor.csm"
    out.parent.mkdir()
    tab.export_csm(out)
    text = out.read_text()
    assert "DESPMTR   span_del_m" in text and "DESPMTR   offsets" in text and (out.parent / TCT_MAIN).is_file()
    assert c.case.folder == case_dir                                    # exporting does not move the case

    c.undo_stack.undo()                                                 # value
    c.undo_stack.undo()                                                 # upper bound
    assert c.case.dv.bounds[1] == (-0.05, None) and tab.table.item(1, 3).text() == ""
    tab.table.selectRow(0)
    tab.remove_button.click()
    assert c.case.dv.names == ["row2.sweep[4]"]
    assert tab.picker._items["hub_offset"].checkState(0) == Qt.Unchecked
    c.undo_stack.undo()
    assert len(c.case.dv) == 2 and tab.picker._items["hub_offset"].checkState(0) == Qt.Checked

    c.save()                                                            # flags are saved with the case
    from tblade3.model import Case
    with Case.load(case_dir, engine="executable") as again:
        assert again.dv.names == ["row2.hub_offset", "row2.sweep[4]"] and again.dv.bounds[1] == (-0.05, None)
    window.close()
