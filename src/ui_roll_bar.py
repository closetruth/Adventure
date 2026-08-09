"""开奖落点画布：随机落点、连通簇可视化、颜色叠加。"""
from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .models import RollPoint
from .reward_system import largest_cluster_indices


class RollDropCanvas(QWidget):
    """随机落点画布，大圆半透明叠加，中央显示连通进度。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: List[RollPoint] = []
        self._cluster_size = 0
        self._span = 10
        self._chance_label = ""
        self._flash = False
        self.setMinimumHeight(64)
        self.setMaximumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_state(
        self,
        points: Sequence[RollPoint],
        cluster_size: int,
        span: int,
        chance_label: str = "",
    ) -> None:
        span = max(1, span)
        cluster_size = max(0, min(cluster_size, span))
        norm_points = list(points)
        changed = (
            self._points != norm_points
            or self._cluster_size != cluster_size
            or self._span != span
            or self._chance_label != chance_label
        )
        self._points = norm_points
        self._cluster_size = cluster_size
        self._span = span
        self._chance_label = chance_label
        if changed:
            self.update()

    def set_flash(self, active: bool) -> None:
        if self._flash != active:
            self._flash = active
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2

        bg_alpha = 28 if not self._flash else 48
        bg = QColor(255, 255, 255, bg_alpha)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        if self._points:
            cluster_idx = set(largest_cluster_indices(self._points))
            point_radius = min(w, h) * 0.16

            # 最大连通簇内的淡连线
            cluster_points = [
                (i, self._points[i]) for i in sorted(cluster_idx)
            ]
            if len(cluster_points) >= 2:
                line_pen = QPen(QColor(255, 255, 255, 36))
                line_pen.setWidthF(1.2)
                painter.setPen(line_pen)
                for ai in range(len(cluster_points)):
                    _, pa = cluster_points[ai]
                    ax = pa.x * w
                    ay = pa.y * h
                    for bi in range(ai + 1, len(cluster_points)):
                        _, pb = cluster_points[bi]
                        dx = pa.x - pb.x
                        dy = pa.y - pb.y
                        if dx * dx + dy * dy <= 0.24 * 0.24:
                            painter.drawLine(
                                QPointF(ax, ay),
                                QPointF(pb.x * w, pb.y * h),
                            )

            painter.setPen(Qt.NoPen)
            painter.setCompositionMode(QPainter.CompositionMode_Plus)
            for i, pt in enumerate(self._points):
                base = QColor(pt.color)
                alpha = 170 if i in cluster_idx else 110
                if self._flash:
                    alpha = min(255, alpha + 40)
                base.setAlpha(alpha)
                painter.setBrush(base)
                cx = pt.x * w
                cy = pt.y * h
                painter.drawEllipse(QPointF(cx, cy), point_radius, point_radius)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # 中央文字
        text_color = QColor("#e8ebf5" if self._flash else "#cfd3e0")
        painter.setPen(QPen(text_color))
        font = QFont("Microsoft YaHei UI", 8)
        font.setBold(True)
        painter.setFont(font)
        main_text = f"{self._cluster_size}/{self._span}"
        if self._chance_label:
            main_text = f"{main_text}  {self._chance_label}"
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, main_text)

        painter.end()
