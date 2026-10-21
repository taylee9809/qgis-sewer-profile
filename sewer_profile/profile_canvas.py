# -*- coding: utf-8 -*-
"""matplotlib 종단도 캔버스 — 지반선·관저/관정·맨홀·지장물 + 측점 커서"""
from qgis.PyQt.QtCore import pyqtSignal
import matplotlib
from matplotlib.figure import Figure
from matplotlib.transforms import blended_transform_factory
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

# 간단식 색 — 흰 바탕에 가라앉은 톤, 색은 관에만 주고 글자는 먹색으로
JUDGE_COLOR = {'GOOD': '#3f8f5f', 'LESS0.6': '#c6882c', '유량없음': '#9aa3ad',
               '만관초과': '#bf4a44', 'UPPR3.0': '#7a6bb0', '역경사/0': '#bf4a44'}
JUDGE_LABEL = {'GOOD': 'GOOD (기준 만족)', 'LESS0.6': 'LESS0.6 (유속<0.6)',
               'UPPR3.0': 'UPPR3.0 (유속>3.0)'}
JUDGE_ORDER = ['GOOD', 'LESS0.6', 'UPPR3.0', '만관초과', '역경사/0', '유량없음', '미판정',
               '자연유하', '압송', '준공(기존)']
NOJUDGE = '#4b5563'         # 판정값 없음 — 지반(회색)과 구분되게 진하게
MARK = '#e8590c'            # 표시(펜) 마크
GROUND = '#878d96'          # 지반선 — 중립 회색(색은 관에만 주려고)
EARTH = '#f3f4f6'           # 지반 아래
from .drawing_style import C_PIPE as PIPE, C_PRESS as PRESS, C_ASB as ASB   # 성과품과 같은 색
MH = '#2b2b2b'              # 맨홀·지장물 세로선(얇은 검정 점선)
VSTEM = (0, (2, 2))         # 점선 간격
OBS = '#2b2b2b'             # 지장물
INK = '#3c4350'             # 글자
INK2 = '#7b828c'            # 흐린 글자
GRID = '#e9ebef'
AXIS = '#dcdfe4'


CAPTURE_DPI = 600          # 캡처 해상도
LW_ZOOM = (0.15, 4.0)      # 줌 연동 선 굵기 배율 하한·상한
LINE_SCALE = 1.0 / 3.0     # 전체 선 굵기 배율 (261021 사용자: 기존의 1/3 이 적당)
# 원래 굵기(배율 1)가 되는 줌 = 화면 1인치에 담기는 가로 m. 창 크기·캡처 dpi 와 무관한 고정 기준
# (처음 화면을 기준으로 잡으면 패널이 펼쳐지기 전 폭으로 잡혀 틀어진다, 261021)
LW_REF_UPI = {'drawing': 120.0, 'simple': 100.0}   # 성과품 처음 화면(패널 폭 ~10in, 가로 ~1300 m)에서 ≈1


class _Figure(Figure):
    """캡처(툴바 저장)는 화면 해상도(~96dpi)가 아니라 CAPTURE_DPI 로 — 글자 크기는 그림 크기 기준이라 모양은 같다.
    성과품 표시는 화면에서 너무 작아 생략한 글자를 저장 해상도 기준으로 다시 골라 그린다."""

    def savefig(self, *a, **k):
        k.setdefault('dpi', CAPTURE_DPI)
        lazy = getattr(self.canvas, '_lazy', None)
        if lazy is not None and isinstance(k['dpi'], (int, float)):
            lazy.update(scale=k['dpi'] / self.dpi)
        try:
            return super().savefig(*a, **k)
        finally:
            if lazy is not None:
                lazy.update()


