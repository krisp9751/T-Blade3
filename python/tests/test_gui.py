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

from PySide6.QtCore import Qt                          # noqa: E402

from tblade3 import paths                              # noqa: E402
from tblade3.gui.controller import Controller          # noqa: E402

from conftest import TCT_DIR, TCT_MAIN                 # noqa: E402

CASE7 = paths.INPUTS_DIR / "OpenCSM" / "Case7-28-8"
BUILD = 30000                                          # ms, generous: one build takes about a second


@pytest.fixture(autouse=True)
def _no_discard_question(monkeypatch):
    """A test that fails with unsaved edits must not hang on the modal 'discard changes?' question at teardown."""
    from tblade3.gui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "_confirm_discard", lambda self: True)


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


def test_spanwise_tab(qtbot, case_dir):
    window = _window(qtbot, case_dir)
    c = window.controller
    row = c.row("2")
    tab = _tab(window, "Spanwise controls")
    qtbot.wait(50)
    assert tab.table.table.rowCount() == 4 and tab.points._pos.shape == (4, 2)       # sweep
    assert "built" in tab.plot.names() and tab.built_plot.isHidden()
    built = row.geometry.sections.copy()

    c.begin_drag()                                                                    # drag point 4 in two moves
    tab._point_dragged(3, 0.01, 1.0)
    tab._point_dragged(3, 0.02, 1.0)
    assert row.get("sweep[4]") == 0.02 and c.undo_stack.count() == 1
    assert tab.points._pos[3, 0] == 0.02
    qtbot.waitUntil(lambda: row.is_current and not c.is_building("2"), timeout=BUILD)
    assert np.abs(row.geometry.sections - built).max() > 0.1

    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        tab._add_point(1)                                                             # between points 2 and 3
    assert len(row.main.sweep) == 5 and row.get("sweep.span[3]") == pytest.approx(0.375)
    assert tab.table.table.rowCount() == 5 and "sweep[5]" in row.parameters
    tab._remove_point(2)
    assert len(row.main.sweep) == 4 and "sweep[5]" not in row.parameters
    c.undo_stack.undo()
    c.undo_stack.undo()
    assert len(row.main.sweep) == 4 and row.get("sweep[4]") == 0.02
    c.undo_stack.undo()
    assert row.get("sweep[4]") == 0.0
    qtbot.waitUntil(lambda: row.is_current and not c.is_building("2"), timeout=BUILD)
    assert np.array_equal(row.geometry.sections, built)

    tab.control_list.setCurrentRow(2)                                                 # inlet angle: separate result plot
    assert tab.table.table.rowCount() == 8 and not tab.built_plot.isHidden()
    assert "built" not in tab.plot.names()
    tab.control_list.setCurrentRow(6)                                                 # u_max: not in this case's file
    assert not tab.table.isEnabled() and tab.points._pos.shape == (0, 2)
    c.undo_stack.setClean()
    window.close()


WENNERSTROM = paths.INPUTS_DIR / "OpenCSM" / "Wennerstrom_with_umxthk"


def _wennerstrom(tmp_path, aux=True):
    folder = tmp_path / "wennerstrom"
    folder.mkdir()
    for path in WENNERSTROM.glob("*input*.dat"):
        if aux or not path.name.startswith("spancontrol"):
            shutil.copy(path, folder / path.name)
    return folder


def _settled(qtbot, c, rid):
    qtbot.waitUntil(lambda: c.row(rid).is_current and not c.is_building(rid), timeout=BUILD)


