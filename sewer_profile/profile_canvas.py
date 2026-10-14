# -*- coding: utf-8 -*-
"""matplotlib 종단도 캔버스 — 지반선·관저/관정·맨홀·지장물 + 측점 커서"""
from qgis.PyQt.QtCore import pyqtSignal
import matplotlib
from matplotlib.figure import Figure
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:  # pragma: no cover
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

for _f in ('Malgun Gothic', 'NanumGothic', 'AppleGothic'):
    try:
        from matplotlib import font_manager
        font_manager.findfont(_f, fallback_to_default=False)
        matplotlib.rcParams['font.family'] = _f
        break
    except Exception:
        continue
matplotlib.rcParams['axes.unicode_minus'] = False

JUDGE_COLOR = {'GOOD': '#2e9d3a', 'LESS0.6': '#e08a00', '유량없음': '#9e9e9e',
               '만관초과': '#d62728', 'UPPR3.0': '#9c27b0', '역경사/0': '#d62728'}
GROUND = '#8b5a2b'
PIPE = '#1f6fd1'
PRESS = '#c2185b'
OBS = '#555555'


class ProfileCanvas(FigureCanvas):
    cursorMoved = pyqtSignal(float)     # 종단 위 마우스 → 누가거리
    cursorLeft = pyqtSignal()

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(8, 3), tight_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self.prof = None
        self.color_mode = 'kind'
        self.show_labels = True
        self.style = 'simple'      # 'simple' | 'drawing'
        self.vex = 5.0
        self._Y = None
        self._vline = None
        self._dot = None
        self._txt = None
        self.mpl_connect('motion_notify_event', self._on_move)
        self.mpl_connect('axes_leave_event', lambda e: self.cursorLeft.emit())
        self.mpl_connect('scroll_event', self._on_scroll)
        self._empty()

    def _empty(self):
        self.ax.clear()
        self.ax.text(0.5, 0.5, '왼쪽 트리에서 노선을 선택하세요', ha='center', va='center',
                     transform=self.ax.transAxes, color='#888')
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.draw_idle()

    # ------------------------------------------------------------------ draw
    def plot(self, prof, title=''):
        self.prof = prof
        ax = self.ax
        ax.clear()
        ax.set_aspect('auto')
        ax.axis('on')
        self._Y = None
        if prof is None or not prof.pipes:
            self._empty()
            return
        if self.style == 'drawing':
            from .drawing_style import draw_sheet
            info = draw_sheet(ax, prof, vex=self.vex, labels=self.show_labels, title=title)
            self._Y = info['Y']
            self._fit_height(info['ytop'])
            self._vline = ax.axvline(0, color='#e01b24', lw=1.2, visible=False, zorder=9)
            self._dot, = ax.plot([], [], 'o', color='#e01b24', ms=5, zorder=10)
            self._txt = ax.text(0.005, 0.99, '', transform=ax.transAxes, fontsize=7.5, va='top', ha='left', zorder=11,
                                bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='#e01b24', alpha=0.92), visible=False)
            self.draw_idle()
            return
        # 지반선
        if getattr(prof, 'dem', None):
            xs, ys = zip(*prof.dem)
            ax.plot(xs, ys, color=GROUND, lw=1.2, label='지반선(DEM)')
            if prof.ground:
                gx, gy = zip(*prof.ground)
                ax.plot(gx, gy, 'o', color=GROUND, ms=2.5)
        elif prof.ground:
            gx, gy = zip(*prof.ground)
            ax.plot(gx, gy, color=GROUND, lw=1.4, label='지반선(맨홀 지반고)')
        # 관
        ymin, ymax = [], []
        for i, p in enumerate(prof.pipes):
            x0, x1 = prof.seg[i]
            if p.il_up is None or p.il_dn is None:
                continue
            press = '압송' in (p.kind or '')
            if self.color_mode == 'judge':
                c = PRESS if press else JUDGE_COLOR.get(str(p.judge), '#444')
            elif self.color_mode == 'judge_w':
                c = PRESS if press else JUDGE_COLOR.get(str(p.judge_w), '#444')
            else:
                c = PRESS if press else PIPE
            ax.plot([x0, x1], [p.il_up, p.il_dn], color=c, lw=1.6)
            ax.plot([x0, x1], [p.il_up + p.d, p.il_dn + p.d], color=c, lw=0.7)
            ax.fill_between([x0, x1], [p.il_up, p.il_dn], [p.il_up + p.d, p.il_dn + p.d], color=c, alpha=0.18, lw=0)
            ymin += [p.il_up, p.il_dn]
            ymax += [p.il_up + p.d, p.il_dn + p.d]
            # 지장물
            for o in p.obs:
                xo = x0 + o['sta'] * (p.length / max(p.length, 1e-9))
                if xo > x1 + 0.5:
                    xo = x1
                # 가로축이 수백 m 라 실제 폭으로 그리면 선이 된다 → 높이는 실제, 모양은 화면크기 기호
                if o['shape'] == 'rect':
                    h = o['h']
                    bot, top = o['el'], o['el'] + h
                    mk = 's'
                else:
                    d = o['w']
                    bot = o['el'] + 0.30          # flo 저면EL = 관저 − 0.30 규약
                    top = bot + d
                    mk = 'o'
                ax.plot([xo, xo], [bot, top], color=OBS, lw=2.2, solid_capstyle='butt')
                ax.plot([xo], [(bot + top) / 2], marker=mk, mfc='white', mec=OBS, ms=7, mew=1.2)
                ymin.append(o['el'])
                ymax.append(top)
                ax.plot([xo], [o['el']], marker='^', color=OBS, ms=3)
                if self.show_labels:
                    # 맨홀 번호(위)와 겹치지 않게 지장물 라벨은 아래로
                    lab = '%s%s\n저면 %.2f' % (o['kind'], (' D' + o['spec']) if o['spec'] else '', o['el'])
                    ax.annotate(lab, (xo, o['el']), xytext=(0, -6), textcoords='offset points',
                                ha='center', va='top', fontsize=6, color=OBS)
        # 맨홀
        for n in prof.nodes:
            if n['gl'] is not None:
                ymax.append(n['gl'])
            if not n.get('mh'):
                continue
            ils = [v for v in (n['il_in'], n['il_out']) if v is not None]
            bot = min(ils) if ils else None
            top = n['gl']
            if bot is not None and top is not None:
                ax.plot([n['x'], n['x']], [bot, top], color='#333', lw=0.8)
                if n['il_in'] is not None and n['il_out'] is not None and n['il_in'] - n['il_out'] > 0.05:
                    ax.plot([n['x']], [n['il_in']], marker='_', color='#d62728', ms=8)
            if self.show_labels and n['name'] and top is not None:
                ax.annotate(n['name'], (n['x'], top), xytext=(0, 3), textcoords='offset points',
                            rotation=90, ha='center', va='bottom', fontsize=6.5, color='#222')
        if prof.ground:
            ymin += [g for _, g in prof.ground]
        lo = min(ymin) if ymin else 0
        hi = max(ymax) if ymax else 1
        pad = max((hi - lo) * 0.12, 0.5)
        ax.set_ylim(lo - pad * 2.0, hi + pad * 2.2)
        ax.set_xlim(-prof.total * 0.01, prof.total * 1.01)
        ax.set_xlabel('누가거리 (m)', fontsize=8)
        ax.set_ylabel('EL (m)', fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(True, lw=0.3, alpha=0.5)
        ax.set_title(title, fontsize=9)
        self._vline = ax.axvline(0, color='#e01b24', lw=1.0, visible=False)
        self._dot, = ax.plot([], [], 'o', color='#e01b24', ms=5)
        self._txt = ax.text(0, 0, '', fontsize=7, va='top', ha='left',
                            bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='#e01b24', alpha=0.9), visible=False)
        self.draw_idle()

    def _fit_height(self, ytop):
        """도면식: 높이 전체가 보이게, 가로는 패널 비율만큼(가로세로 1:1 유지)"""
        ax = self.ax
        y0, y1 = -12.0, ytop + 10.0
        bb = ax.get_position()
        wpx = max(self.width() * bb.width, 50)
        hpx = max(self.height() * bb.height, 50)
        W = (y1 - y0) * wpx / hpx
        x0 = -35.0
        ax.set_ylim(y0, y1)
        ax.set_xlim(x0, x0 + max(W, 60.0))

    def _on_scroll(self, ev):
        """휠 확대/축소(마우스 위치 기준) — CAD 처럼"""
        if ev.inaxes is not self.ax or ev.xdata is None:
            return
        f = 0.8 if ev.button == 'up' else 1.25
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        self.ax.set_xlim(ev.xdata - (ev.xdata - x0) * f, ev.xdata + (x1 - ev.xdata) * f)
        self.ax.set_ylim(ev.ydata - (ev.ydata - y0) * f, ev.ydata + (y1 - ev.ydata) * f)
        self.draw_idle()

    # ---------------------------------------------------------------- cursor
    def set_cursor(self, s):
        if self.prof is None or self._vline is None:
            return
        if s is None:
            self._vline.set_visible(False)
            self._txt.set_visible(False)
            self._dot.set_data([], [])
            self.draw_idle()
            return
        prof = self.prof
        i, il = prof.invert_at(s)
        p = prof.pipes[i]
        gl = prof.dem_at(s) if getattr(prof, 'dem', None) else prof.ground_at(s)
        lines = ['측점 %.2f m' % s, p.name + (' (압송)' if '압송' in (p.kind or '') else '')]
        if gl is not None:
            lines.append('지반고 %.2f' % gl)
        if il is not None:
            lines.append('관저고 %.2f  D%d' % (il, round(p.d * 1000)))
        if gl is not None and il is not None:
            lines.append('토피 %.2f' % (gl - il - p.d))
        if p.slope is not None:
            lines.append('경사 %.2f‰' % p.slope)
        if p.flow is not None:
            lines.append('누가 %.1f ㎥/일' % p.flow)
        if p.vel is not None:
            lines.append('유속 %.3f m/s %s' % (p.vel, p.judge or ''))
        self._vline.set_xdata([s, s])
        self._vline.set_visible(True)
        if self._Y is not None:
            self._dot.set_data([s], [self._Y(il, s)] if il is not None else [])
            x0, x1 = self.ax.get_xlim()
            if not (x0 <= s <= x1):            # 화면 밖이면 종단을 따라 이동
                w = x1 - x0
                self.ax.set_xlim(s - w / 2, s + w / 2)
            self._txt.set_text('\n'.join(lines))
            self._txt.set_visible(True)
            self.draw_idle()
            return
        self._dot.set_data([s], [il] if il is not None else [])
        y0, y1 = self.ax.get_ylim()
        x0, x1 = self.ax.get_xlim()
        self._txt.set_text('\n'.join(lines))
        self._txt.set_position((s + (x1 - x0) * 0.01 if s < (x0 + x1) / 2 else s - (x1 - x0) * 0.01, y1 - (y1 - y0) * 0.03))
        self._txt.set_ha('left' if s < (x0 + x1) / 2 else 'right')
        self._txt.set_visible(True)
        self.draw_idle()

    def _on_move(self, ev):
        if self.prof is None or ev.inaxes is not self.ax or ev.xdata is None:
            return
        if self.toolbar_active():
            return
        s = max(0.0, min(ev.xdata, self.prof.total))
        self.set_cursor(s)
        self.cursorMoved.emit(s)

    def toolbar_active(self):
        tb = getattr(self, 'toolbar', None)
        return bool(tb and getattr(tb, 'mode', ''))