class ProfileCanvas(FigureCanvas):
    cursorMoved = pyqtSignal(float)     # 종단 위 마우스 → 누가거리
    cursorLeft = pyqtSignal()
    markClicked = pyqtSignal(float)     # 표시 모드에서 클릭 → 누가거리

    def __init__(self, parent=None):
        self.fig = _Figure(figsize=(8, 3), tight_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self.prof = None
        self.color_mode = 'kind'
        self.show_labels = True
        self.style = 'simple'      # 'simple' | 'drawing'
        self.mark_mode = False     # 표시(펜) 모드
        self.vex = 5.0
        self._Y = None
        self._vline = None
        self._dot = None
        self._txt = None
        self.line_scale = LINE_SCALE
        self._lw_base = []         # [(artist, 원래 굵기)] — 줌 연동용
        self._lw_span = None       # 배율 1 이 되는 1인치당 m (LW_REF_UPI)
        self.mpl_connect('motion_notify_event', self._on_move)
        self.mpl_connect('button_press_event', self._on_click)
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
        if getattr(self, '_lazy', None) is not None:
            self._lazy.disconnect()
            self._lazy = None
        ax.clear()
        ax.set_aspect('auto')
        ax.axis('on')
        self.fig.set_tight_layout(self.style != 'drawing')   # 도면식은 꽉 채우고, 간단식은 축 여백
        self._Y = None
        if prof is None or not prof.pipes:
            self._empty()
            return
        if self.style == 'drawing':
            from .drawing_style import draw_sheet
            info = draw_sheet(ax, prof, vex=self.vex, labels=self.show_labels, title=title)
            self._Y = info['Y']
            from .drawing_style import LazyText
            self._lazy = LazyText(self, ax, info['texts'])
            self._draw_marks(prof)
            self._fit_height(info['ytop'])
            self._vline = ax.axvline(0, color='#e01b24', lw=1.2, visible=False, zorder=9)
            self._dot, = ax.plot([], [], 'o', color='#e01b24', ms=5, zorder=10)
            self._txt = ax.text(0.005, 0.99, '', transform=ax.transAxes, fontsize=7.5, va='top', ha='left', zorder=11,
                                bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='#e01b24', alpha=0.92), visible=False)
            self._lw_init()
            self.draw_idle()
            return
        # 지반선
        gline = None
        if getattr(prof, 'dem', None):
            xs, ys = zip(*prof.dem)
            ax.plot(xs, ys, color=GROUND, lw=1.2, zorder=3)
            gline = (xs, ys)
            if prof.ground:
                gx, gy = zip(*prof.ground)
                ax.plot(gx, gy, 'o', color=GROUND, ms=2.6, zorder=3)
        elif prof.ground:
            gx, gy = zip(*prof.ground)
            ax.plot(gx, gy, color=GROUND, lw=1.3, zorder=3)
            gline = (gx, gy)
        # 관
        ymin, ymax = [], []
        used = {}                                   # 범례 — 실제로 쓰인 색만
        for i, p in enumerate(prof.pipes):
            x0, x1 = prof.seg[i]
            if p.il_up is None or p.il_dn is None:
                continue
            press = '압송' in (p.kind or '')
            if getattr(p, 'asb', False):
                c, key = ASB, '준공(기존)'
            elif self.color_mode == 'judge' and not press:
                j = str(p.judge)
                c = JUDGE_COLOR.get(j, NOJUDGE)
                key = j if j in JUDGE_COLOR else '미판정'
            elif press:
                c, key = PRESS, '압송'
            else:
                c, key = PIPE, '자연유하'
            used.setdefault(key, c)
            ax.fill_between([x0, x1], [p.il_up, p.il_dn], [p.il_up + p.d, p.il_dn + p.d],
                            color=c, alpha=0.85, lw=0, zorder=4)
            ax.plot([x0, x1], [p.il_up, p.il_dn], color=c, lw=1.1, zorder=5,
                    solid_capstyle='butt')          # 관이 얇아도 보이게 관저선만
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
                ax.plot([xo, xo], [bot, top], color=OBS, lw=0.7, ls=VSTEM, zorder=6)
                ax.plot([xo], [(bot + top) / 2], marker=mk, mfc='white', mec=OBS, ms=5.5, mew=0.8, zorder=6)
                ymin.append(o['el'])
                ymax.append(top)
                if self.show_labels:
                    # 맨홀 번호(위)와 겹치지 않게 지장물 라벨은 아래로
                    lab = '%s%s\n저면 %.2f' % (o['kind'], (' D' + o['spec']) if o['spec'] else '', o['el'])
                    ax.annotate(lab, (xo, o['el']), xytext=(0, -6), textcoords='offset points',
                                ha='center', va='top', fontsize=6.4, color=INK2, zorder=7)
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
                ax.plot([n['x'], n['x']], [bot, top], color=MH, lw=0.7, ls=VSTEM, zorder=6)
                if n['il_in'] is not None and n['il_out'] is not None and n['il_in'] - n['il_out'] > 0.05:
                    ax.plot([n['x']], [n['il_in']], marker='_', color='#bf4a44', ms=7, mew=1.4, zorder=7)
            if self.show_labels and n['name'] and top is not None:
                ax.annotate(n['name'], (n['x'], top), xytext=(0, 4), textcoords='offset points',
                            rotation=90, ha='center', va='bottom', fontsize=7, color=INK2, zorder=7)
        if prof.ground:
            ymin += [g for _, g in prof.ground]
        lo = min(ymin) if ymin else 0
        hi = max(ymax) if ymax else 1
        pad = max((hi - lo) * 0.12, 0.5)
        ax.set_ylim(lo - pad * 1.2, hi + pad * 2.6)      # 아래는 지장물 라벨, 위는 맨홀 라벨 자리
        ax.set_xlim(-prof.total * 0.01, prof.total * 1.01)
        if gline:                                        # 지반 아래 — 아주 옅게
            ax.fill_between(gline[0], gline[1], ax.get_ylim()[0], color=EARTH, lw=0, zorder=0)
        ax.set_xlabel('누가거리 (m)', fontsize=8.5, color=INK2)
        ax.set_ylabel('EL (m)', fontsize=8.5, color=INK2)
        ax.tick_params(labelsize=8, colors=INK2, length=3, width=0.8)
        ax.set_axisbelow(True)
        ax.grid(True, axis='y', color=GRID, lw=0.8)      # 가로줄만 — 세로줄은 노이즈
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
        for sp in ('left', 'bottom'):
            ax.spines[sp].set_color(AXIS)
            ax.spines[sp].set_linewidth(0.8)
        ax.set_title(title, fontsize=10.5, color=INK)
        self._draw_marks(prof)
        if used:
            from matplotlib.patches import Patch
            keys = sorted(used, key=lambda k: JUDGE_ORDER.index(k) if k in JUDGE_ORDER else 99)
            hs = [Patch(facecolor=used[k], edgecolor='none', label=JUDGE_LABEL.get(k, k))
                  for k in keys]
            leg = ax.legend(handles=hs, loc='best', fontsize=7.5, frameon=True,
                            framealpha=0.95, edgecolor=AXIS, facecolor='white',
                            borderpad=0.5, labelspacing=0.35, handlelength=1.1,
                            handleheight=0.9, borderaxespad=0.4)
            leg.get_frame().set_linewidth(0.8)
            for t in leg.get_texts():
                t.set_color(INK)
        self._vline = ax.axvline(0, color='#e01b24', lw=1.0, visible=False)
        self._dot, = ax.plot([], [], 'o', color='#e01b24', ms=5)
        self._txt = ax.text(0, 0, '', fontsize=7, va='top', ha='left',
                            bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='#e01b24', alpha=0.9), visible=False)
        self._lw_init()
        self.draw_idle()

    # ------------------------------------------------------------ 선 굵기(줌 연동)
    def _lw_init(self):
        """그린 선들의 원래 굵기를 기억하고, 가로 범위가 바뀔 때마다 굵기를 다시 매긴다.
        matplotlib 선 굵기는 화면 pt 고정이라 줌아웃하면 선끼리 뭉쳐 두껍게 보인다 → CAD 처럼 줌에 비례."""
        ax = self.ax
        skip = {id(self._vline), id(self._dot)}       # 측점 커서는 그대로
        base = []
        for a in list(ax.lines) + list(ax.patches):
            if id(a) not in skip:
                base.append((a, a.get_linewidth()))
        for c in ax.collections:
            base.append((c, list(c.get_linewidths())))
        self._lw_base = base
        self._lw_span = LW_REF_UPI.get(self.style, 48.0)
        ax.callbacks.connect('xlim_changed', lambda _ax: self._lw_apply())   # ax.clear() 가 콜백을 비우므로 매번 연결
        self._lw_apply()

    def _lw_apply(self):
        if not self._lw_base or not self._lw_span:
            return
        z = self._lw_span / self._upp()          # >1 줌인, <1 줌아웃 (창 크기 변경은 영향 없음)
        k = min(max(z, LW_ZOOM[0]), LW_ZOOM[1]) * self.line_scale
        for a, w in self._lw_base:
            if isinstance(w, list):
                a.set_linewidths([v * k for v in w])
            else:
                a.set_linewidth(w * k)

    def _upp(self):
        """화면 1인치당 가로 m — 줌 배율의 기준(창을 넓혀도 같은 줌이면 같은 값)"""
        x0, x1 = self.ax.get_xlim()
        wpx = max(self.ax.get_window_extent().width, 1.0)
        return max(abs(x1 - x0), 1e-9) / wpx * self.figure.dpi

    def set_line_scale(self, v):
        self.line_scale = float(v)
        self._lw_apply()
        self.draw_idle()

    def _draw_marks(self, prof):
        """표시(펜) 마크 — prof.marks = [(측점, 번호)]"""
        for s, lab in getattr(prof, 'marks', None) or []:
            ax = self.ax
            tr = blended_transform_factory(ax.transData, ax.transAxes)
            ax.axvline(s, color=MARK, lw=1.0, ls=(0, (5, 3)), zorder=8)
            ax.plot([s], [0.985], marker='v', ms=8, color=MARK, transform=tr,
                    clip_on=False, zorder=12)
            ax.text(s, 0.955, str(lab), transform=tr, ha='center', va='top',
                    fontsize=7.5, color='white', zorder=13,
                    bbox=dict(boxstyle='circle,pad=0.22', fc=MARK, ec='none'))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.refit_width()
        if getattr(self, '_lazy', None) is not None:
            self._lazy.update()

    def _fit_height(self, ytop):
        """도면식: 높이 전체가 보이게, 가로는 패널 비율만큼(가로세로 1:1 유지)"""
        ax = self.ax
        y0, y1 = -12.0, ytop + 10.0
        wpx, hpx = self._axes_px()
        W = max((y1 - y0) * wpx / hpx, 60.0)
        ax.set_ylim(y0, y1)
        if W > self.prof.total + 70.0:        # 종단이 화면보다 짧으면 가운데로
            c = self.prof.total / 2.0
            ax.set_xlim(c - W / 2.0, c + W / 2.0)
        else:
            ax.set_xlim(-35.0, -35.0 + W)

    def _axes_px(self):
        """도면식은 축 눈금이 없으니 그림틀을 캔버스에 꽉 채운다 → 여백 낭비 제거"""
        ax = self.ax
        if self.style == 'drawing':
            self.fig.set_tight_layout(False)
            ax.set_position([0.004, 0.006, 0.992, 0.988])
        else:
            self.fig.set_tight_layout(True)
        bb = ax.get_position()
        return (max(self.width() * bb.width, 50), max(self.height() * bb.height, 50))

    def refit_width(self):
        """창 크기가 바뀌어도 가로세로 1:1 유지(세로 배율은 그대로, 가운데 기준)"""
        if self.style != 'drawing' or self.prof is None:
            return
        ax = self.ax
        y0, y1 = ax.get_ylim()
        x0, x1 = ax.get_xlim()
        wpx, hpx = self._axes_px()
        W = (y1 - y0) * wpx / hpx
        c = (x0 + x1) / 2.0
        ax.set_xlim(c - W / 2.0, c + W / 2.0)
        self.draw_idle()

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
    def set_profile_cursor(self, s):
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

    def _on_click(self, ev):
        if not self.mark_mode or self.prof is None or ev.inaxes is not self.ax:
            return
        if ev.button != 1 or ev.xdata is None or self.toolbar_active():
            return
        self.markClicked.emit(max(0.0, min(ev.xdata, self.prof.total)))

    def _on_move(self, ev):
        if self.prof is None or ev.inaxes is not self.ax or ev.xdata is None:
            return
        if self.toolbar_active():
            return
        s = max(0.0, min(ev.xdata, self.prof.total))
        self.set_profile_cursor(s)
        self.cursorMoved.emit(s)

    def toolbar_active(self):
        tb = getattr(self, 'toolbar', None)
        return bool(tb and getattr(tb, 'mode', ''))
