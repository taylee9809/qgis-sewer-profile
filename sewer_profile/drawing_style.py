# -*- coding: utf-8 -*-
"""우림 종단면도 DXF 서식을 흉내낸 '도면식' 종단.

좌표: 가로 1 단위 = 1 m (H 1:1000), 세로 Y = 117 + (EL − DATUM) × VEX (VEX 5 = V 1:200)
밴드(아래→위, 각 15): 측점 · 거리 · 추가거리 · 지반고 · 관저고 · 토피 · 구배
그 위: 구간 표제 막대 y=111, 관번호 막대 y=129, 기준선 y=117, 45° 인출선(맨홀명·H)
글자는 도면 단위 높이 — 확대 비율에 맞춰 보이는 것만 그린다(LazyText), CAD 처럼 같이 커진다.
"""
import math
from matplotlib.font_manager import FontProperties
from matplotlib.collections import LineCollection
from matplotlib.patches import Ellipse, Rectangle, Polygon, Circle

BANDS = ['측    점', '거    리', '추가거리', '지 반 고', '관 저 고', '토    피', '구    배']
C_GROUND = '#d62728'
C_PIPE = '#1f3fd1'
C_PRESS = '#c2185b'
C_MH = '#c000c0'
C_BAND = '#1aa3a3'
C_BAND2 = '#2ca02c'
C_LEAD = '#9a8a00'
C_TEXT = '#111111'
C_OBS = '#555555'
C_GRID = '#c8c8c8'

_FP = None


def _fp():
    global _FP
    if _FP is None:
        for f in ('Malgun Gothic', 'NanumGothic', 'Dotum', 'AppleGothic', 'DejaVu Sans'):
            try:
                from matplotlib import font_manager
                font_manager.findfont(f, fallback_to_default=False)
                _FP = FontProperties(family=f)
                break
            except Exception:
                continue
        if _FP is None:
            _FP = FontProperties()
    return _FP


class _Text(object):
    """도면 단위 글자 명세만 모은다. 실제 Text 는 LazyText 가 화면에 보이는 것만 만든다
    (8.7 km 노선 글자 수천 개를 한 번에 도형화하면 40초 넘게 걸렸다)."""

    def __init__(self):
        self.specs = []

    def add(self, x, y, s, h=2.5, rot=0, ha='left', va='bottom', color=C_TEXT):
        if s:
            self.specs.append((x, y, s, h, rot, ha, va, color))

    def flush(self, ax):
        return self.specs


class LazyText(object):
    """도면 단위 높이 h 를 현재 확대 비율로 pt 환산해 보이는 범위의 글자만 그린다."""
    MIN_PX = 3.0         # 이보다 작게 보이면 생략
    MAX_N = 3000

    def __init__(self, canvas, ax, specs):
        self.canvas, self.ax, self.specs = canvas, ax, specs
        self.arts = []
        self._busy = False
        import bisect
        self._bisect = bisect
        self.specs.sort(key=lambda t: t[0])
        self.xs = [t[0] for t in self.specs]
        self.cids = [ax.callbacks.connect('xlim_changed', self.update),
                     ax.callbacks.connect('ylim_changed', self.update)]

    def disconnect(self):
        for c in self.cids:
            try:
                self.ax.callbacks.disconnect(c)
            except Exception:
                pass
        self.clear()

    def clear(self):
        for a in self.arts:
            try:
                a.remove()
            except Exception:
                pass
        self.arts = []

    def update(self, *_):
        if self._busy:
            return
        self._busy = True
        try:
            ax = self.ax
            self.clear()
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            bb = ax.get_window_extent()
            if bb.width <= 0 or x1 <= x0:
                return
            ppu = bb.width / (x1 - x0)                 # 픽셀 / 도면단위
            pt = 72.0 / self.canvas.figure.dpi
            pad = 40
            i0 = self._bisect.bisect_left(self.xs, x0 - pad)
            i1 = self._bisect.bisect_right(self.xs, x1 + pad)
            cnt = 0
            for x, y, s, h, rot, ha, va, color in self.specs[i0:i1]:
                if h * ppu < self.MIN_PX or not (y0 - pad <= y <= y1 + pad):
                    continue
                fp = _fp().copy()
                fp.set_size(h * 1.12 * ppu * pt)
                self.arts.append(ax.text(x, y, s, fontproperties=fp, rotation=rot,
                                         rotation_mode='anchor', ha=ha, va=va, color=color,
                                         zorder=6, clip_on=True))
                cnt += 1
                if cnt >= self.MAX_N:
                    break
        finally:
            self._busy = False