def test_row_setup_tab(qtbot, case_dir):
    window = _window(qtbot, case_dir)
    c = window.controller
    row = c.row("2")
    tab = _tab(window, "Row setup")
    qtbot.wait(50)
    assert tab.casename_edit.text() == "Case7-28-8" and tab.blades_edit.text() == "16"
    assert tab.boxes["thickness_distribution"].currentData() == 5 and tab.boxes["clustering_switch"].currentData() == 4
    assert not tab.boxes["le_spline"].isEnabled() and "spancontrolinputs.2.dat" in tab.aux_note.text()
    pitch = row.geometry.section_table["pitch"].copy()

    tab.blades_edit.setText("18")                                          # blade count
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        tab.blades_edit.editingFinished.emit()
    assert row.main.n_blades == 18 and not np.allclose(row.geometry.section_table["pitch"], pitch)
    c.undo_stack.undo()
    assert row.main.n_blades == 16 and tab.blades_edit.text() == "16"
    _settled(qtbot, c, "2")
    built = row.geometry.sections.copy()

    box = tab.boxes["clustering_switch"]                                   # a switch that rebuilds
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        box.setCurrentIndex(box.findData(3))
    assert row.main.clustering_switch == 3 and c.error("2") == ""
    assert np.abs(row.geometry.sections - built).max() > 1e-3
    count = c.undo_stack.count()

    box = tab.boxes["thickness_distribution"]                              # with hyperbolic clustering the
    box.setCurrentIndex(box.findData(0))                                   # Wennerstrom thickness is accepted
    assert row.main.thickness_distribution == 0 and c.undo_stack.count() == count + 1
    assert row.aux.thickness is None and "naca.t_max[1]" not in row.parameters      # NACA block now not read
    c.undo_stack.undo()
    assert row.aux.naca and "naca.t_max[1]" in row.parameters
    c.undo_stack.undo()                                                    # back to elliptical clustering
    assert row.main.clustering_switch == 4
    count = c.undo_stack.count()
    with qtbot.waitSignal(c.message) as blocker:                           # but not with elliptical clustering
        box.setCurrentIndex(box.findData(0))
    assert "elliptical" in blocker.args[0].lower() and row.main.thickness_distribution == 5
    assert box.currentData() == 5 and c.undo_stack.count() == count
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):                 # variable stacking starts from the axis
        tab.boxes["variable_stacking"].setCurrentIndex(1)
    assert row.main.variable_stacking == 1 and np.all(row.main.stk_u == 55.0) and np.all(row.main.stk_v == 0.0)
    assert np.array_equal(row.geometry.sections, built)
    c.undo_stack.undo()
    assert row.main.variable_stacking == 0 and np.all(row.main.stk_u == 25.0)
    _settled(qtbot, c, "2")
    assert np.array_equal(row.geometry.sections, built)
    c.undo_stack.setClean()
    window.close()


def test_row_setup_default_data(qtbot, tmp_path):
    """A switch that needs data the case lacks: the data is created in the same undoable edit."""
    try:
        paths.library()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    window = _window(qtbot, _wennerstrom(tmp_path, aux=False))
    c = window.controller
    row = c.row("1")
    tab = _tab(window, "Row setup")
    qtbot.wait(50)
    assert row.aux is None and "no auxiliary file" in tab.aux_note.text()
    built = row.geometry.sections.copy()
    box = tab.boxes["thickness_distribution"]
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        box.setCurrentIndex(box.findData(5))
    assert row.main.thickness_distribution == 5 and row.main.spanwise_spline and row.aux.naca
    assert c.error("1") == "" and "naca.t_max[2]" in row.parameters
    assert row.get("naca.t_max[1]") == pytest.approx(row.main.sections["tc_max"][0])
    assert np.abs(row.geometry.sections - built).max() > 1e-3
    c.undo_stack.undo()
    assert row.aux is None and row.main.thickness_distribution == 0 and not row.main.spanwise_spline
    _settled(qtbot, c, "1")
    assert np.array_equal(row.geometry.sections, built)
    c.undo_stack.setClean()
    window.close()


