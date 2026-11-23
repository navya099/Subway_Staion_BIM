"""웹 뷰어 에스컬레이터 애니메이션 자료: 코 선 표본 · 대표 스텝 · 운행 방향 · 묶음 태그.
뷰어(JS)의 배치 식을 그대로 옮긴 파이썬 식으로, 위상 0 의 배치 = 3D DXF 의 실제 스텝인지 독립 검증"""
import gzip
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from engine.cad_engine import StationCADEngine
from entrances.entrance_spec import EntranceSpec
from escalators.escalator_spec import EscalatorSpec
from exporter import esc_anim
from exporter.web_viewer import build_web_data
from test_entrances import FORE, _fin_cfg, cfg_with


def engine(curved=False, ts=(-5.6, -7.3), direction=1, ent=True, **fore):
    cfg = cfg_with({**FORE, **fore}, curved=True) if curved else _fin_cfg(**{**FORE, **fore})
    if not ent:
        cfg.entrances = []
    cfg.escalators = [EscalatorSpec(lower_floor=1, s_wp=60 if direction > 0 else 90, direction=direction, t_center=t) for t in ts]
    cfg.validate()
    return StationCADEngine(cfg)


def data_of(eng):
    data, packed = build_web_data(eng)
    return data, gzip.decompress(packed)


def interp(e, u):
    """뷰어 ESC.at: (점, 진행 방향, 왼쪽)"""
    f = min(max((u + e["dep"]) / e["du"], 0.0), len(e["path"]) - 1.000001)
    i = int(f)
    a, b = np.array(e["path"][i]), np.array(e["path"][i + 1])
    t = (b - a)[:2] / np.hypot(*(b - a)[:2])
    return a + (b - a) * (f - i), t, np.array([-t[1], t[0]])


def chunk_tris(data, buf, tag):
    """태그 묶음의 (부재 이름, 삼각형 (3, 3)) 목록"""
    out = []
    for c in data["chunks"]:
        if c.get("anim") != tag:
            continue
        pos = np.frombuffer(buf, np.float32, c["nv"] * 3, c["pos"]).reshape(-1, 3)
        idx = np.frombuffer(buf, np.uint32, c["nt"] * 3, c["idx"]).reshape(-1, 3)
        el = np.frombuffer(buf, np.uint32, c["nt"], c["elem"])
        out += [(data["elements"][k]["name"], pos[t]) for k, t in zip(el, idx)]
    return out


# ===================================================== 자료
def test_escalators_and_tags():
    data, buf = data_of(engine())
    assert [e["name"] for e in data["escs"]] == ["ES1", "ES2", "EN1_ESC"]
    for i, e in enumerate(data["escs"]):
        tris = chunk_tris(data, buf, f"E|{i}")
        assert {n for n, _ in tris} == set(e["steps"]) and len(e["steps"]) == e["n"]           # 스텝만, 빠짐없이
        for c in data["chunks"]:
            if c.get("anim") == f"E|{i}":
                assert c["layer"] == "STRUCT_ESCALATOR"
        u_end = -e["dep"] + e["du"] * (len(e["path"]) - 1)
        assert u_end == pytest.approx((e["n"] + 1) * e["dep"]) and e["du"] == pytest.approx(0.05, abs=0.003)
        assert np.hypot(*(np.array(e["path"][1]) - np.array(e["path"][0]))[:2]) == pytest.approx(e["du"], rel=2e-3)


def test_no_escalators():
    cfg = cfg_with(FORE)
    cfg.entrances = []
    data, _ = build_web_data(StationCADEngine(cfg))
    assert data["escs"] == [] and not any(str(c.get("anim", "")).startswith("E|") for c in data["chunks"])


