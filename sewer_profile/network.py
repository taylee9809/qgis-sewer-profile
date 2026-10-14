# -*- coding: utf-8 -*-
"""노선 레이어 → 관로 그래프 → 분기점 기준 구간(run) 트리, 종단 데이터.

QGIS 객체는 읽기에만 쓰고 계산은 순수 파이썬으로 한다(테스트하기 쉽게).
"""
import math
import re

# 필드 이름 후보 — 앞에서부터 레이어에 있는 것을 쓴다
PIPE_FIELDS = {
    'name': ['관번호', 'pipe_id', 'name'],
    'il_up': ['상류관저고', 'il_up'],
    'il_dn': ['하류관저고', 'il_dn'],
    'dia': ['관경', 'dia_mm'],
    'gl_up': ['상류지반고', 'gl_up'],
    'kind': ['구분', 'kind'],
    'obs': ['종단지장물', 'obstacles'],
    'judge': ['금회_수리판정', '수리판정'],
    'judge_w': ['수리판정'],
    'zone': ['지구'],
    'slope': ['경사퍼밀'],
    'flow': ['금회_누가유량_m3d', '누가유량_m3d'],
    'vel': ['금회_실유속_mps', '실유속_mps'],
}
MH_FIELDS = {
    'name': ['맨홀번호', 'name'],
    'gl': ['지반고', 'gl'],
    'kind': ['구분'],
    'type': ['맨홀호수', '맨홀규격'],
}

SNAP = 0.05   # 끝점 동일 판정(m)


def pick_fields(layer, cands):
    names = set(f.name() for f in layer.fields())
    return {k: next((c for c in v if c in names), None) for k, v in cands.items()}


def _num(v):
    try:
        if v is None:
            return None
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _polyline(geom):
    """QgsGeometry → [(x, y), ...] (멀티파트는 이어붙임)"""
    if geom is None or geom.isEmpty():
        return []
    if geom.isMultipart():
        out = []
        for part in geom.asMultiPolyline():
            pts = [(p.x(), p.y()) for p in part]
            if out and pts and math.dist(out[-1], pts[0]) < SNAP:
                pts = pts[1:]
            out += pts
        return out
    return [(p.x(), p.y()) for p in geom.asPolyline()]


OBS_RE = re.compile(r'^\s*(?P<kind>.*?)(?:\s+D(?P<spec>[\d.]+(?:\s*[xX×]\s*[\d.]+)?))?\s*@\s*(?P<sta>-?[\d.]+)\s*\(\s*(?:EL)?\s*(?P<el>-?[\d.]+)\s*\)\s*$')


def parse_obstacles(text):
    """'횡배수관 D600@13.3(74.70) / BOX D2.00X1.00@3.3(25.50)' → [dict]
    측점은 관 시점(상류맨홀)부터 m, el 은 flo 저면EL(원형관은 관저 −0.30 규약)."""
    out = []
    if not text:
        return out
    for tok in str(text).split('/'):
        m = OBS_RE.match(tok)
        if not m:
            continue
        spec = m.group('spec')
        w = h = None
        shape = 'circle'
        if spec:
            mm = re.match(r'([\d.]+)\s*[xX×]\s*([\d.]+)', spec)
            if mm:
                shape = 'rect'
                w, h = float(mm.group(1)), float(mm.group(2))
            else:
                d = float(spec)
                w = h = d / 1000.0 if d > 20 else d
        kind = m.group('kind').strip() or '지장물'
        if shape == 'circle' and w is None:
            w = h = 0.3
        out.append(dict(kind=kind, spec=spec, sta=float(m.group('sta')), el=float(m.group('el')),
                        shape=shape, w=w, h=h))
    return out


class Pipe(object):
    __slots__ = ('fid', 'name', 'pts', 'length', 'il_up', 'il_dn', 'd', 'gl_up', 'kind', 'obs',
                 'judge', 'judge_w', 'zone', 'slope', 'flow', 'vel', 'a', 'b')


def read_pipes(layer, expression=None):
    from qgis.core import QgsFeatureRequest
    F = pick_fields(layer, PIPE_FIELDS)
    req = QgsFeatureRequest()
    if expression:
        req.setFilterExpression(expression)
    pipes = {}
    for f in layer.getFeatures(req):
        pts = _polyline(f.geometry())
        if len(pts) < 2:
            continue
        p = Pipe()
        p.fid = f.id()
        g = lambda k: f[F[k]] if F[k] else None
        p.name = str(g('name') if g('name') not in (None, '') else 'fid%d' % f.id())
        p.pts = pts
        p.length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        p.il_up, p.il_dn = _num(g('il_up')), _num(g('il_dn'))
        dmm = _num(g('dia'))
        p.d = (dmm / 1000.0 if dmm and dmm > 20 else dmm) or 0.2
        p.gl_up = _num(g('gl_up'))
        p.kind = str(g('kind') or '')
        p.obs = parse_obstacles(g('obs'))
        p.judge = g('judge')
        p.judge_w = g('judge_w')
        p.zone = g('zone')
        p.slope, p.flow, p.vel = _num(g('slope')), _num(g('flow')), _num(g('vel'))
        pipes[p.fid] = p
    return pipes