def test_sections_tab(qtbot, case_dir):
    window = _window(qtbot, case_dir)
    c = window.controller
    row = c.row("2")
    tab = _tab(window, "Sections")
    qtbot.wait(50)
    assert tab.table.table.rowCount() == 21 and tab.table.table.columnCount() == 8
    assert tab.table.table.item(0, 0).text() == "-57.82648041"
    assert tab.points._pos.shape == (21, 2) and tab.points._pos[0, 0] == row.main.sections["in_beta"][0]
    assert "built" in tab.plot.names() and tab.built_plot.isHidden()
    assert "chord" in tab.table.table.item(0, 3).toolTip() and tab.table.table.item(0, 0).toolTip() == ""
    assert "chord" in tab.note.text() and "mrel_in" in tab.note.text()      # unused with chord switch 2
    built = row.geometry.sections.copy()

    c.begin_drag()
    tab._point_dragged(5, -45.0, 0.3)
    tab._point_dragged(5, -44.0, 0.9)                                       # the span is not changed
    assert row.get("sec.in_beta[6]") == -44.0 and c.undo_stack.count() == 1
    _settled(qtbot, c, "2")
    assert np.abs(row.geometry.sections - built).max() > 0.01
    c.undo_stack.undo()
    assert row.get("sec.in_beta[6]") == pytest.approx(-50.0582314)
    _settled(qtbot, c, "2")
    assert np.array_equal(row.geometry.sections, built)

    tab.column_list.setCurrentIndex(3)                                      # chord: result on its own plot
    assert not tab.built_plot.isHidden() and "built" not in tab.plot.names()
    tab.column_list.setCurrentIndex(4)                                      # t/c_max: as built from geom_data
    assert "built" in tab.plot.names()
    tab.column_list.setCurrentIndex(2)                                      # mrel_in: no result
    assert "built" not in tab.plot.names() and tab.built_plot.isHidden()
    c.undo_stack.setClean()
    window.close()


def test_thickness_tab(qtbot, case_dir):
    window = _window(qtbot, case_dir)
    c = window.controller
    row = c.row("2")
    tab = _tab(window, "Thickness")
    qtbot.wait(50)
    assert tab.pages.currentIndex() == 0 and tab.naca_table.table.rowCount() == 5
    assert [tab.naca_list.itemText(i) for i in range(tab.naca_list.count())] == ["LE_radius", "u_max", "t_max",
                                                                                    "t_TE"]
    assert tab.naca_param == "t_max" and tab.points._pos[0, 0] == pytest.approx(0.12546)
    assert {"thk 0", "thk 10", "thk 20"} <= set(tab.result_plot.names())
    thickness = row.geometry.thickness[2].copy()

    c.begin_drag()
    tab._point_dragged(2, 0.06, 0.5)                                        # t_max at mid span
    assert row.get("naca.t_max[3]") == 0.06
    _settled(qtbot, c, "2")
    assert np.abs(row.geometry.thickness[10][:, 1] - thickness[:, 1]).max() > 1e-3 or \
        np.abs(row.geometry.thickness[2][:, 1] - thickness[:, 1]).max() > 1e-4
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        tab._add_naca(1)                                                    # between points 2 and 3
    assert row.aux.thickness.data.shape == (6, 5) and row.get("naca.span[3]") == pytest.approx(0.375)
    assert tab.naca_table.table.rowCount() == 6 and c.error("2") == ""
    tab._remove_naca(2)
    assert row.aux.thickness.data.shape == (5, 5)
    c.undo_stack.undo()
    c.undo_stack.undo()
    assert row.aux.thickness.data.shape == (5, 5) and row.get("naca.t_max[3]") == 0.06
    c.undo_stack.undo()
    assert row.get("naca.t_max[3]") == pytest.approx(0.04794)
    _settled(qtbot, c, "2")
    np.testing.assert_array_equal(row.geometry.thickness[2], thickness)
    tab.result_choice.setCurrentIndex(tab.result_choice.findData("all"))
    assert sum(n.startswith("thk ") for n in tab.result_plot.names()) == 21
    c.undo_stack.setClean()
    window.close()


