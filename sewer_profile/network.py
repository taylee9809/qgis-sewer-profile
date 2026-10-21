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
    'ftype': ['자연유하/압송'],
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


def short_range(a, b):
    """관번호 두 개를 공통 접두로 묶는다.
    MS-A-018, MS-A-028 → MS-A-018~028 / ODS-101-001, ODS-101-00505 → ODS-101-001~00505
    MS-A2-001, MS-A-028 → MS-A2-001~A-028 / 접두가 다르면 'a ~ b'"""
    if a == b:
        return a
    ta, tb = a.split('-'), b.split('-')
    k = 0
    while k < min(len(ta), len(tb)) - 1 and ta[k] == tb[k]:
        k += 1
    if k == 0:
        return '%s ~ %s' % (a, b)
    return '%s~%s' % (a, '-'.join(tb[k:]))


class Pipe(object):
    __slots__ = ('fid', 'name', 'pts', 'length', 'il_up', 'il_dn', 'd', 'gl_up', 'kind', 'obs',
                 'judge', 'judge_w', 'zone', 'slope', 'flow', 'vel', 'a', 'b', 'ftype', 'asb')


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
        p.ftype = str(g('ftype') or '')
        p.asb = p.kind.strip() == '기존'          # 노선에 편입된 준공관(구분=기존)은 기존관으로 표시
        pipes[p.fid] = p
    return pipes


JOIN_TOL = 1.5   # 다른 레이어 관 시점에 말단을 잇는 허용(m) — 준공 좌표가 1 m 안팎 밀린 지구가 있다(마사)
DUP_TOL = 0.5    # 다른 레이어에 같은 관(양 끝 일치)이 있으면 중복으로 본다
LAYER_STEP = 10000000


def net_fid(k, fid):
    """k 번째 레이어의 fid → 망 안의 fid (첫 레이어는 그대로, 나머지는 음수로 겹치지 않게)"""
    return fid if k == 0 else -(k * LAYER_STEP + fid + 1)


def merge_layers(layers):
    """여러 노선 레이어의 관을 한 망으로 합친다.

    layers: [(레이어id, {fid: Pipe}, 기존관레이어여부)] — 앞 레이어가 우선(중복이면 앞 것을 남김).
    · 중복: 양 끝이 DUP_TOL 안에서 일치하는 관은 뒤 레이어 것을 버리고 앞 관으로 대응시킨다.
    · 접속: 하류로 이어지는 관이 없는 말단은, 다른 레이어 관의 시점이 JOIN_TOL 안에 있으면 그 시점으로
      말단 좌표를 옮겨 잇는다(메모리에서만 — 레이어는 그대로).
    반환: (pipes, info) — info['fidmap'] = {(레이어id, fid): 망fid}"""
    out, fidmap, src, dup, joins = {}, {}, {}, 0, []
    for k, (lid, pipes, existing) in enumerate(layers):
        kept = list(out.values())
        for p in pipes.values():
            a, b = p.pts[0], p.pts[-1]
            m = next((q for q in kept if math.dist(a, q.pts[0]) < DUP_TOL and math.dist(b, q.pts[-1]) < DUP_TOL), None)
            if m is not None:
                fidmap[(lid, p.fid)] = m.fid
                dup += 1
                continue
            nf = net_fid(k, p.fid)
            fidmap[(lid, p.fid)] = nf
            p.fid = nf
            p.pts = list(p.pts)
            if existing:
                p.asb = True
                p.kind = '기존 ' + ('압송' if '압송' in (p.ftype or '') + (p.kind or '') else '자연유하')
                p.judge = p.judge_w = None
            out[nf] = p
            src[nf] = k
    sn = _Snap(SNAP)
    has_out = set(sn.key(*p.pts[0]) for p in out.values())
    starts = [(p.pts[0], p) for p in out.values()]
    for p in out.values():
        e = p.pts[-1]
        if sn.key(*e) in has_out:
            continue
        best = None
        for s, q in starts:
            if src[q.fid] == src[p.fid] or q is p:
                continue
            d = math.dist(e, s)
            if d <= JOIN_TOL and (best is None or d < best[0]):
                best = (d, q)
        if best is None:
            continue
        q = best[1]
        joins.append((p.name, q.name, round(best[0], 3)))
        p.pts = p.pts[:-1] + [q.pts[0]]
        p.length = sum(math.dist(a, b) for a, b in zip(p.pts, p.pts[1:]))
    return out, dict(fidmap=fidmap, dup=dup, joins=joins)


