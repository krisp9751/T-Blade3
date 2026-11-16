"""2D plots (pyqtgraph): a themed plot widget with named curves and draggable control points."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

# Categorical series colours in fixed order (light theme, dark theme). Assign by entity, never by rank.
SERIES = (("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"), ("#eda100", "#c98500"),
          ("#e87ba4", "#d55181"), ("#008300", "#0ca30c"), ("#6250d6", "#9085e9"), ("#e34948", "#e66767"))
# One-hue ramp for ordered families of curves (e.g. hub to tip), light to dark.
RAMP = ("#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")
_TEXT = ("#3c3c3a", "#c3c2b7")
_MUTED = ("#9a9992", "#6f6e68")
_GRID_ALPHA = 0.12


def is_dark() -> bool:
    app = QApplication.instance()
    return bool(app) and app.palette().window().color().lightness() < 128


def series_colour(slot: int) -> str:
    return SERIES[slot % len(SERIES)][int(is_dark())]


def text_colour() -> str:
    return _TEXT[int(is_dark())]


def muted_colour() -> str:
    return _MUTED[int(is_dark())]


def ramp_colours(n: int) -> list[str]:
    """n colours along the one-hue ramp, for an ordered family of curves."""
    stops = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in (RAMP if not is_dark() else RAMP[::-1])],
                     dtype=float)
    if n <= 1:
        idx = np.array([len(stops) / 2.0])
    else:
        idx = np.linspace(0, len(stops) - 1, n)
    lo = np.floor(idx).astype(int).clip(0, len(stops) - 2)
    f = (idx - lo)[:, None]
    rgb = stops[lo] * (1 - f) + stops[lo + 1] * f
    return ["#%02x%02x%02x" % tuple(int(round(v)) for v in c) for c in rgb]


class Plot(pg.PlotWidget):
    """A plot with named items: ``curve(name, x, y)`` creates the curve once and updates it afterwards."""

    def __init__(self, x_label: str = "", y_label: str = "", title: str = "", equal_aspect: bool = False,
                 legend: bool = False, parent=None):
        super().__init__(parent=parent, background=None)
        self._items: dict[str, pg.PlotDataItem] = {}
        item = self.getPlotItem()
        item.showGrid(x=True, y=True, alpha=_GRID_ALPHA)
        item.setMenuEnabled(False)
        if equal_aspect:
            item.setAspectLocked(True)
        self._legend = item.addLegend(offset=(-8, 8)) if legend else None
        self._labels = (x_label, y_label, title)
        self.apply_theme()

    def apply_theme(self) -> None:
        colour = text_colour()
        item = self.getPlotItem()
        x_label, y_label, title = self._labels
        for side, label in (("bottom", x_label), ("left", y_label)):
            axis = item.getAxis(side)
            axis.setPen(pg.mkPen(muted_colour()))
            axis.setTextPen(pg.mkPen(colour))
            if label:
                axis.setLabel(label, color=colour)
        if title:
            item.setTitle(title, color=colour, size="10pt")
        if self._legend is not None:
            self._legend.setLabelTextColor(colour)

    def curve(self, name: str, x, y, colour: str | None = None, width: float = 2.0, dashed: bool = False,
              symbol: str | None = None, label: str | None = None, z: float = 0.0) -> pg.PlotDataItem:
        """Create or update the curve called ``name``. ``label`` puts it in the legend."""
        pen = pg.mkPen(colour or series_colour(0), width=width, style=Qt.DashLine if dashed else Qt.SolidLine)
        item = self._items.get(name)
        if item is None:
            item = self.plot(name=label) if label else self.plot()
            item.setZValue(z)
            self._items[name] = item
        item.setData(np.asarray(x, dtype=float), np.asarray(y, dtype=float), pen=pen,
                     symbol=symbol, symbolSize=7, symbolBrush=colour or series_colour(0), symbolPen=None)
        return item

    def remove(self, name: str) -> None:
        item = self._items.pop(name, None)
        if item is not None:
            self.removeItem(item)
            if self._legend is not None:
                self._legend.removeItem(item)

    def remove_matching(self, prefix: str, keep: set[str] | None = None) -> None:
        """Remove the curves whose name starts with ``prefix``, except those in ``keep``."""
        for name in [n for n in self._items if n.startswith(prefix) and not (keep and n in keep)]:
            self.remove(name)

    def names(self) -> list[str]:
        return list(self._items)


class _DragSignals(QObject):
    moved = Signal(int, float, float)       # index, x, y (while dragging and on release)
    started = Signal(int)
    finished = Signal(int)
    clicked = Signal(int)


class DragPoints(pg.GraphItem):
    """Control points that can be dragged with the mouse.

    ``movable`` is "xy", "x" or "y". Connect ``signals.moved`` to write the new position into the
    model; the item does not move a point by itself, it follows the next ``set_points`` call, so the
    model stays the single source of truth.
    """

    def __init__(self, colour: str | None = None, movable: str = "xy", size: int = 11, line: bool = False):
        super().__init__()
        self.signals = _DragSignals()
        self.movable = movable
        self._colour = colour or series_colour(0)
        self._size = size
        self._line = line
        self._pos = np.zeros((0, 2))
        self._drag_index: int | None = None
        self._drag_offset = None
        self.setZValue(10)
        self.scatter.sigClicked.connect(self._clicked)

    def set_points(self, x, y) -> None:
        self._pos = np.column_stack([np.asarray(x, dtype=float), np.asarray(y, dtype=float)])
        n = len(self._pos)
        if n == 0:
            self.setData(pos=np.zeros((0, 2)), adj=np.zeros((0, 2), dtype=int))
            return
        adj = np.column_stack([np.arange(n - 1), np.arange(1, n)]) if (self._line and n > 1) else np.zeros((0, 2), dtype=int)
        background = "#1a1a19" if is_dark() else "#ffffff"
        self.setData(pos=self._pos, adj=adj, size=self._size, symbol="o", pxMode=True,
                     symbolBrush=pg.mkBrush(self._colour), symbolPen=pg.mkPen(background, width=2),
                     pen=pg.mkPen(self._colour, width=1, style=Qt.DashLine), data=np.arange(n))

    def _clicked(self, _scatter, points) -> None:
        if len(points):
            self.signals.clicked.emit(int(points[0].data()))

    def mouseDragEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            ev.ignore()
            return
        if ev.isStart():
            points = self.scatter.pointsAt(ev.buttonDownPos())
            if len(points) == 0:
                ev.ignore()
                return
            self._drag_index = int(points[0].data())
            self._drag_offset = self._pos[self._drag_index] - np.array([ev.buttonDownPos().x(), ev.buttonDownPos().y()])
            self.signals.started.emit(self._drag_index)
        if self._drag_index is None:
            ev.ignore()
            return
        i = self._drag_index
        new = np.array([ev.pos().x(), ev.pos().y()]) + self._drag_offset
        x = new[0] if "x" in self.movable else self._pos[i, 0]
        y = new[1] if "y" in self.movable else self._pos[i, 1]
        self.signals.moved.emit(i, float(x), float(y))
        if ev.isFinish():
            self._drag_index = None
            self.signals.finished.emit(i)
        ev.accept()
