"""웹 뷰어 걷기 충돌 (exporter/web_walk.js, node 로 실행): 벽에 막힘·미끄러짐, 계단·턱, 낙하·점프, 머리, 틈, 바닥 없음 + 템플릿 연결"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "exporter" / "web_walk.js"
NODE = shutil.which("node")
need_node = pytest.mark.skipif(NODE is None, reason="node 없음")

# 장면: 상자 [x0, x1, y0, y1, z0, z1, 이름]. 걷기 = [dx, dy, 걸음 수, dt] 목록, 결과 = 걸음 묶음마다 상태
HARNESS = """
const WalkCore = require(%s);
const inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const tris = [];
for (const [x0, x1, y0, y1, z0, z1, n] of inp.boxes) {
  const v = [[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],[x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]];
  for (const [a,b,c,d] of [[0,1,2,3],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]) { tris.push([v[a],v[b],v[c],n]); tris.push([v[a],v[c],v[d],n]); }
}
for (const t of inp.tris || []) tris.push(t);
const query = (x0,y0,z0,x1,y1,z1,cb) => { for (const [a,b,c,n] of tris) {
  if (Math.min(a[0],b[0],c[0])>x1||Math.max(a[0],b[0],c[0])<x0||Math.min(a[1],b[1],c[1])>y1||Math.max(a[1],b[1],c[1])<y0||Math.min(a[2],b[2],c[2])>z1||Math.max(a[2],b[2],c[2])<z0) continue;
  cb(...a, ...b, ...c, n); } };
