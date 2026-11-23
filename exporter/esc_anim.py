"""웹 뷰어 에스컬레이터 애니메이션 자료 (정거장 안 · 출입구 공통).

스텝은 수평 간격(스텝 깊이)이 같은 같은 모양이므로, 뷰어는 스텝 하나의 형상(대표 스텝 = 챌판이 있는 경사부 스텝, 3D DXF 그대로)을
스텝 코 선 N(u) 을 따라 늘어놓고 한 칸(스텝 깊이) 안에서 되풀이해 옮긴다 — 위치 0 이면 3D DXF 의 스텝과 같음.
- path: 코 선 표본 [x, y, z] (스텝 폭 가운데, u = lo − dep ~ hi + dep, 간격 du), 세계 좌표
- 스텝 j 의 코 u = lo + (j + 위상) · dep, 디딤판 윗면 N(u), 챌판 아래 끝 = N(u − dep), 스텝 범위 [lo, hi] 밖은 잘림(콤 아래)
- dir: 처음 운행 방향 (+1 상행 / −1 하행). 나란한 에스컬레이터는 오르는 방향을 볼 때 오른쪽부터 상행·하행 번갈아 (우측 통행)
"""
from escalators.escalator_spec import STEP_PLATE_T

DU = 0.05                    # 코 선 표본 간격 (u, m) — 곡선 전이부 표본과 같음
GROUP_GAP = 1.0              # 이 거리 안에 나란하면 한 묶음 (방향 번갈아)


def _items(engine) -> list:
    """[(EscalatorData, 코 선 N(u), 스텝 깊이, 묶음 키, 좌우 좌표(오르는 방향 왼쪽 +), 진행 범위, u → 세계 (x, y))]"""
    out = []
    se = getattr(engine, "escalators", None)
    cfg = engine.cfg
    for esc in (se.all_escalators() if se is not None else []):
        lay = se._layouts.get(esc.name)
        if lay is None or not esc.steps:
            continue
        sp, tc = lay.spec, lay.spec.t_center
        out.append((esc, lay.nose, sp.step_depth, ("S", sp.lower_floor, sp.direction), tc * sp.direction, sp.truss_width,
                    lay.s_range, lambda u, lay=lay, tc=tc: cfg.to_world(lay.s_at(u), tc)))
    en = getattr(engine, "entrances", None)
    for ent in (en.entrances if en is not None else []):
        for esc, le in zip(ent.escalators, ent.layout.escalators):
            if not esc.steps:
                continue
            tc = le.spec.t_center
            out.append((esc, le.nose, le.spec.step_depth, ("E", ent.name), tc, le.spec.truss_width, esc.s_range,
                        lambda u, le=le, tc=tc, fr=ent.frame: fr.to_world(le.u_wp + u, tc)))
    return out


def _directions(items) -> list:
    """나란한 묶음(같은 키, 진행 범위 겹침, 사이 ≤ GROUP_GAP)마다 오른쪽부터 +1, −1 번갈아"""
    dirs = [1] * len(items)
    order = sorted(range(len(items)), key=lambda i: (str(items[i][3]), items[i][4]))
    prev = None
    for i in order:
        if prev is not None:
            a, b = items[prev], items[i]
            near = b[4] - a[4] - (a[5] + b[5]) / 2.0 <= GROUP_GAP
            over = min(a[6][1], b[6][1]) - max(a[6][0], b[6][0]) > 0
            if a[3] == b[3] and near and over:
                dirs[i] = -dirs[prev]
        prev = i
    return dirs


def build(engine) -> tuple:
    """(escs 자료(세계 좌표), {스텝 3DFACE 핸들: 태그 'E|순번'}). build_3d_doc 뒤에 부를 것"""
    items = _items(engine)
    escs, tags = [], {}
    for i, ((esc, nose, dep, *_, xy), d) in enumerate(zip(items, _directions(items))):
        steps = sorted(esc.steps, key=lambda s: s.index)
        n, lo = len(steps), steps[0].chain_u
        for s in steps:
            for ent in s.source_element or []:
                tags[ent.dxf.handle] = f"E|{i}"
        rises = [nose(s.chain_u) - nose(s.chain_u - dep) for s in steps]
        m = min((k for k in range(n) if rises[k] > max(rises) - 1e-6), key=lambda k: abs(k - n / 2.0))
        cnt = int(round((n + 2) * dep / DU)) + 1
        du = (n + 2) * dep / (cnt - 1)
        path = []
        for k in range(cnt):
            u = lo - dep + k * du
            x, y = xy(u)
            path.append([x, y, nose(u)])
        t0, t1 = steps[0].t_range
        escs.append({"name": esc.name, "dep": dep, "n": n, "du": du, "path": path, "width": t1 - t0, "plate": STEP_PLATE_T,
                     "template": m, "steps": [s.name for s in steps], "dir": d})
    return escs, tags