def test_thickness_tab_wennerstrom(qtbot, tmp_path):
    try:
        paths.library()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    window = _window(qtbot, _wennerstrom(tmp_path))
    c = window.controller
    row = c.row("1")
    tab = _tab(window, "Thickness")
    qtbot.wait(50)
    assert tab.pages.currentIndex() == 1 and tab.section_table.table.rowCount() == 21
    assert tab.tm_table.isEnabled() and tab.tm_table.table.rowCount() == 5
    assert "u_max" in tab.section_table.table.item(0, 1).toolTip()               # umxthk: u_max spline instead
    assert tab.section_table.table.item(0, 2).toolTip() == ""
    assert len(row.geometry.thickness) == 21
    assert row.geometry.thickness[0][:, 1].max() == pytest.approx(row.main.sections["tc_max"][0], rel=0.02)
    thickness = [t.copy() for t in row.geometry.thickness]

    tab.section_list.setCurrentIndex(2)                                          # lethk
    assert tab.points._pos[4, 0] == row.main.lethk[4]
    c.begin_drag()
    tab._point_dragged(4, 0.04, 0.2)
    assert row.get("lethk[5]") == 0.04
    _settled(qtbot, c, "1")
    assert np.abs(row.geometry.thickness[4][:, 1] - thickness[4][:, 1]).max() > 1e-4
    c.undo_stack.undo()
    _settled(qtbot, c, "1")
    np.testing.assert_array_equal(row.geometry.thickness[4], thickness[4])
    assert {"thk 0", "thk 10", "thk 20"} <= set(tab.result_plot.names())
    c.undo_stack.setClean()
    window.close()


def test_stacking_tab(qtbot, case_dir):
    window = _window(qtbot, case_dir)
    c = window.controller
    row = c.row("2")
    tab = _tab(window, "Stacking")
    qtbot.wait(50)
    assert tab.variable_box.currentData() == 0 and tab.table.rowCount() == 21
    assert tab.table.cellWidget(0, 0).currentData() == "sect1"
    assert "variable" in tab.table.item(0, 1).toolTip()                         # stk_u unused
    assert (tab.axis_edit.u_spin.value(), tab.axis_edit.v_spin.value()) == (55, 0)       # 055000
    assert tab.points["stk_u"]._pos.shape == (21, 2) and tab.blend_table.rowCount() == len(row.main.blending)
    built = row.geometry.sections.copy()

    tab.axis_edit.u_spin.setValue(30)
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        tab.axis_edit._commit()
    assert row.main.stacking_axis == 30000 and np.abs(row.geometry.sections - built).max() > 0.1
    tab.axis_edit.centroid.setChecked(True)
    assert row.main.stacking_axis == 200000
    c.undo_stack.undo()
    c.undo_stack.undo()
    assert row.main.stacking_axis == 55000 and tab.axis_edit.u_spin.value() == 55

    box = tab.table.cellWidget(3, 0)                                            # an unknown type is refused
    box.setEditText("naca4")
    tab._type_changed(3)
    assert row.main.airfoil_type[3] == "sect1" and box.currentData() == "sect1"
    tab.set_airfoil_type(3, "0012")
    assert row.main.airfoil_type[3] == "0012" and tab.table.cellWidget(3, 0).currentText() == "0012"
    c.undo_stack.undo()
    assert row.main.airfoil_type[3] == "sect1"
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):                      # variable stacking, same blade
        tab.variable_box.setCurrentIndex(1)
    assert row.main.variable_stacking == 1 and tab.table.item(0, 1).toolTip() == ""
    assert tab.table.item(5, 1).text() == "55" and np.array_equal(row.geometry.sections, built)
    c.begin_drag()
    tab._point_dragged("stk_u", 5, 65.0)                                        # moves section 6 only
    _settled(qtbot, c, "2")
    moved = np.abs(row.geometry.sections - built).max(axis=(1, 2))
    assert moved[5] > 0.1 and moved[4] == 0.0 and moved[6] == 0.0
    c.undo_stack.undo()
    c.undo_stack.undo()
    assert row.main.variable_stacking == 0
    _settled(qtbot, c, "2")
    assert np.array_equal(row.geometry.sections, built)
    c.undo_stack.setClean()
    window.close()