const W = WalkCore(query);
const st = { x: inp.at[0], y: inp.at[1], foot: inp.at[2], vz: 0, grounded: inp.grounded !== false };
const out = [];
for (const [dx, dy, n, dt, jump] of inp.moves) {
  if (jump) W.jump(st);
  let head = null, blocked = null, top = -1e9;
  for (let i = 0; i < n; i++) { W.move(st, dx, dy, dt || 0.02, inp.opt); head = st.head || head; blocked = st.blocked !== null ? st.blocked : blocked; top = Math.max(top, st.foot); }
  out.push({ x: st.x, y: st.y, foot: st.foot, grounded: st.grounded, head, blocked, top });
}
console.log(JSON.stringify({ out, stands: inp.stands ? W.stands(...inp.stands) : null, R: W.R, H: W.H, STEP: W.STEP }));
"""


def run(boxes, at, moves, **kw):
    inp = dict(boxes=boxes, at=at, moves=moves, **kw)
    r = subprocess.run([NODE, "-e", HARNESS % json.dumps(str(JS))], input=json.dumps(inp).encode(), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode()
    return json.loads(r.stdout.decode())


FLOOR = [-20, 20, -20, 20, -0.5, 0.0, "바닥"]
WALL = [5, 5.2, -20, 20, 0, 4, "벽"]


@need_node
@pytest.mark.parametrize("step", [0.03, 0.1, 0.9])            # 걷기 · 달리기 · 느린 화면의 큰 걸음 (벽을 뚫지 않음)
def test_wall_blocks_and_slides(step):
    r = run([FLOOR, WALL], [0, 0, 0], [[step, 0, 300], [step * 0.7, step * 0.7, 10]])
    a, b = r["out"]
    assert a["x"] == pytest.approx(5 - r["R"], abs=2e-3) and a["y"] == pytest.approx(0, abs=1e-6) and a["blocked"] == "벽"
    assert b["x"] == pytest.approx(5 - r["R"], abs=2e-3) and b["y"] == pytest.approx(step * 7, rel=0.05)    # 벽을 따라 미끄러짐


@need_node
def test_inner_corner_and_column():
    r = run([FLOOR, WALL, [-20, 20, 3, 3.2, 0, 4, "벽2"]], [0, 0, 0], [[0.05, 0.04, 400]])
    assert (r["out"][0]["x"], r["out"][0]["y"]) == (pytest.approx(4.75, abs=5e-3), pytest.approx(2.75, abs=5e-3))
    r = run([FLOOR, [2, 2.6, -0.3, 0.3, 0, 4, "기둥"]], [0, 0.42, 0], [[0.05, 0, 400]])         # 모서리에 걸리면 옆으로 비켜 지나감
    assert r["out"][0]["x"] > 10


@need_node
def test_doorway_width():
    gap = lambda w: [FLOOR, [5, 5.2, w / 2, 20, 0, 4, "벽"], [5, 5.2, -20, -w / 2, 0, 4, "벽"]]
    assert run(gap(0.9), [0, 0, 0], [[0.05, 0, 300]])["out"][0]["x"] > 8                       # 문 폭 0.9 는 지나감
    assert run(gap(0.4), [0, 0, 0], [[0.05, 0, 300]])["out"][0]["x"] < 5                       # 몸(지름 0.5)보다 좁음


@need_node
@pytest.mark.parametrize("h, ok", [(0.18, True), (0.29, True), (0.35, False), (1.0, False)])
def test_step_height_limit(h, ok):
    r = run([FLOOR, [5, 20, -20, 20, 0, h, "턱"]], [0, 0, 0], [[0.05, 0, 200]])
    a = r["out"][0]
    if ok:
        assert a["x"] > 8 and a["foot"] == pytest.approx(h)
    else:
        assert a["x"] < 5 and a["foot"] == pytest.approx(0) and a["blocked"] == "턱"


@need_node
def test_stairs_up_and_down_follow_treads():
    rise, going, n = 0.175, 0.3, 20
    steps = [[2 + k * going, 2 + n * going + 5, -2, 2, 0, (k + 1) * rise, f"단{k}"] for k in range(n)]
    r = run([FLOOR] + steps, [0, 0, 0], [[0.06, 0, 160], [-0.18, 0, 60]])
    up, down = r["out"]
    assert up["foot"] == pytest.approx(n * rise) and up["grounded"]
    assert down["foot"] == pytest.approx(0) and down["grounded"] and down["x"] < 2              # 달려 내려와도 디딤판을 따라 (뜨지 않음)


@need_node
def test_fall_jump_and_no_floor():
    low = [FLOOR, [-20, 0, -20, 20, 0, 1.2, "승강장"]]
    r = run(low, [-2, 0, 1.2], [[0.06, 0, 60], [0, 0, 80]])
    assert r["out"][0]["x"] > 1 and r["out"][1]["foot"] == pytest.approx(0) and r["out"][1]["grounded"]        # 떨어짐
    up = run(low, [2, 0, 0], [[-0.06, 0, 100]])["out"][0]
    assert up["foot"] == pytest.approx(0) and up["x"] > 0                                       # 1.2m 는 못 올라감
    j = run([FLOOR], [0, 0, 0], [[0, 0, 60, 0.02, True]])["out"][0]
    assert 0.45 < j["top"] < 0.7 and j["grounded"] and j["foot"] == pytest.approx(0)
    ceil = run([FLOOR, [-5, 5, -5, 5, 2.0, 2.2, "천장"]], [0, 0, 0], [[0, 0, 60, 0.02, True]])["out"][0]
    assert ceil["top"] <= 0.3 + 1e-6                                                            # 점프해도 머리가 천장을 넘지 않음
    edge = run([[-5, 5, -5, 5, -0.5, 0, "판"]], [0, 0, 0], [[0.05, 0, 400]])["out"][0]          # 아래에 바닥이 전혀 없으면 끝에서 멈춤
    assert edge["x"] <= 5 + 0.13 and edge["foot"] == pytest.approx(0)


@need_node
def test_small_gap_is_crossed():
    """좁은 틈(0.1 — 카 문턱 등)은 빠지지 않고 지나감"""
    r = run([[-5, 2, -5, 5, -0.5, 0, "A"], [2.1, 9, -5, 5, -0.5, 0, "B"], [-9, 20, -9, 9, -9, -8, "바닥"]], [0, 0, 0], [[0.04, 0, 100]])
    assert r["out"][0]["x"] == pytest.approx(4, abs=0.01) and r["out"][0]["foot"] == pytest.approx(0)


@need_node
def test_head_blocks_and_reports():
    low = run([FLOOR, [5, 9, -20, 20, 1.6, 2.0, "막이"]], [0, 0, 0], [[0.05, 0, 200]])
    a = low["out"][0]
    assert a["x"] < 5 and a["head"]["tag"] == "막이" and a["head"]["clear"] == pytest.approx(1.6)
    ok = run([FLOOR, [5, 9, -20, 20, 1.75, 2.0, "막이"]], [0, 0, 0], [[0.05, 0, 200]])["out"][0]
    assert ok["x"] > 9 and ok["head"] is None
    # 경사 하면(계단 아래): 키 높이까지 들어가고 막힘
    slope = [[[2, -5, 4.0], [12, -5, 0.0], [12, 5, 0.0], "하부"], [[2, -5, 4.0], [12, 5, 0.0], [2, 5, 4.0], "하부"]]
    s = run([FLOOR], [0, 0, 0], [[0.05, 0, 300]], tris=slope)
    z = lambda x: 4.0 - (x - 2) * 0.4
    x = s["out"][0]["x"]
    assert z(x + 0.15) >= s["H"] - 0.05 and z(x + 0.15) < s["H"] + 0.1 and s["out"][0]["head"]["tag"] == "하부"


@need_node
def test_ride_keeps_height_and_stands():
    r = run([FLOOR], [0, 0, 2.0], [[0.05, 0, 10]], opt={"ride": True})["out"][0]                # 에스컬레이터 위: 높이는 밖에서 정함
    assert r["foot"] == pytest.approx(2.0) and r["x"] == pytest.approx(0.5)
    two = [FLOOR, [-5, 5, -5, 5, 3.0, 3.3, "중간 슬래브"], [-5, 5, -5, 5, 4.5, 4.8, "낮은 천장"]]
    s = run(two, [0, 0, 0], [], stands=[0, 0, -1, 10])["stands"]
    assert sorted(round(z, 6) for z, _ in s) == [0.0, 4.8]                                      # 3.3 은 머리 여유 1.2 라 못 섬


def test_template_is_wired(tmp_path):
    from engine.cad_engine import StationCADEngine
    from exporter.live_viewer import live_html
    from exporter.web_viewer import build_web_data
    from test_patch import make_cfg
    html = live_html()
    assert "/*__WALK__*/" not in html and "function WalkCore" in html and "WalkCore((x0" in html and 'id="collide"' in html
    eng = StationCADEngine(make_cfg())
    path = eng.generate_web(tmp_path / "v.html")
    text = open(path, encoding="utf-8").read()
    assert "/*__WALK__*/" not in text and "function WalkCore" in text and text.count("</script>") == text.count("<script>")
    assert build_web_data(eng)[0]["half_width"] == pytest.approx(eng.cfg.station.width / 2)