@pytest.mark.parametrize("curved", [False, True])
@pytest.mark.parametrize("direction", [1, -1])
def test_phase_zero_reproduces_bim_steps(curved, direction):
    """대표 스텝을 코 선에 늘어놓은 위상 0 배치 = 실제 스텝 꼭짓점 (챌판 아래 끝은 아래 스텝 높이)"""
    data, buf = data_of(engine(curved=curved, direction=direction, ent=not curved))
    tol = 1.2e-2 if curved else 2.5e-3                                                         # 코 선 표본(0.05) 사이 직선 근사, 곡선은 호 근사
    for i, e in enumerate(data["escs"]):
        tris = {}
        for nm, t in chunk_tris(data, buf, f"E|{i}"):
            tris.setdefault(nm, []).append(t)
        m = e["template"]
        c0, t0, l0 = interp(e, m * e["dep"])
        local = [np.array([(p - c0)[:2] @ t0, (p - c0)[:2] @ l0, p[2] - c0[2]]) for t in tris[e["steps"][m]] for p in t]
        assert min(q[2] for q in local) < -e["plate"] - 1e-3                                  # 대표 스텝에는 챌판이 있음
        assert min(q[0] for q in local) == pytest.approx(0.0, abs=tol) and max(q[0] for q in local) == pytest.approx(e["dep"], abs=tol)
        for k, nm in enumerate(e["steps"]):
            u = k * e["dep"]
            zn = interp(e, u)[0][2]
            rise = max(e["plate"], zn - interp(e, u - e["dep"])[0][2])
            made = []
            for du, dt, dz in local:
                q, _, left = interp(e, min(max(u + du, 0.0), e["n"] * e["dep"]))
                made.append([*(q[:2] + left * dt), zn - rise if dz < -e["plate"] - 1e-3 else zn + dz])
            made = np.array(made)
            real = np.array([p for t in tris[nm] for p in t])
            far = max(np.min(np.linalg.norm(made - p, axis=1)) for p in real)                  # 실제 꼭짓점마다 배치한 꼭짓점이 있음
            assert far < tol, (e["name"], k, far)


def test_steps_stay_on_nose_line_while_moving():
    """움직이는 동안: 이웃 스텝 디딤판이 수평 간격 dep 로 이어지고(빈틈 없음), 범위 [0, n·dep] 을 정확히 채움"""
    data, _ = data_of(engine(ent=False))
    e = data["escs"][0]
    for ph in (0.0, 0.25, 0.6, 0.99):
        spans = [(max(0.0, (s - 1 + ph) * e["dep"]), min(e["n"] * e["dep"], (s + ph) * e["dep"])) for s in range(e["n"] + 1)]
        spans = [(a, b) for a, b in spans if b - a > 1e-9]
        assert spans[0][0] == 0.0 and spans[-1][1] == pytest.approx(e["n"] * e["dep"])
        assert all(a1 == pytest.approx(b0) for (_, b0), (a1, _) in zip(spans, spans[1:]))


# ===================================================== 운행 방향 (나란하면 오른쪽 상행 · 왼쪽 하행)
@pytest.mark.parametrize("direction", [1, -1])
def test_parallel_pair_alternates_right_up(direction):
    data, _ = data_of(engine(direction=direction, ent=False))
    d = {e["name"]: e["dir"] for e in data["escs"]}
    # +s 로 오르면 왼쪽 = +t → 오른쪽은 t 가 작은 ES2(−7.3); −s 로 오르면 반대
    assert d == ({"ES1": -1, "ES2": 1} if direction > 0 else {"ES1": 1, "ES2": -1})


def test_far_or_single_escalators_go_up():
    a, _ = data_of(engine(ts=(-6.5,), ent=False))
    assert [e["dir"] for e in a["escs"]] == [1]
    eng = engine(ts=(-6.5, 6.5), ent=False)
    assert [e["dir"] for e in esc_anim.build(_meshed(eng))[0]] == [1, 1]                       # 멀리 떨어짐 (승강장 양쪽)


def _meshed(eng):
    eng.build_3d_doc()
    return eng


def test_entrance_escalators_alternate():
    data, buf = data_of(engine(ts=(), escalator_count=3))
    es = [e for e in data["escs"] if e["name"].startswith("EN1")]
    assert len(es) == 3 and sorted(e["dir"] for e in es) == [-1, 1, 1]
    mids = [np.array(e["path"][0])[:2] for e in es]
    left = interp(es[0], 0.0)[2]
    order = sorted(range(3), key=lambda k: mids[k] @ left)                                      # 오른쪽(왼쪽 좌표가 작은 쪽)부터
    assert [es[k]["dir"] for k in order] == [1, -1, 1]
    assert isinstance(EntranceSpec().escalator_count, int)


def test_template_has_controls():
    from exporter.web_viewer import TEMPLATE
    html = TEMPLATE.read_text(encoding="utf-8")
    for s in ('id="escrun"', 'id="escup"', 'id="escdn"', 'id="escstop"', "const ESC = (function", "ESC.load();", "ESC.step(dt);"):
        assert s in html