def _fmt_sta(s):
    s = round(s, 3)
    n = int(math.floor(s / 20.0 + 1e-4))
    r = s - n * 20
    if abs(r) < 0.005:
        return 'NO. %d' % n
    return '+ %.2f' % r


def _mh_kind(n):
    k = (n.get('mh_kind') or '')
    if '펌프' in k:
        return '맨홀펌프장'
    if '기존' in k:
        return '1호기존'
    if k:
        return '1호맨홀' if k in ('계획맨홀', '1호맨홀') else k
    return '1호맨홀'


def draw_sheet(ax, prof, vex=5.0, labels=True, title=''):
    T = _Text()
    total = prof.total
    # ---- DATUM
    ils = [v for p in prof.pipes for v in (p.il_up, p.il_dn) if v is not None]
    obs_el = [o['el'] for p in prof.pipes for o in p.obs]
    lo = min(ils + obs_el) if (ils or obs_el) else 0.0
    # ---- DATUM 구간: 우림 도면처럼 높이가 벗어나면 맨홀에서 DATUM 을 바꾼다(단절선)
    def pipe_lo(p):
        v = [x for x in (p.il_up, p.il_dn) if x is not None] + [o['el'] for o in p.obs]
        return (min(v) - p.d) if v else None

    def win_lo(i):
        x0 = prof.seg[i][0]
        v = [pipe_lo(q) for j, q in enumerate(prof.pipes[i:], start=i) if prof.seg[j][0] - x0 <= WIN]
        v = [a for a in v if a is not None]
        return min(v) if v else lo
    WIN, LOW, HIGH = 250.0, 2.0, 32.0 * 5.0 / vex
    dsegs = []                       # [(x_start, datum)]
    for i, p in enumerate(prof.pipes):
        pl = pipe_lo(p)
        if not dsegs:
            dsegs.append((prof.seg[i][0], math.floor(win_lo(i)) - 12))
            continue
        cur = dsegs[-1][1]
        if pl is not None and (pl < cur + LOW or pl > cur + 12 + HIGH * 0.6):
            nd = math.floor(win_lo(i)) - 12
            if nd != cur:
                dsegs.append((prof.seg[i][0], nd))
    breaks = [x for x, _ in dsegs[1:]]

    def dat_at(s, right=True):
        d = dsegs[0][1]
        for x, v in dsegs:
            if s > x + 1e-6 or (right and abs(s - x) <= 1e-6):
                d = v
        return d

    def Y(el, s=0.0, right=True):
        return 117 + (el - dat_at(s, right)) * vex
    datum = dsegs[0][1]

    # ---- 측점 목록: 20 m 배수 + 맨홀 + 지장물 (0.3 m 안은 병합, 맨홀 우선)
    cand = [(n['x'], 0) for n in prof.nodes]
    for i, p in enumerate(prof.pipes):
        x0, x1 = prof.seg[i]
        for o in p.obs:
            cand.append((min(x0 + o['sta'], x1), 1))
    k = 0
    while k * 20 <= total + 1e-6:
        cand.append((k * 20.0, 2))
        k += 1
    cand.sort(key=lambda t: (t[0], t[1]))
    sta = []
    for x, pr in cand:
        if sta and abs(sta[-1][0] - x) < 0.3:
            if pr < sta[-1][1]:
                sta[-1] = (x, pr)
            continue
        sta.append((x, pr))
    gfun = prof.dem_at if getattr(prof, 'dem', None) else prof.ground_at

    def pd_in(i):
        return prof.pipes[i - 1].d if i > 0 else prof.pipes[0].d

    # ---- 밴드 틀
    segs = []
    for j in range(8):
        segs.append([(-30, j * 15), (total + 5, j * 15)])
    segs.append([(-30, 0), (-30, 105)])
    segs.append([(-8, 0), (-8, 105)])
    ax.add_collection(LineCollection(segs, colors=C_BAND, linewidths=0.8, zorder=2))
    for j, name in enumerate(BANDS):
        T.add(-19, j * 15 + 7.5, name, h=3.0, ha='center', va='center')
    # 기준선·표척
    ax.plot([-8, total + 5], [117, 117], color=C_BAND, lw=0.6, zorder=2)
    ytop_rul = 117
    for k, (xs, dv) in enumerate(dsegs):
        xe = dsegs[k + 1][0] if k + 1 < len(dsegs) else total
        gl_seg = [g for x, g in prof.ground if xs - 1e-6 <= x <= xe + 1e-6] or [lo]
        top_el = math.ceil(max(gl_seg) / 10.0) * 10
        rx = -7.5 if k == 0 else xs
        el = math.ceil(dv / 10.0) * 10
        while el <= top_el:
            y = 117 + (el - dv) * vex
            ax.plot([rx - 2.5, rx + 2.5], [y, y], color=C_MH, lw=0.8, zorder=2)
            T.add(rx - 4.5, y + 1, '%.2f' % el, h=3.0 if k == 0 else 2.2, ha='right', va='bottom',
                  color=C_TEXT if k == 0 else C_MH)
            el += 10
        yt = 117 + (top_el - dv) * vex
        ytop_rul = max(ytop_rul, yt)
        if k == 0:
            ax.plot([rx, rx], [117, yt], color=C_MH, lw=2.0, zorder=2)
        else:                       # DATUM 변경 단절선
            ax.plot([xs, xs], [117, yt], color=C_MH, lw=0.8, ls=(0, (4, 3)), zorder=2)
            T.add(xs + 1.0, 118.5, 'DATUM %.2f' % dv, h=2.2, rot=90, ha='left', va='bottom', color=C_MH)
    T.add(-28, -3.5, 'H=1:1000', h=2.5, va='top')
    T.add(-28, -7.5, 'V=1:%d' % round(1000 / vex), h=2.5, va='top')

    # ---- 측점별 밴드 값
    prev = None
    vl = []
    lx_prev = -1e9
    for x, pr in sta:
        lx = max(x, lx_prev + 2.7)        # 글자 겹침 회피(우림 도면도 옆으로 민다)
        lx_prev = lx
        gl = gfun(x)
        i, il = prof.invert_at(x)
        p = prof.pipes[i]
        vl.append([(x, 117), (x, Y(gl, x) if gl is not None else 117)])
        for j in range(1, 7):
            vl.append([(x, j * 15 - 1), (x, j * 15 + 1)])
        if lx - x > 0.05:
            vl.append([(x, 0), (lx, 3)])
        T.add(lx, 14, _fmt_sta(x), rot=90, ha='right', va='center')
        T.add(lx, 29, '%.2f' % (x - prev if prev is not None else 0.0), rot=90, ha='right', va='center')
        T.add(lx, 44, '%.2f' % x, rot=90, ha='right', va='center')
        if gl is not None:
            T.add(lx, 59, '%.2f' % gl, rot=90, ha='right', va='center')
        node = next((n for n in prof.nodes if abs(n['x'] - x) < 0.3), None)
        if node is not None:
            il_out = node['il_out'] if node['il_out'] is not None else node['il_in']
            il_in = node['il_in']
            if il_out is not None:
                T.add(lx, 74, '%.2f' % il_out, rot=90, ha='right', va='center')
            if il_in is not None and il_out is not None and il_in - il_out >= 0.05:
                T.add(lx - 2.5, 74, '%.2f' % il_in, rot=90, ha='right', va='center')
                if gl is not None:
                    T.add(lx - 2.5, 89, '%.2f' % (gl - il_in - pd_in(i)), rot=90, ha='right', va='center')
            ilv, pd = il_out, (prof.pipes[min(i, len(prof.pipes) - 1)].d)
        else:
            ilv, pd = il, p.d
            if il is not None:
                T.add(lx, 74, '%.2f' % il, rot=90, ha='right', va='center')
        if gl is not None and ilv is not None:
            T.add(lx, 89, '%.2f' % (gl - ilv - pd), rot=90, ha='right', va='center')
        prev = x
    ax.add_collection(LineCollection(vl, colors=C_GRID, linewidths=0.5, zorder=1))

    # ---- 구배 밴드: 맨홀 원 + 관저고, 구간 L/H/S
    for n in prof.nodes:
        if not n.get('mh') and n is not prof.nodes[-1]:
            continue
        ax.add_patch(Circle((n['x'], 97.5), 7.5, fill=False, ec=C_LEAD, lw=0.7, zorder=3))
        v = n['il_out'] if n['il_out'] is not None else n['il_in']
        if v is not None:
            T.add(n['x'], 97.5, '%.2f' % v, rot=90, ha='center', va='center')
    mh_x = [n['x'] for n in prof.nodes if n.get('mh')] + [total]
    mh_x = sorted(set(round(v, 3) for v in mh_x))
    for a, b in zip(mh_x, mh_x[1:]):
        i0 = prof.pipe_at(a + 1e-3)
        i1 = prof.pipe_at(b - 1e-3)
        ia, ib = prof.pipes[i0], prof.pipes[i1]
        if ia.il_up is None or ib.il_dn is None:
            continue
        L = b - a
        H = ia.il_up - ib.il_dn
        S = H / L * 1000 if L > 0 else 0
        mid = (a + b) / 2
        s1 = 'L=%.2fM, H=%.2fM' % (L, H)
        s2 = 'S=%.2f‰' % S
        room = L - 15
        if room > len(s1) * 1.1:
            T.add(mid, 93.75, s1, h=2.0, ha='center', va='center')
            T.add(mid, 101.25, s2, h=2.0, ha='center', va='center')
        else:                                  # 폭 부족 — 우림처럼 기준선 위 3줄
            T.add(mid, 117.6, 'H=%.2fM' % H, h=1.6, ha='center', va='bottom')
            T.add(mid, 119.7, 'L=%.2fM' % L, h=1.6, ha='center', va='bottom')
            T.add(mid, 121.8, s2, h=1.6, ha='center', va='bottom')
        if room > 4:
            ax.plot([a + 7.5, b - 7.5], [90.5, 104.5] if H < 0 else [104.5, 90.5], color=C_LEAD, lw=0.5, zorder=3)

    # ---- 관번호 막대(y 129) / 관종 막대(y 111)
    def bar(a, b, y):
        if b - a < 5.5:
            ax.plot([a, b], [y, y], color=C_TEXT, lw=0.6, zorder=3)
            return
        ax.add_patch(Polygon([(a, y), (a + 2.5, y + 1.25), (a + 2.5, y - 1.25)], closed=True, fc=C_TEXT, ec='none', zorder=3))
        ax.add_patch(Polygon([(b, y), (b - 2.5, y + 1.25), (b - 2.5, y - 1.25)], closed=True, fc=C_TEXT, ec='none', zorder=3))
        ax.plot([a + 2.5, b - 2.5], [y, y], color=C_TEXT, lw=0.6, zorder=3)
    for i, p in enumerate(prof.pipes):
        a, b = prof.seg[i]
        if p.length < 0.5:
            continue
        bar(a, b, 129)
        if labels:
            h = 2.5 if (b - a) > len(p.name) * 1.6 else max(1.0, (b - a) / max(len(p.name), 1) * 1.4)
            T.add((a + b) / 2, 131.25, p.name, h=h, ha='center', va='bottom')
            T.add((a + b) / 2, 126.75, 'L=%.2fM' % p.length, h=min(h, 2.5), ha='center', va='center')
    runs = []
    for i, p in enumerate(prof.pipes):
        key = ('신설압송' if '압송' in (p.kind or '') else '신설오수', round(p.d * 1000))
        if runs and runs[-1][0] == key:
            runs[-1][2] = prof.seg[i][1]
        else:
            runs.append([key, prof.seg[i][0], prof.seg[i][1]])
    for (kind, dmm), a, b in runs:
        bar(a, b, 111)
        T.add((a + b) / 2, 113.5, '%s, D=%dMM' % (kind, dmm), h=3.0 if b - a > 40 else 2.0, ha='center', va='bottom')
        T.add((a + b) / 2, 108.5, 'L=%.2fM' % (b - a), h=2.5, ha='center', va='top')

    # ---- 지반선 / 관
    if getattr(prof, 'dem', None):
        gpts = prof.dem
    else:
        gpts = prof.ground
    if gpts:                          # DATUM 구간마다 끊어 그림
        bounds = [x for x, _ in dsegs] + [total + 1]
        for k in range(len(dsegs)):
            xs, xe = bounds[k], bounds[k + 1]
            pts = [(x, g) for x, g in gpts if xs - 1e-6 <= x <= xe + 1e-6]
            if k + 1 < len(dsegs):
                ge = gfun(xe)
                if ge is not None and not any(abs(x - xe) < 1e-6 for x, _ in pts):
                    pts.append((xe, ge))
            if pts:
                ax.plot([x for x, _ in pts], [Y(g, x, right=(abs(x - xs) < 1e-6)) if abs(x - xe) > 1e-6 else Y(g, x, right=False) for x, g in pts],
                        color=C_GROUND, lw=1.0, zorder=4)
    for i, p in enumerate(prof.pipes):
        a, b = prof.seg[i]
        if p.il_up is None or p.il_dn is None:
            continue
        c = C_PRESS if '압송' in (p.kind or '') else C_PIPE
        dv = dat_at(a)
        Yp = lambda el: 117 + (el - dv) * vex
        ax.plot([a, b], [Yp(p.il_up), Yp(p.il_dn)], color=c, lw=0.9, zorder=4)
        ax.plot([a, b], [Yp(p.il_up + p.d), Yp(p.il_dn + p.d)], color=c, lw=0.9, zorder=4)

    # ---- 맨홀 + 45° 인출선
    lead = []
    for n in prof.nodes:
        if not n.get('mh'):
            continue
        gl = n['gl']
        ilm = [v for v in (n['il_in'], n['il_out']) if v is not None]
        if gl is None or not ilm:
            continue
        bot = min(ilm)
        x = n['x']
        wo = 1.5 + 0.4 if '펌프' in (n.get('mh_kind') or '') else 0.9 + 0.4
        rt = n is not prof.nodes[-1]
        Ym = lambda el: Y(el, x, right=rt)
        ax.add_patch(Rectangle((x - wo / 2, Ym(bot - 0.4)), wo, Ym(gl) - Ym(bot - 0.4), fill=False, ec=C_MH, lw=0.8, zorder=5))
        ax.add_patch(Rectangle((x - (wo - 0.4) / 2, Ym(bot - 0.2)), wo - 0.4, Ym(gl - 0.2) - Ym(bot - 0.2), fill=False, ec=C_MH, lw=0.5, zorder=5))
        if not labels:
            continue
        y0 = Ym(gl)
        cx, cy = x, y0 + 43.5
        ex, ey = cx + 23 * math.cos(math.radians(45)), cy + 23 * math.sin(math.radians(45))
        lead += [[(x, y0), (cx, cy)], [(cx, cy), (ex, ey)]]
        H = gl - bot
        drop = (n['il_in'] - n['il_out']) if (n['il_in'] is not None and n['il_out'] is not None) else 0
        nm = (n['name'] or '') + ' ' + _mh_kind(n)
        T.add(cx + 0.9, cy + 1.0, nm.strip(), h=2.5, rot=45, ha='left', va='bottom')
        hs = 'H=%.2fM' % H + (' (dh=%.2fM)' % drop if drop >= 0.05 else '')
        T.add(cx + 2.4, cy - 0.6, hs, h=2.2, rot=45, ha='left', va='top')

    # ---- 지장물: 타원(가로 실폭, 세로 ×VEX) + 45° 3줄 라벨
    for i, p in enumerate(prof.pipes):
        x0, x1 = prof.seg[i]
        for o in p.obs:
            xo = min(x0 + o['sta'], x1)
            gl = gfun(xo)
            if o['shape'] == 'rect':
                w, h = o['w'], o['h']
                bot = o['el']
                ax.add_patch(Rectangle((xo - w / 2, Y(bot, x0)), w, h * vex, fill=False, ec=C_OBS, lw=0.8, zorder=5))
                top = bot + h
                inv = bot
                l1 = 'BOX, %sM' % (o['spec'] or '')
            else:
                d = o['w']
                inv = o['el'] + 0.30
                ax.add_patch(Ellipse((xo, Y(inv + d / 2, x0)), d, d * vex, fill=False, ec=C_OBS, lw=0.8, zorder=5))
                top = inv + d
                l1 = '%s, D=%sMM' % (o['kind'], o['spec'] or '?')
            if not labels:
                continue
            ys = Y(top, x0)
            yl = max(ys + 6, (Y(gl, x0) if gl is not None else ys) + 18)
            lead.append([(xo, ys), (xo, yl)])
            for k2, s in enumerate((l1, 'INV.EL.%.2f' % inv, 'NO. %s' % _fmt_sta(xo).replace('NO. ', '').replace('+ ', '+'))):
                off = k2 * 2.7
                T.add(xo + 0.85 + off * math.cos(math.radians(45)), yl + 1.0 - off * math.sin(math.radians(45)),
                      s, h=2.2, rot=45, ha='left', va='bottom', color=C_OBS)
    if lead:
        ax.add_collection(LineCollection(lead, colors=C_LEAD, linewidths=0.6, zorder=3))
    ytop = max([max(p[1] for p in l) for l in lead] + [ytop_rul]) + 12
    if title:
        T.add(total / 2, ytop, title, h=5.0, ha='center', va='bottom')
    specs = T.flush(ax)
    ax.set_aspect('auto')          # 1:1 은 캔버스가 xlim 으로 맞춘다(_fit_height)
    ax.set_xlim(-35, total + 10)
    ax.set_ylim(-12, ytop + 10)
    ax.axis('off')
    return dict(Y=Y, datum=datum, ytop=ytop, breaks=breaks, texts=specs)