def test_airfoils_tab(qtbot, case_dir):
    window = _window(qtbot, case_dir)
    c = window.controller
    row = c.row("2")
    tab = _tab(window, "Airfoils")
    qtbot.wait(50)
    assert tab.section_list.count() == 21 and tab.checked() == [0, 10, 20]
    assert {"sec 0", "sec 10", "sec 20", "mean 0"} <= set(tab.plot.names())
    assert tab.table.rowCount() == 21
    headers = [tab.table.horizontalHeaderItem(j).text() for j in range(tab.table.columnCount())]
    assert "Chord (mm)" in headers and "Throat (mm)" in headers
    tab.table.selectRow(5)
    assert tab.highlight == 5 and "sec highlight" in tab.plot.names()
    tab.check("all")
    assert sum(n.startswith("sec ") and n != "sec highlight" for n in tab.plot.names()) == 21
    tab.meanline_box.setChecked(False)
    assert not any(n.startswith("mean ") for n in tab.plot.names())

    curve = tab.plot._items["sec 10"].getData()[1].copy()                       # follows a rebuild
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        c.set_value("2", "naca.t_max[3]", 0.06)
    assert not np.allclose(tab.plot._items["sec 10"].getData()[1], curve)
    c.undo_stack.undo()
    _settled(qtbot, c, "2")
    np.testing.assert_array_equal(tab.plot._items["sec 10"].getData()[1], curve)
def test_camber_tab(qtbot, case_dir):
    from PySide6.QtCore import Qt

    window = _window(qtbot, case_dir)
    c = window.controller
    row = c.row("2")
    tab = _tab(window, "Camber")
    qtbot.wait(50)
    data = row.aux.curvature.data.copy()
    assert tab.stations.table.rowCount() == len(data) == 8 and tab.points_table.rowCount() == 7
    assert tab.points._pos.shape == (7, 2) and tab.span_points._pos.shape == (8, 2)
    assert tab.points_table.item(1, 0).text() == "0.15" and tab.column_box.currentData() == "cur1"
    assert not tab.points_table.item(0, 0).flags() & Qt.ItemIsEditable        # u1 is fixed at 0
    assert len([n for n in tab.result_plot.names() if n.startswith("sec")]) == 21
    assert "built" in tab.span_plot.names()
    built = row.geometry.sections.copy()

    tab.stations.select_row(3)                                                # station 4, span 0.35
    assert tab.station == 3 and tab.points._pos[2, 1] == row.get("cur3[4]")
    c.begin_drag()                                                            # drag chordwise point 3 in two moves
    tab._point_dragged(2, 0.30, 0.5)
    tab._point_dragged(2, 0.90, 0.7)                                          # location stops short of point 4
    assert row.get("cur3[4]") == 0.7 and row.get("u3[4]") == pytest.approx(0.5 - 1e-4)
    assert c.undo_stack.count() == 1 and tab.points_table.item(2, 1).text() == "0.7"
    qtbot.waitUntil(lambda: row.is_current and not c.is_building("2"), timeout=BUILD)
    assert np.abs(row.geometry.sections - built).max() > 0.01

    tab._point_clicked(4)                                                     # its value along the span
    assert tab.column_box.currentData() == "cur5" and tab.span_points._pos[3, 0] == row.get("cur5[4]")
    tab._span_point_dragged(0, 0.2, 0.0)
    assert row.get("cur5[1]") == 0.2

    with qtbot.waitSignal(c.buildFinished, timeout=BUILD):
        tab._add_station(3)                                                   # between span 0.35 and 0.65
    assert len(row.aux.curvature.data) == 9 and row.get("curvature.span[5]") == pytest.approx(0.5)
    assert tab.stations.table.rowCount() == 9 and tab.station == 4 and "cur7[9]" in row.parameters
    tab._remove_station(4)
    assert len(row.aux.curvature.data) == 8 and "cur7[9]" not in row.parameters
    for _ in range(4):
        c.undo_stack.undo()
    assert c.undo_stack.index() == 0 and np.array_equal(row.aux.curvature.data, data)
    qtbot.waitUntil(lambda: row.is_current and not c.is_building("2"), timeout=BUILD)
    assert np.array_equal(row.geometry.sections, built)

    tab.quantity_box.setCurrentIndex(1)                                       # camber line: starts and ends at zero
    y = tab.result_plot._items["sec10"].getData()[1]
    assert abs(y[0]) < 1e-9 and abs(y[-1]) < 1e-6 and np.abs(y).max() > 0.01
    c.undo_stack.setClean()
    window.close()


