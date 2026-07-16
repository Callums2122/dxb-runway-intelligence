from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QMargins, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget
)
from PySide6.QtCharts import QAreaSeries, QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries, QPieSeries, QValueAxis

from .style import COLORS


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("card", True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)


class MetricCard(Card):
    def __init__(self, label: str, value: str = "—", detail: str = "", accent: str = COLORS["cyan"]):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(6)
        self.label = QLabel(label.upper())
        self.label.setObjectName("eyebrow")
        self.value = QLabel(value)
        self.value.setObjectName("metricValue")
        self.value.setStyleSheet(f"color:{accent}")
        self.detail = QLabel(detail)
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def set_value(self, value: str, detail: str | None = None, accent: str | None = None) -> None:
        self.value.setText(value)
        if detail is not None:
            self.detail.setText(detail)
        if accent:
            self.value.setStyleSheet(f"color:{accent}")


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 3)
        layout.setSpacing(3)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:17px;font-weight:700")
        layout.addWidget(heading)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("muted")
            sub.setWordWrap(True)
            layout.addWidget(sub)


class RingWidget(QWidget):
    def __init__(self, value: int = 0, label: str = "SCORE", color: str = COLORS["green"]):
        super().__init__()
        self.value, self.label, self.color = value, label, QColor(color)
        self.setMinimumSize(150, 150)

    def set_value(self, value: int) -> None:
        self.value = max(0, min(100, value))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 22
        rect = self.rect().adjusted((self.width()-side)//2, (self.height()-side)//2, -(self.width()-side)//2, -(self.height()-side)//2)
        pen = QPen(QColor("#222c39"), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -360 * 16)
        pen.setColor(self.color)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, int(-360 * 16 * self.value / 100))
        painter.setPen(QColor(COLORS["text"]))
        font = QFont("Segoe UI Variable", 24, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(rect.adjusted(0, -12, 0, 0), Qt.AlignmentFlag.AlignCenter, str(self.value))
        painter.setPen(QColor(COLORS["muted"]))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRect(0, self.height() // 2 + 20, self.width(), 18), Qt.AlignmentFlag.AlignCenter, self.label)


def _chart_base(title: str) -> QChart:
    chart = QChart()
    chart.setTitle(title)
    chart.setTitleFont(QFont("Segoe UI Variable", 10, QFont.Weight.DemiBold))
    chart.setTitleBrush(QColor(COLORS["text"]))
    chart.setBackgroundVisible(False)
    chart.setPlotAreaBackgroundVisible(False)
    chart.legend().setLabelColor(QColor(COLORS["muted"]))
    chart.legend().setFont(QFont("Segoe UI", 8))
    chart.setMargins(QMargins(6, 8, 6, 4))
    return chart


def line_chart(title: str, values: Sequence[float], labels: Sequence[str] | None = None, color: str = COLORS["cyan"]) -> QChartView:
    chart = _chart_base(title)
    series = QLineSeries()
    series.setName("Balance")
    series.setColor(QColor(color))
    series.setPen(QPen(QColor(color), 2.5))
    for i, value in enumerate(values):
        series.append(i, value)
    chart.addSeries(series)
    axis_x = QValueAxis(); axis_x.setVisible(False); axis_x.setRange(0, max(1, len(values)-1))
    axis_y = QValueAxis(); axis_y.setLabelsColor(QColor(COLORS["muted"])); axis_y.setGridLineColor(QColor("#1d2632")); axis_y.setLabelFormat("%.0f")
    top = max(values or [1]); bottom = min(values or [0]); pad = max(1, (top-bottom)*.15)
    axis_y.setRange(min(0, bottom-pad), top+pad)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom); chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(axis_x); series.attachAxis(axis_y)
    chart.legend().hide()
    view = QChartView(chart); view.setRenderHint(QPainter.RenderHint.Antialiasing); view.setMinimumHeight(220); view.setStyleSheet("background:transparent")
    return view


def bar_chart(title: str, planned: Sequence[float], actual: Sequence[float], labels: Sequence[str]) -> QChartView:
    chart = _chart_base(title)
    set1, set2 = QBarSet("Planned"), QBarSet("Actual")
    set1.setColor(QColor(COLORS["purple"])); set2.setColor(QColor(COLORS["cyan"]))
    set1.append(list(planned)); set2.append(list(actual))
    series = QBarSeries(); series.append(set1); series.append(set2); series.setBarWidth(.62); chart.addSeries(series)
    axis_x = QBarCategoryAxis(); axis_x.append(list(labels)); axis_x.setLabelsColor(QColor(COLORS["muted"]))
    axis_y = QValueAxis(); axis_y.setLabelsColor(QColor(COLORS["muted"])); axis_y.setGridLineColor(QColor("#1d2632")); axis_y.setLabelFormat("%.0f")
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom); chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(axis_x); series.attachAxis(axis_y)
    view = QChartView(chart); view.setRenderHint(QPainter.RenderHint.Antialiasing); view.setMinimumHeight(220); view.setStyleSheet("background:transparent")
    return view


def pie_chart(title: str, values: Sequence[tuple[str, float, str]]) -> QChartView:
    chart = _chart_base(title)
    series = QPieSeries(); series.setHoleSize(.58); series.setPieSize(.78)
    for label, value, color in values:
        piece = series.append(label, value); piece.setBrush(QColor(color)); piece.setPen(QPen(QColor("#111720"), 1))
    chart.addSeries(series)
    view = QChartView(chart); view.setRenderHint(QPainter.RenderHint.Antialiasing); view.setMinimumHeight(220); view.setStyleSheet("background:transparent")
    return view