class _Snap(object):
    """끝점 군집 — SNAP 거리 안이면 같은 노드"""

    def __init__(self, tol):
        self.tol, self.cells, self.xy = tol, {}, []

    def key(self, x, y):
        cx, cy = int(math.floor(x / self.tol)), int(math.floor(y / self.tol))
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for k in self.cells.get((cx + i, cy + j), ()):
                    if math.dist(self.xy[k], (x, y)) <= self.tol:
                        return k
        k = len(self.xy)
        self.xy.append((x, y))
        self.cells.setdefault((cx, cy), []).append(k)
        return k


class Network(object):
    def __init__(self, pipes):
        self.pipes = pipes
        sn = _Snap(SNAP)
        for p in pipes.values():
            p.a = sn.key(*p.pts[0])
            p.b = sn.key(*p.pts[-1])
        self.node_xy = sn.xy
        self.out = {}
        self.inn = {}
        for p in pipes.values():
            self.out.setdefault(p.a, []).append(p.fid)
            self.inn.setdefault(p.b, []).append(p.fid)
        self._build_runs()

    def _is_break(self, n):
        return len(self.inn.get(n, ())) != 1 or len(self.out.get(n, ())) != 1

    def _build_runs(self):
        self.runs = []          # [dict(id, pipes[fid..], start, end, parent, children, length)]
        self.run_of = {}
        seen = set()
        starts = [p.fid for p in self.pipes.values() if self._is_break(p.a)]
        rest = [fid for fid in self.pipes if fid not in starts]
        for fid in starts + rest:
            if fid in seen:
                continue
            seq = []
            cur = fid
            while cur is not None and cur not in seen:
                seen.add(cur)
                seq.append(cur)
                n = self.pipes[cur].b
                if self._is_break(n):
                    break
                cur = self.out[n][0]
            rid = len(self.runs)
            self.runs.append(dict(id=rid, pipes=seq, start=self.pipes[seq[0]].a, end=self.pipes[seq[-1]].b,
                                  parent=None, children=[],
                                  length=sum(self.pipes[i].length for i in seq)))
            for i in seq:
                self.run_of[i] = rid
        for r in self.runs:
            nxt = self.out.get(r['end'])
            if nxt:
                pr = self.run_of[nxt[0]]
                if pr != r['id']:
                    r['parent'] = pr
                    self.runs[pr]['children'].append(r['id'])
        # 상류 총연장(본선 판정·정렬용)
        memo = {}

        def up_len(rid, stack=()):
            if rid in stack:          # 순환 방어
                return 0.0
            if rid not in memo:
                memo[rid] = self.runs[rid]['length'] + max(
                    [up_len(c, stack + (rid,)) for c in self.runs[rid]['children']] or [0])
            return memo[rid]
        for r in self.runs:
            r['up_length'] = up_len(r['id'])
        for r in self.runs:
            r['children'].sort(key=lambda c: -self.runs[c]['up_length'])

    def roots(self):
        return sorted((r for r in self.runs if r['parent'] is None), key=lambda r: -r['up_length'])

    def run_label(self, r):
        a = self.pipes[r['pipes'][0]].name
        b = self.pipes[r['pipes'][-1]].name
        return a if a == b else '%s → %s' % (a, b)

    def downstream_chain(self, rid):
        """rid 부터 방류까지 구간 id 목록"""
        out = []
        while rid is not None and rid not in out:
            out.append(rid)
            rid = self.runs[rid]['parent']
        return out

    def main_upstream(self, rid):
        """rid 의 상류 본선(상류연장 최대 자식) 을 끝까지 — 상류→하류 순"""
        out = [rid]
        while self.runs[out[-1]]['children']:
            out.append(self.runs[out[-1]]['children'][0])
        return out[::-1]

    def order_runs(self, rids):
        """선택된 구간들이 상하류로 이어지면 상류→하류 순 정렬, 아니면 None"""
        rids = list(dict.fromkeys(rids))
        s = set(rids)
        heads = [r for r in rids if not any(c in s for c in self.runs[r]['children'])]
        if len(heads) != 1:
            return None
        seq, cur = [], heads[0]
        while cur is not None and cur in s:
            seq.append(cur)
            cur = self.runs[cur]['parent']
        return seq if len(seq) == len(rids) else None