def downstream_closure(pipes, seeds):
    """seeds(망fid) 와 그 하류로 방류까지 이어지는 관 전부"""
    sn = _Snap(SNAP)
    out_of = {}
    for p in pipes.values():
        out_of.setdefault(sn.key(*p.pts[0]), []).append(p.fid)
    keep, stack = set(), [f for f in seeds if f in pipes]
    while stack:
        f = stack.pop()
        if f in keep:
            continue
        keep.add(f)
        stack += out_of.get(sn.key(*pipes[f].pts[-1]), [])
    return keep


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

    def run_short(self, r):
        """'MS-A-018' ~ 'MS-A-028' → 'MS-A-018~028' (공통 접두 토큰은 한 번만)"""
        return short_range(self.pipes[r['pipes'][0]].name, self.pipes[r['pipes'][-1]].name)

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
        """선택된 구간들이 한 하류 경로 위에 있으면 가장 상류 것부터 가장 하류 것까지
        (사이에 끼인 구간 포함) 상류→하류 순으로, 아니면 None"""
        s = set(rids)
        for r in s:
            chain = self.downstream_chain(r)
            if s <= set(chain):
                return chain[:max(chain.index(x) for x in s) + 1]
        return None


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
            # 준공(기존) 관 구간 맨홀은 준공 맨홀 레이어(뒤 순번) 이름을 먼저 — 같은 자리에 계획맨홀이 있으면
            # 계획 이름(MS-A-027·우림식 MS-G-014 등)이 준공 이름(MS08·MS-G-013)을 덮던 문제 (261021)
            asb_rank = manholes.nranks - 1 if manholes.nranks > 1 else None
            for k, n in enumerate(self.nodes):
                p = self.pipes[min(k, len(self.pipes) - 1)]
                pref = asb_rank if getattr(p, 'asb', False) else (0 if asb_rank is not None else None)
                mh = manholes.near(n['xy'], 1.5, pref)
                if mh:
                    n['name'] = mh['name'] or n['name']
                    if mh.get('gl') is not None and (n['gl'] is None or n is self.nodes[-1]):
                        n['gl'] = mh['gl']
                    n['mh'] = True
                    n['mh_kind'] = str(mh.get('type') or mh.get('kind') or '')
                    k = self.nodes.index(n)
                    p = self.pipes[min(k, len(self.pipes) - 1)]
                    if getattr(p, 'asb', False) and '펌프' not in n['mh_kind'] and '기존' not in n['mh_kind']:
                        n['mh_kind'] = '기존 ' + n['mh_kind']      # 기존관 구간 맨홀은 '1호기존'으로
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
    """맨홀 레이어(하나 또는 여러 개). 여러 개면 앞 레이어가 우선 — 같은 자리(허용거리 안)에
    두 레이어 맨홀이 다 있으면 앞 레이어 것을 쓴다."""

    def __init__(self, layers):
        if not isinstance(layers, (list, tuple)):
            layers = [layers]
        self.items = []
        for rank, layer in enumerate(layers):
            F = pick_fields(layer, MH_FIELDS)
            for f in layer.getFeatures():
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue
                c = g.centroid().asPoint()
                self.items.append(dict(xy=(c.x(), c.y()), name=str(f[F['name']]) if F['name'] and f[F['name']] else '',
                                       gl=_num(f[F['gl']]) if F['gl'] else None,
                                       kind=f[F['kind']] if F['kind'] else None,
                                       type=f[F['type']] if F['type'] else None, rank=rank))
        self.cell = {}
        for k, it in enumerate(self.items):
            self.cell.setdefault((int(it['xy'][0] // 10), int(it['xy'][1] // 10)), []).append(k)

    def near(self, xy, tol, pref=None):
        """pref: 먼저 쓸 레이어 순번(없으면 앞 레이어 우선). 준공 관 구간은 준공 맨홀 이름을 쓰려고."""
        cx, cy = int(xy[0] // 10), int(xy[1] // 10)
        best = None
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for k in self.cell.get((cx + i, cy + j), ()):
                    it = self.items[k]
                    d = math.dist(it['xy'], xy)
                    key = ((it['rank'] != pref) if pref is not None else it['rank'], d)
                    if d <= tol and (best is None or key < best[0]):
                        best = (key, it)
        return best[1] if best else None

    @property
    def nranks(self):
        return 1 + max((it['rank'] for it in self.items), default=0)