def test_unused_inputs_are_greyed(qtbot, case_dir):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    window = _window(qtbot, case_dir)
    c = window.controller
    row = c.row("2")
    grey = QApplication.palette().brush(QPalette.Disabled, QPalette.Text).color()
    tab = _tab(window, "Sensitivities")
    qtbot.wait(50)
    item = tab.picker._items["sec.chord[3]"]                 # chord switch 2: the chord column is not used
    assert item.foreground(0).color() == grey and "chord" in item.toolTip(0) and item.text(1) == "not used"
    assert tab.picker._items["sweep[4]"].toolTip(0) == ""
    tab.select("sec.chord[3]")
    assert tab.method_label.text().startswith("No effect") and tab._coloured is None
    assert "sec.chord[3]" not in row._fd_cache               # no finite-difference runs for it

    c.set_attribute("2", row.main, "curvature_control", 0)   # switch changes: the camber controls go grey
    assert tab.picker._items["cur3[2]"].foreground(0).color() == grey
    c.undo_stack.undo()
    assert tab.picker._items["cur3[2]"].toolTip(0) == "" and tab.picker._items["cur3[2]"].text(1) == "analytic"

    dv = _tab(window, "Design variables")
    c.set_design_variable("2", "sec.chord[3]", True)
    assert "no effect" in dv.summary.text()
    c.undo_stack.undo()
    qtbot.waitUntil(lambda: row.is_current and not c.is_building("2"), timeout=BUILD)
    c.undo_stack.setClean()
    window.close()


def test_export_dialog_request(qtbot, case_dir):
    pytest.importorskip("pyvistaqt")
    from tblade3.gui.export_dialog import DEFAULT_BODIES, ExportDialog
    window = _window(qtbot, case_dir)
    dialog = ExportDialog(window.controller, "2")
    qtbot.addWidget(dialog)
    request = dialog.request()
    assert request.bodies == DEFAULT_BODIES and "step" in request.formats and "brep" in request.formats
    assert request.stem == "Case7-28-8" and request.bore_radius is None and request.sensitivities == ()
    assert not dialog.body_boxes["assembly"].isChecked()
    dialog.bore_edit.setText("15.5")
    dialog.inlet_edit.setText("-20")
    assert (dialog.request().bore_radius, dialog.request().x_inlet, dialog.request().x_outlet) == (15.5, -20.0, None)
    dialog.bore_edit.setText("abc")
    with pytest.raises(ValueError, match="Bore radius"):
        dialog.request()
    dialog.bore_edit.clear()
    for box in dialog.body_boxes.values():
        box.setChecked(False)
    with pytest.raises(ValueError, match="body"):
        dialog.request()
    assert not dialog.sens_box.isEnabled()              # no design variables yet
    window.controller.set_design_variable("2", "sweep[4]", True)
    dialog2 = ExportDialog(window.controller, "2")
    qtbot.addWidget(dialog2)
    dialog2.sens_box.setChecked(True)
    assert dialog2.request().sensitivities == ("sweep[4]",)
    window.close()