class Profile(object):
    """상류→하류 관 목록으로 만든 종단 데이터.
    path: 노선 좌표열(레이어 CRS), cum: 각 정점 누가거리"""

    def __init__(self, net, fids, manholes=None):
        self.pipes = [net.pipes[i] for i in fids]
        self.path, self.cum, self.seg = [], [], []   # seg: 각 관의 (x0, x1)
        x = 0.0
        for p in self.pipes:
            pts = p.pts
            if self.path and math.dist(self.path[-1], pts[0]) < SNAP:
                pts = pts[1:]
            else:
                if self.path:          # 끊긴 경우 — 이어붙이되 길이는 더하지 않음
                    pass
            for q in pts:
                if self.path:
                    x += math.dist(self.path[-1], q)
                self.path.append(q)
                self.cum.append(x)
            self.seg.append((x - p.length, x))
        self.total = x
        # 노드(맨홀) — 각 관 시점 + 마지막 종점
        self.nodes = []
        for i, p in enumerate(self.pipes):
            x0 = self.seg[i][0]
            il_in = self.pipes[i - 1].il_dn if i > 0 else None
            self.nodes.append(dict(x=x0, xy=p.pts[0], name=p.name, gl=p.gl_up, il_in=il_in, il_out=p.il_up))
        last = self.pipes[-1]
        self.nodes.append(dict(x=self.total, xy=last.pts[-1], name='', gl=None, il_in=last.il_dn, il_out=None))
        if manholes:
            for n in self.nodes:
                mh = manholes.near(n['xy'], 1.5)
                if mh:
                    n['name'] = mh['name'] or n['name']
                    if mh.get('gl') is not None and (n['gl'] is None or n is self.nodes[-1]):
                        n['gl'] = mh['gl']
                    n['mh'] = True
                    n['mh_kind'] = str(mh.get('type') or mh.get('kind') or '')
                else:
                    n['mh'] = n is not self.nodes[-1] and not (self._is_sub(n['name']))
        else:
            for n in self.nodes:
                n['mh'] = not self._is_sub(n['name'])
        self.ground = [(n['x'], n['gl']) for n in self.nodes if n['gl'] is not None]

    @staticmethod
    def _is_sub(name):
        # 압송 중간절점(OHG-A-00601 처럼 5자리 이상 일련번호)
        return bool(re.search(r'-\d{5,}$', name or ''))

    def locate(self, s):
        """누가거리 → (x, y)"""
        s = max(0.0, min(s, self.total))
        for i in range(1, len(self.cum)):
            if self.cum[i] >= s:
                a, b = self.path[i - 1], self.path[i]
                L = self.cum[i] - self.cum[i - 1]
                t = 0 if L == 0 else (s - self.cum[i - 1]) / L
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return self.path[-1]

    def project(self, x, y):
        """점 → (누가거리, 이격)"""
        best = (None, 1e18)
        for i in range(1, len(self.path)):
            (ax, ay), (bx, by) = self.path[i - 1], self.path[i]
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = 0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
            px, py = ax + dx * t, ay + dy * t
            d = math.hypot(x - px, y - py)
            if d < best[1]:
                best = (self.cum[i - 1] + t * math.sqrt(L2), d)
        return best

    def pipe_at(self, s):
        for i, (x0, x1) in enumerate(self.seg):
            if x0 - 1e-6 <= s <= x1 + 1e-6:
                return i
        return len(self.seg) - 1

    def ground_at(self, s):
        g = self.ground
        if not g:
            return None
        if s <= g[0][0]:
            return g[0][1]
        for (x0, y0), (x1, y1) in zip(g, g[1:]):
            if x0 <= s <= x1:
                return y0 if x1 == x0 else y0 + (y1 - y0) * (s - x0) / (x1 - x0)
        return g[-1][1]

    def dem_at(self, s):
        d = getattr(self, 'dem', None)
        if not d:
            return None
        for (x0, y0), (x1, y1) in zip(d, d[1:]):
            if x0 <= s <= x1:
                return y0 if x1 == x0 else y0 + (y1 - y0) * (s - x0) / (x1 - x0)
        return d[-1][1] if s > d[-1][0] else d[0][1]

    def invert_at(self, s):
        i = self.pipe_at(s)
        p = self.pipes[i]
        x0, x1 = self.seg[i]
        if p.il_up is None or p.il_dn is None:
            return i, None
        t = 0 if x1 == x0 else (s - x0) / (x1 - x0)
        return i, p.il_up + (p.il_dn - p.il_up) * t


class Manholes(object):
    def __init__(self, layer):
        F = pick_fields(layer, MH_FIELDS)
        self.items = []
        for f in layer.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            c = g.centroid().asPoint()
            self.items.append(dict(xy=(c.x(), c.y()), name=str(f[F['name']]) if F['name'] and f[F['name']] else '',
                                   gl=_num(f[F['gl']]) if F['gl'] else None,
                                   kind=f[F['kind']] if F['kind'] else None,
                                   type=f[F['type']] if F['type'] else None))
        self.cell = {}
        for k, it in enumerate(self.items):
            self.cell.setdefault((int(it['xy'][0] // 10), int(it['xy'][1] // 10)), []).append(k)

    def near(self, xy, tol):
        cx, cy = int(xy[0] // 10), int(xy[1] // 10)
        best = None
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for k in self.cell.get((cx + i, cy + j), ()):
                    d = math.dist(self.items[k]['xy'], xy)
                    if d <= tol and (best is None or d < best[0]):
                        best = (d, self.items[k])
        return best[1] if best else None
