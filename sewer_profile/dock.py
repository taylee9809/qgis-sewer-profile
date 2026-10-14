# -*- coding: utf-8 -*-
"""종단도 도킹 패널 — 구간 트리 + 종단 캔버스 + 지도 연동"""
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget,
                                 QTreeWidgetItem, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
                                 QAbstractItemView, QMessageBox)
from qgis.core import (QgsProject, QgsMapLayerProxyModel, QgsCoordinateTransform, QgsPointXY, QgsGeometry,
                       QgsWkbTypes, QgsRectangle, QgsVectorLayer, QgsRasterLayer)
from qgis.gui import QgsMapLayerComboBox, QgsVertexMarker, QgsRubberBand

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT

from .network import read_pipes, Network, Profile, Manholes
from .profile_canvas import ProfileCanvas

ROLE = Qt.UserRole + 1
KEY = 'sewer_profile/'


class ProfileDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__('종단도 (Sewer Profile)', parent)
        self.setObjectName('SewerProfileDock')
        self.iface = iface
        self.canvas_map = iface.mapCanvas()
        self.net = None
        self.prof = None
        self.layer = None
        self._xf_to_layer = None
        self._xf_to_map = None

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)

        # --- 상단 설정 줄
        row = QHBoxLayout()
        row.addWidget(QLabel('노선'))
        self.cb_line = QgsMapLayerComboBox()
        self.cb_line.setFilters(QgsMapLayerProxyModel.LineLayer)
        row.addWidget(self.cb_line, 2)
        row.addWidget(QLabel('맨홀'))
        self.cb_mh = QgsMapLayerComboBox()
        self.cb_mh.setFilters(QgsMapLayerProxyModel.PointLayer | QgsMapLayerProxyModel.PolygonLayer)
        self.cb_mh.setAllowEmptyLayer(True)
        row.addWidget(self.cb_mh, 2)
        row.addWidget(QLabel('DEM'))
        self.cb_dem = QgsMapLayerComboBox()
        self.cb_dem.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.cb_dem.setAllowEmptyLayer(True)
        row.addWidget(self.cb_dem, 1)
        row.addWidget(QLabel('필터'))
        self.ed_expr = QLineEdit()
        self.ed_expr.setPlaceholderText("예: \"지구\" IN ('마사','황계(처리장아래)')")
        row.addWidget(self.ed_expr, 3)
        self.bt_build = QPushButton('트리 만들기')
        row.addWidget(self.bt_build)
        lay.addLayout(row)

        # --- 본문: 트리 | 종단
        sp = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['구간(분기점 기준)', '관', '연장 m'])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setColumnWidth(0, 230)
        self.tree.setColumnWidth(1, 36)
        ll.addWidget(self.tree)
        opt = QHBoxLayout()
        self.chk_down = QCheckBox('방류까지')
        self.chk_down.setToolTip('선택한 구간부터 하류 방류점까지 이어서 그린다')
        self.chk_up = QCheckBox('상류 본선')
        self.chk_up.setToolTip('선택한 구간의 상류 본선(가장 긴 상류)까지 이어서 그린다')
        opt.addWidget(self.chk_down)
        opt.addWidget(self.chk_up)
        ll.addLayout(opt)
        opt2 = QHBoxLayout()
        opt2.addWidget(QLabel('관 색'))
        self.cb_color = QComboBox()
        self.cb_color.addItem('구분(자연유하/압송)', 'kind')
        self.cb_color.addItem('금회 판정', 'judge')
        self.cb_color.addItem('우림 판정', 'judge_w')
        opt2.addWidget(self.cb_color)
        self.chk_lab = QCheckBox('라벨')
        self.chk_lab.setChecked(True)
        opt2.addWidget(self.chk_lab)
        ll.addLayout(opt2)
        self.lb_info = QLabel('')
        self.lb_info.setWordWrap(True)
        ll.addWidget(self.lb_info)
        sp.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.pc = ProfileCanvas(right)
        self.tb = NavigationToolbar2QT(self.pc, right)
        self.pc.toolbar = self.tb
        rl.addWidget(self.tb)
        rl.addWidget(self.pc)
        sp.addWidget(right)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setSizes([330, 900])
        lay.addWidget(sp, 1)
        self.setWidget(w)

        # --- 지도 그래픽
        self.band = QgsRubberBand(self.canvas_map, QgsWkbTypes.LineGeometry)
        self.band.setColor(QColor(255, 200, 0, 170))
        self.band.setWidth(6)
        self.marker = QgsVertexMarker(self.canvas_map)
        self.marker.setColor(QColor(224, 27, 36))
        self.marker.setFillColor(QColor(224, 27, 36))
        self.marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
        self.marker.setIconSize(12)
        self.marker.setPenWidth(3)
        self.marker.hide()

        # --- 시그널
        self.bt_build.clicked.connect(self.build_tree)
        self.tree.itemSelectionChanged.connect(self.on_select)
        self.tree.itemDoubleClicked.connect(self.zoom_to_item)
        self.chk_down.toggled.connect(self.on_select)
        self.chk_up.toggled.connect(self.on_select)
        self.cb_color.currentIndexChanged.connect(self.redraw)
        self.chk_lab.toggled.connect(self.redraw)
        self.pc.cursorMoved.connect(self.on_profile_cursor)
        self.pc.cursorLeft.connect(self.marker.hide)
        self.canvas_map.xyCoordinates.connect(self.on_map_move)
        self.canvas_map.destinationCrsChanged.connect(self._update_xf)

        self._restore()

    # ------------------------------------------------------------- settings
    def _restore(self):
        s = QSettings()
        prj = QgsProject.instance()
        for cb, k in ((self.cb_line, 'line'), (self.cb_mh, 'mh'), (self.cb_dem, 'dem')):
            lid = s.value(KEY + k, '')
            lyr = prj.mapLayer(lid) if lid else None
            if lyr is None and k == 'line':
                lyr = next(iter(prj.mapLayersByName('노선(실시설계)')), None)
            if lyr is None and k == 'mh':
                lyr = next(iter(prj.mapLayersByName('계획맨홀(실시설계)')), None)
            if lyr is not None:
                cb.setLayer(lyr)
            elif k != 'line':
                cb.setLayer(None)
        self.ed_expr.setText(s.value(KEY + 'expr', ''))

    def _save(self):
        s = QSettings()
        for cb, k in ((self.cb_line, 'line'), (self.cb_mh, 'mh'), (self.cb_dem, 'dem')):
            s.setValue(KEY + k, cb.currentLayer().id() if cb.currentLayer() else '')
        s.setValue(KEY + 'expr', self.ed_expr.text())

    # ----------------------------------------------------------------- tree
    def build_tree(self):
        lyr = self.cb_line.currentLayer()
        if not isinstance(lyr, QgsVectorLayer):
            QMessageBox.information(self, '종단도', '노선 레이어를 고르세요.')
            return
        expr = self.ed_expr.text().strip() or None
        try:
            pipes = read_pipes(lyr, expr)
        except Exception as e:
            QMessageBox.warning(self, '종단도', '노선을 읽지 못했습니다: %s' % e)
            return
        self.layer = lyr
        self._update_xf()
        self.net = Network(pipes)
        mh = self.cb_mh.currentLayer()
        self.mh = Manholes(mh) if isinstance(mh, QgsVectorLayer) else None
        self._save()
        self.tree.blockSignals(True)
        self.tree.clear()
        net = self.net

        def add(parent, rid):
            r = net.runs[rid]
            it = QTreeWidgetItem([net.run_label(r), str(len(r['pipes'])), '%.1f' % r['length']])
            it.setData(0, ROLE, rid)
            p0 = net.pipes[r['pipes'][0]]
            tip = '%s\n관 %d개 · 연장 %.1f m · 상류 총연장 %.1f m' % (net.run_label(r), len(r['pipes']), r['length'], r['up_length'])
            if p0.zone:
                tip += '\n지구: %s' % p0.zone
            it.setToolTip(0, tip)
            if any('압송' in (net.pipes[i].kind or '') for i in r['pipes']):
                it.setForeground(0, QColor('#c2185b'))
            (parent.addChild(it) if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem(it))
            for c in r['children']:
                add(it, c)
            return it

        # 지구별로 묶기
        groups = {}
        for r in net.roots():
            z = net.pipes[r['pipes'][-1]].zone or '(지구없음)'
            groups.setdefault(z, []).append(r['id'])
        for z in sorted(groups):
            g = QTreeWidgetItem(['%s  (방류 %d)' % (z, len(groups[z])), '', ''])
            g.setFlags(g.flags() & ~Qt.ItemIsSelectable)
            f = g.font(0)
            f.setBold(True)
            g.setFont(0, f)
            self.tree.addTopLevelItem(g)
            for rid in groups[z]:
                add(g, rid)
            g.setExpanded(True)
        self.tree.blockSignals(False)
        njun = sum(1 for n, v in net.inn.items() if len(v) >= 2)
        self.lb_info.setText('관 %d개 · 구간 %d개 · 합류점 %d · 방류 %d' % (
            len(net.pipes), len(net.runs), njun, len(net.roots())))

    def selected_runs(self):
        return [it.data(0, ROLE) for it in self.tree.selectedItems() if it.data(0, ROLE) is not None]

    def on_select(self):
        if self.net is None:
            return
        rids = self.selected_runs()
        if not rids:
            return
        net = self.net
        seq = net.order_runs(rids)
        if seq is None:
            seq = [rids[-1]]
            self.lb_info.setText('선택한 구간들이 한 줄로 이어지지 않아 마지막 것만 그립니다.')
        if self.chk_up.isChecked():
            seq = net.main_upstream(seq[0])[:-1] + seq
        if self.chk_down.isChecked():
            seq = seq[:-1] + net.downstream_chain(seq[-1])
        fids = [f for rid in seq for f in net.runs[rid]['pipes']]
        self.prof = Profile(net, fids, self.mh)
        self._sample_dem(self.prof)
        a, b = net.pipes[fids[0]].name, net.pipes[fids[-1]].name
        self.title = '%s → %s   (관 %d개, %.1f m)' % (a, b, len(fids), self.prof.total)
        self.redraw()
        self._show_band()

    def redraw(self):
        self.pc.color_mode = self.cb_color.currentData()
        self.pc.show_labels = self.chk_lab.isChecked()
        if self.prof is not None:
            self.pc.plot(self.prof, getattr(self, 'title', ''))

    def _sample_dem(self, prof):
        prof.dem = None
        dem = self.cb_dem.currentLayer()
        if not isinstance(dem, QgsRasterLayer):
            return
        xf = QgsCoordinateTransform(self.layer.crs(), dem.crs(), QgsProject.instance())
        step = 2.0
        out = []
        s = 0.0
        while True:
            x, y = prof.locate(s)
            pt = xf.transform(QgsPointXY(x, y))
            v, ok = dem.dataProvider().sample(pt, 1)
            if ok:
                out.append((s, v))
            if s >= prof.total:
                break
            s = min(s + step, prof.total)
        prof.dem = out or None

    # ------------------------------------------------------------- map link
    def _update_xf(self):
        if self.layer is None:
            return
        dst = self.canvas_map.mapSettings().destinationCrs()
        self._xf_to_layer = QgsCoordinateTransform(dst, self.layer.crs(), QgsProject.instance())
        self._xf_to_map = QgsCoordinateTransform(self.layer.crs(), dst, QgsProject.instance())

    def _show_band(self):
        self.band.reset(QgsWkbTypes.LineGeometry)
        if self.prof is None or self._xf_to_map is None:
            return
        for x, y in self.prof.path:
            self.band.addPoint(self._xf_to_map.transform(QgsPointXY(x, y)), False)
        self.band.show()
        self.band.updatePosition()
        self.canvas_map.refresh()

    def zoom_to_item(self, item, col):
        if self.prof is None or self._xf_to_map is None:
            return
        xs = [p[0] for p in self.prof.path]
        ys = [p[1] for p in self.prof.path]
        r = QgsRectangle(min(xs), min(ys), max(xs), max(ys))
        r = self._xf_to_map.transformBoundingBox(r)
        r.scale(1.15)
        self.canvas_map.setExtent(r)
        self.canvas_map.refresh()

    def on_profile_cursor(self, s):
        if self.prof is None or self._xf_to_map is None:
            return
        x, y = self.prof.locate(s)
        self.marker.setCenter(self._xf_to_map.transform(QgsPointXY(x, y)))
        self.marker.show()

    def on_map_move(self, pt):
        if self.prof is None or self._xf_to_layer is None or not self.isVisible():
            return
        try:
            q = self._xf_to_layer.transform(pt)
        except Exception:
            return
        s, d = self.prof.project(q.x(), q.y())
        tol = 15 * self.canvas_map.mapUnitsPerPixel()
        if s is None or d > tol:
            self.marker.hide()
            self.pc.set_cursor(None)
            return
        x, y = self.prof.locate(s)
        self.marker.setCenter(self._xf_to_map.transform(QgsPointXY(x, y)))
        self.marker.show()
        self.pc.set_cursor(s)

    # -------------------------------------------------------------- cleanup
    def cleanup(self):
        try:
            self.canvas_map.xyCoordinates.disconnect(self.on_map_move)
        except Exception:
            pass
        try:
            self.canvas_map.destinationCrsChanged.disconnect(self._update_xf)
        except Exception:
            pass
        for g in (self.band, self.marker):
            try:
                self.canvas_map.scene().removeItem(g)
            except Exception:
                pass

    def closeEvent(self, e):
        self.marker.hide()
        self.band.hide()
        super().closeEvent(e)