def test_export_geometry_in_background(qtbot, case_dir, tmp_path):
    pytest.importorskip("pyvistaqt")
    pytest.importorskip("OCP")
    from tblade3.export_geometry import ExportRequest
    window = _window(qtbot, case_dir)
    c = window.controller
    request = ExportRequest(tmp_path / "out", "rotor", ("blade", "solid"), ("step", "brep"))
    with qtbot.waitSignal(c.exportFinished, timeout=BUILD) as blocker:
        c.export_geometry("2", request)
    row_id, files, notes = blocker.args
    assert row_id == "2" and sorted(f.name for f in files) == ["rotor.step", "rotor_blade.brep", "rotor_solid.brep"]
    assert all(f.is_file() for f in files)
    both = ExportRequest(tmp_path / "out", "withsens", ("blade",), ("hgeom",), sensitivities=("sweep[4]",))
    with qtbot.waitSignal(c.exportFinished, timeout=BUILD) as blocker:
        c.export_geometry("2", both)
    from tblade3.brep import hgeom
    assert "blade" in hgeom.read(blocker.args[1][0]).bodies
    bad = ExportRequest(tmp_path / "out", "bad", ("blade",), ("brep",), bore_radius=1e6)
    with qtbot.waitSignal(c.exportFailed, timeout=BUILD) as blocker:
        c.export_geometry("2", bad)
    assert blocker.args[0] == "2" and blocker.args[1]
    window.close()


def test_export_action_runs_dialog(qtbot, case_dir, tmp_path, monkeypatch):
    pytest.importorskip("pyvistaqt")
    pytest.importorskip("OCP")
    from PySide6.QtWidgets import QMessageBox
    window = _window(qtbot, case_dir)
    dialog = window.export_dialog()
    dialog.folder_edit.setText(str(tmp_path / "gui_out"))
    for name, box in dialog.body_boxes.items():
        box.setChecked(name == "blade")
    for name, box in dialog.format_boxes.items():
        box.setChecked(name == "brep")
    with qtbot.waitSignal(window.controller.exportFinished, timeout=BUILD):
        dialog.accept()
    assert (tmp_path / "gui_out" / "Case7-28-8_blade.brep").is_file()
    qtbot.waitUntil(lambda: isinstance(window.export_box, QMessageBox) and window.export_box.isVisible(), timeout=5000)
    window.export_box.close()
    window.close()


def test_brep_view(qtbot, case_dir):
    pytest.importorskip("pyvistaqt")
    pytest.importorskip("OCP")
    window = _window(qtbot, case_dir)
    c, view = window.controller, window.view
    assert not window.brep_action.isChecked() and not view.show_brep and "2" not in c.brep_meshes
    plain = len(view._actors["2"])
    with qtbot.waitSignal(c.brepReady, timeout=BUILD):
        window.brep_action.trigger()
    assert view.show_brep
    roles = {role for role, _ in c.brep_meshes["2"]}
    assert {"blade_suction", "blade_pressure", "hub", "casing", "periodic_lo", "inlet"} <= roles
    assert len(view._actors["2"]) >= len(roles)
    window.brep_action.trigger()
    assert not view.show_brep and len(view._actors["2"]) == plain
    window.brep_action.trigger()
    with qtbot.waitSignal(c.buildFinished, timeout=BUILD), qtbot.waitSignal(c.brepReady, timeout=BUILD):
        c.set_value("2", "sweep[4]", 0.05)
    assert view.show_brep and c._brep_geometry["2"] is c.row("2").geometry
    window.brep_action.trigger()
    c.undo_stack.undo()
    c.undo_stack.setClean()
    window.close()
