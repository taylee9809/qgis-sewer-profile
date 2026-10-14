# -*- coding: utf-8 -*-
"""종단도 도킹 패널 — 구간 트리 + 종단 캔버스 + 지도 연동"""
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QColor, QFont, QBrush
from qgis.PyQt.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget,
                                 QTreeWidgetItem, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
                                 QAbstractItemView, QMessageBox, QHeaderView)
from qgis.core import (QgsProject, QgsMapLayerProxyModel, QgsCoordinateTransform, QgsPointXY, QgsGeometry,
                       QgsWkbTypes, QgsRectangle, QgsVectorLayer, QgsRasterLayer)
from qgis.gui import QgsMapLayerComboBox, QgsVertexMarker, QgsRubberBand, QgsMapToolEmitPoint

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT

from .network import read_pipes, Network, Profile, Manholes, short_range
from .profile_canvas import ProfileCanvas

ROLE = Qt.UserRole + 1
ROLE_TXT = Qt.UserRole + 2          # 찾기용 — 구간에 속한 관번호 전부
KEY = 'sewer_profile/'
PUMP_C = QColor('#c2185b')          # 압송 포함 구간
BR_C = QColor('#6b7280')            # 지류(분기) — 본선은 기본색
GRP_BG = QColor('#e8eaf0')
FIND_BG = QColor('#ffe9a8')         # 찾기에 걸린 구간


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
        self.bt_build = QPushButton('트리 새로고침')
        row.addWidget(self.bt_build)
        self.bt_pick = QPushButton('지도에서 고르기')
        self.bt_pick.setCheckable(True)
        self.bt_pick.setToolTip('켠 뒤 지도에서 관로를 클릭하면 그 관이 속한 구간이 트리에서 선택되고 종단이 그려진다.\n'
                                '(QGIS 선택 도구로 노선을 선택해도 똑같이 동작)')
        row.addWidget(self.bt_pick)
        lay.addLayout(row)

        # --- 본문: 트리 | 종단
        sp = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        rowf = QHBoxLayout()
        rowf.addWidget(QLabel('찾기'))
        self.ed_find = QLineEdit()
        self.ed_find.setPlaceholderText('관번호·지구 일부 (예: MS-A-020, OHG-109, 마사)')
        self.ed_find.setClearButtonEnabled(True)
        self.ed_find.setToolTip('구간에 속한 관번호 전부를 뒤진다 — 중간 관번호로도 그 구간을 찾는다.')
        rowf.addWidget(self.ed_find)
        ll.addLayout(rowf)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['구간', '연장 m'])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(10)
        self.tree.setTextElideMode(Qt.ElideLeft)
        self.tree.setExpandsOnDoubleClick(False)      # 더블클릭 = 지도 줌
        hd = self.tree.header()
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(0, QHeaderView.Stretch)
        hd.setSectionResizeMode(1, QHeaderView.Fixed)
        self.tree.setColumnWidth(1, 64)
        self.tree.headerItem().setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        # 선택 표시를 지도 선택색과 같은 노랑으로 (지도에서 고른 구간이 트리에서 바로 보이게)
        self.tree.setStyleSheet('QTreeWidget::item:selected{background:#ffd21e;}'
                                'QTreeWidget::item:selected:!active{background:#ffd21e;}')
        self.mono = QFont('Consolas')
        self.mono.setStyleHint(QFont.Monospace)
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
        opt3 = QHBoxLayout()
        opt3.addWidget(QLabel('표시'))
        self.cb_style = QComboBox()
        self.cb_style.addItem('도면식(우림 종단면도)', 'drawing')
        self.cb_style.addItem('간단', 'simple')
        opt3.addWidget(self.cb_style)
        opt3.addWidget(QLabel('V'))
        self.cb_vex = QComboBox()
        for lab, v in (('1:200 (×5)', 5.0), ('1:100 (×10)', 10.0), ('1:500 (×2)', 2.0), ('1:1000 (×1)', 1.0)):
            self.cb_vex.addItem(lab, v)
        opt3.addWidget(self.cb_vex)
        ll.addLayout(opt3)
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
        sp.setSizes([400, 840])
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
        self.ed_find.textChanged.connect(self._apply_find)
        self.bt_pick.toggled.connect(self._pick_toggled)
        self.pick_tool = QgsMapToolEmitPoint(self.canvas_map)
        self.pick_tool.canvasClicked.connect(self._picked)
        self.pick_tool.deactivated.connect(lambda: self.bt_pick.setChecked(False))
        self._sel_layer = None
        self._focus_fid = None
        self._hl_fids = None               # 지도에서 고른 관 → 종단 노란 강조
        self.tree.itemSelectionChanged.connect(self.on_select)
        self.tree.itemDoubleClicked.connect(self.zoom_to_item)
        self.chk_down.toggled.connect(self.on_select)
        self.chk_up.toggled.connect(self.on_select)
        self.cb_color.currentIndexChanged.connect(self.redraw)
        self.chk_lab.toggled.connect(self.redraw)
        self.cb_style.currentIndexChanged.connect(self.redraw)
        self.cb_vex.currentIndexChanged.connect(self.redraw)
        self.pc.cursorMoved.connect(self.on_profile_cursor)
        self.pc.cursorLeft.connect(self.marker.hide)
        self.canvas_map.xyCoordinates.connect(self.on_map_move)
        self.canvas_map.destinationCrsChanged.connect(self._update_xf)

        self._restore()
        # 복원이 끝난 뒤에 연결(복원 중 build_tree→_save 가 덜 복원된 값을 저장하던 문제)
        self.cb_line.layerChanged.connect(self._layer_changed)
        self.ed_expr.editingFinished.connect(self.build_tree)
        if isinstance(self.cb_line.currentLayer(), QgsVectorLayer):
            self.build_tree()

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
            if k == 'dem' and not lid:
                lyr = None                     # DEM 은 사용자가 고를 때만
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
        self._watch_selection(lyr)
        self.net = Network(pipes)
        mh = self.cb_mh.currentLayer()
        self.mh = Manholes(mh) if isinstance(mh, QgsVectorLayer) else None
        self._save()
        self.tree.blockSignals(True)
        self.tree.clear()
        net = self.net

        def subtotal(rid):
            return net.runs[rid]['length'] + sum(subtotal(c) for c in net.runs[rid]['children'])

        def add(parent, rid, main, root=False):
            r = net.runs[rid]
            fids = r['pipes']
            pump = any('압송' in (net.pipes[i].kind or '') for i in fids)
            it = QTreeWidgetItem([net.run_short(r) + ('  ⇡' if pump else ''),
                                  format(r['length'], ',.1f')])
            it.setData(0, ROLE, rid)
            it.setData(0, ROLE_TXT, ' '.join(net.pipes[i].name for i in fids).upper())
            fo = QFont(self.mono)
            fo.setBold(root)
            it.setFont(0, fo)
            it.setFont(1, QFont(self.mono))
            it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            tip = '%s\n관 %d개 · 연장 %.1f m · 본선 상류연장 %.1f m' % (
                net.run_label(r), len(fids), r['length'], r['up_length'])
            if pump:
                tip += '\n압송 포함 (⇡)'
            z0 = net.pipes[fids[0]].zone
            if z0:
                tip += '\n지구: %s' % z0
            for c in (0, 1):
                it.setToolTip(c, tip)
                if pump:
                    it.setForeground(c, PUMP_C)
                elif not main:
                    it.setForeground(c, BR_C)       # 지류는 흐리게 → 본선이 뜬다
            (parent.addChild(it) if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem(it))
            for k, ch in enumerate(r['children']):
                add(it, ch, k == 0)               # 첫 자식 = 본선(상류연장 최대)
            return it

        # 지구별로 묶기
        groups = {}
        for r in net.roots():
            z = net.pipes[r['pipes'][-1]].zone or '(지구없음)'
            groups.setdefault(z, []).append(r['id'])
        for z in sorted(groups):
            tot = sum(subtotal(rid) for rid in groups[z])
            g = QTreeWidgetItem(['%s   방류 %d' % (z, len(groups[z])), format(tot, ',.0f')])
            g.setFlags(g.flags() & ~Qt.ItemIsSelectable)
            for c in (0, 1):
                f = g.font(c)
                f.setBold(True)
                g.setFont(c, f)
                g.setBackground(c, GRP_BG)
            g.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            g.setToolTip(0, '%s · 방류 %d 개소 · 총연장 %.1f m' % (z, len(groups[z]), tot))
            self.tree.addTopLevelItem(g)
            for rid in groups[z]:
                add(g, rid, True, True)           # 방류 루트 = 본선 끝 → 굵게
            g.setExpanded(True)
        self.tree.blockSignals(False)
        self._apply_find()
        njun = sum(1 for n, v in net.inn.items() if len(v) >= 2)
        self.lb_info.setText('관 %d개 · 구간 %d개 · 합류점 %d · 방류 %d' % (
            len(net.pipes), len(net.runs), njun, len(net.roots())))

    def _apply_find(self, txt=None):
        q = (txt if txt is not None else self.ed_find.text()).strip().upper()
        for i in range(self.tree.topLevelItemCount()):
            self._filter_item(self.tree.topLevelItem(i), q)

    def _filter_item(self, it, q, forced=False):
        run = it.data(0, ROLE) is not None
        own = bool(q) and (q in (it.data(0, ROLE_TXT) or '') or q in it.text(0).upper())
        hit = forced or (not q) or own
        kid = False
        for i in range(it.childCount()):
            # 지구 이름이 걸리면 그 밑은 전부 보여준다
            kid = self._filter_item(it.child(i), q, forced or (hit and not run)) or kid
        it.setHidden(not (hit or kid))
        if run:
            br = QBrush(FIND_BG) if own else QBrush()
            for c in (0, 1):
                it.setBackground(c, br)
        if q and kid:
            it.setExpanded(True)
        return hit or kid

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
        self.prof.hl = self._hl_spans(self.prof, fids, rids)
        self._sample_dem(self.prof)
        a, b = net.pipes[fids[0]].name, net.pipes[fids[-1]].name
        self.title = '%s → %s   (관 %d개, %.1f m)' % (a, b, len(fids), self.prof.total)
        self.redraw()
        self._show_band()
        if self._focus_fid is not None and self._focus_fid in fids:
            k = fids.index(self._focus_fid)
            x0, x1 = self.prof.seg[k]
            sm = (x0 + x1) / 2
            self.pc.set_profile_cursor(sm)
            self.on_profile_cursor(sm)
        self._focus_fid = None

    def _hl_spans(self, prof, fids, rids):
        """종단에서 노랗게 칠할 구간 — 지도에서 고른 관, 없으면 트리에서 고른 구간.
        그린 전체가 선택이면(= 구분할 게 없으면) 칠하지 않는다."""
        allf = set(fids)
        sel = set(self._hl_fids or ()) & allf
        if not sel:
            sel = set(f for rid in rids for f in self.net.runs[rid]['pipes']) & allf
        if not sel or len(sel) == len(allf):
            return []
        out, i, n = [], 0, len(fids)
        while i < n:
            if fids[i] not in sel:
                i += 1
                continue
            j = i
            while j + 1 < n and fids[j + 1] in sel:
                j += 1
            out.append((prof.seg[i][0], prof.seg[j][1],
                        short_range(prof.pipes[i].name, prof.pipes[j].name)))
            i = j + 1
        return out

    def redraw(self):
        self.pc.color_mode = self.cb_color.currentData()
        self.pc.show_labels = self.chk_lab.isChecked()
        self.pc.style = self.cb_style.currentData()
        self.pc.vex = self.cb_vex.currentData()
        self.cb_vex.setEnabled(self.pc.style == 'drawing')
        self.cb_color.setEnabled(self.pc.style == 'simple')
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

    # ------------------------------------------------- map → tree selection
    def _layer_changed(self, lyr):
        if isinstance(lyr, QgsVectorLayer):
            self.build_tree()

    def _watch_selection(self, lyr):
        if self._sel_layer is not None:
            try:
                self._sel_layer.selectionChanged.disconnect(self._map_selection)
            except Exception:
                pass
        self._sel_layer = lyr
        lyr.selectionChanged.connect(self._map_selection)

    def _map_selection(self, selected, deselected, clear):
        if self.net is None or not self.isVisible():
            return
        fids = [f for f in self.layer.selectedFeatureIds() if f in self.net.run_of]
        if not fids:
            return
        rids = list(dict.fromkeys(self.net.run_of[f] for f in fids))
        self._hl_fids = set(fids)
        self._focus_fid = fids[0] if len(fids) == 1 else None
        self.select_runs(rids)

    def _items_by_run(self):
        out = {}
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            rid = it.data(0, ROLE)
            if rid is not None:
                out[rid] = it
            stack += [it.child(i) for i in range(it.childCount())]
        return out

    def select_runs(self, rids):
        items = self._items_by_run()
        if self.ed_find.text().strip() and any(
                items.get(r) is not None and items[r].isHidden() for r in rids):
            self.ed_find.clear()
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        last = None
        for rid in rids:
            it = items.get(rid)
            if it is None:
                continue
            it.setSelected(True)
            p = it.parent()
            while p is not None:
                p.setExpanded(True)
                p = p.parent()
            last = it
        self.tree.blockSignals(False)
        if last is not None:
            self.tree.scrollToItem(last)
            self.on_select()

    def _pick_toggled(self, on):
        if on:
            self._prev_tool = self.canvas_map.mapTool()
            self.canvas_map.setMapTool(self.pick_tool)
        elif self.canvas_map.mapTool() is self.pick_tool:
            prev = getattr(self, '_prev_tool', None)
            if prev is not None:
                self.canvas_map.setMapTool(prev)
            else:
                self.canvas_map.unsetMapTool(self.pick_tool)

    def _picked(self, pt, button):
        if self.net is None or self._xf_to_layer is None:
            return
        q = self._xf_to_layer.transform(pt)
        tol = 12 * self.canvas_map.mapUnitsPerPixel()
        best = None
        for fid, p in self.net.pipes.items():
            xs = [a for a, _ in p.pts]
            ys = [b for _, b in p.pts]
            if not (min(xs) - tol <= q.x() <= max(xs) + tol and min(ys) - tol <= q.y() <= max(ys) + tol):
                continue
            for (ax_, ay), (bx, by) in zip(p.pts, p.pts[1:]):
                dx, dy = bx - ax_, by - ay
                L2 = dx * dx + dy * dy
                t = 0 if L2 == 0 else max(0.0, min(1.0, ((q.x() - ax_) * dx + (q.y() - ay) * dy) / L2))
                d = ((q.x() - ax_ - dx * t) ** 2 + (q.y() - ay - dy * t) ** 2) ** 0.5
                if d <= tol and (best is None or d < best[0]):
                    best = (d, fid)
        if best is None:
            return
        self.layer.selectByIds([best[1]])      # → _map_selection 이 트리·종단 갱신

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
            self.pc.set_profile_cursor(None)
            return
        x, y = self.prof.locate(s)
        self.marker.setCenter(self._xf_to_map.transform(QgsPointXY(x, y)))
        self.marker.show()
        self.pc.set_profile_cursor(s)

    # -------------------------------------------------------------- cleanup
    def cleanup(self):
        if self._sel_layer is not None:
            try:
                self._sel_layer.selectionChanged.disconnect(self._map_selection)
            except Exception:
                pass
        if self.canvas_map.mapTool() is self.pick_tool:
            self.canvas_map.unsetMapTool(self.pick_tool)
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
