"""3D 웹 뷰어 (three.js, HTML 한 파일).

기하는 3D DXF 문서(StationCADEngine.build_3d_doc)의 3DFACE 그대로 (미리보기·3D DXF·DAE 와 같은 단일 원천).
three.js(assets/web/three.min.js, MIT)와 모델 자료를 HTML 한 파일에 넣어 인터넷 없이 브라우저로 연다.

자료 (모두 정수 원점 기준 상대 좌표):
- 묶음(레이어 × 보기 재질)마다 꼭짓점 위치(float32 ×3), 정거장 로컬 s·FL 기준 높이 h(float32 ×2, 잘라 보기),
  삼각형 꼭짓점 번호(uint32 ×3), 삼각형 → 부재 번호(uint32) — 한 바이트 열로 이어 gzip + base64
  (브라우저 DecompressionStream 으로 풂)
- 부재 표: 이름·레이어·층·재질·종류 (클릭 정보)
- 표시 묶음(미리보기와 같은 LAYER_GROUPS), 층(이름, 천장 하면 h, FL h), 선형 중심 표본(1m: s, x, y, FL 표고 — 걷기 높이)
"""
import base64
import dataclasses
import gzip
import json
from pathlib import Path

import numpy as np

from exporter.render_material import finish_material, layer_material
from preview.preview_render import LAYER_GROUPS, station_of
from rooms.room_layout import ceiling_rel

THREE_JS = Path(__file__).resolve().parent.parent / "assets" / "web" / "three.min.js"
TEMPLATE = Path(__file__).resolve().parent / "web_viewer_template.html"
SKIP_LAYERS = {"FIN_FRAME"}          # 천장틀: 면이 매우 많고 천장판에 가림 (frames=True 로 포함)


@dataclasses.dataclass
class WebResult:
    path: str
    origin: tuple
    triangles: int = 0
    elements: int = 0
    size: int = 0                     # HTML 바이트 수


def _element_index(engine) -> dict:
    """3DFACE 핸들 → (이름, 층, 재질, 종류) — 서브 엔진의 BIM 객체(source_element 를 가진 것)를 모두 훑음"""
    out, seen = {}, set()

    def visit(obj, depth):
        if depth > 6 or id(obj) in seen or obj is None or isinstance(obj, (str, int, float, bool, bytes)):
            return
        seen.add(id(obj))
        src = getattr(obj, "source_element", None)
        if isinstance(src, list) and src and hasattr(src[0], "dxf"):
            info = (str(getattr(obj, "name", "") or ""), str(getattr(obj, "level", "") or ""),
                    str(getattr(obj, "material", "") or ""), str(getattr(obj, "type_name", "") or ""))
            for ent in src:
                out.setdefault(ent.dxf.handle, info)
        if isinstance(obj, (list, tuple)):
            for x in obj:
                visit(x, depth + 1)
        elif isinstance(obj, dict):
            for x in obj.values():
                visit(x, depth + 1)
        elif dataclasses.is_dataclass(obj) or hasattr(obj, "__dict__"):
            for k, v in vars(obj).items():
                if k in ("cfg", "config", "sp", "source_element", "shape") or k.startswith("_"):
                    continue
                if isinstance(v, (list, tuple, dict)) or dataclasses.is_dataclass(v):
                    visit(v, depth + 1)
    for e in engine.sub_engines:
        visit(e, 0)
    return out


def _group_of(layer: str) -> str:
    for name, layers, _ in LAYER_GROUPS:
        if layer in layers:
            return name
    return "기타"


def build_web_data(engine, frames: bool = False) -> tuple:
    """(자료 dict, 압축 바이트) — HTML 에 넣을 모델 자료"""
    cfg = engine.cfg
    st = cfg.station
    doc = engine.build_3d_doc()
    mat_of = {}
    tactile = getattr(engine, "tactiles", None)
    for e in engine.finishes.all_elements() + (tactile.elements if tactile is not None else []):
        m = finish_material(e.material)
        for ent in e.source_element or []:
            mat_of[ent.dxf.handle] = m
    elem_of = _element_index(engine)
    skip = set() if frames else SKIP_LAYERS

    chunks = {}                                          # (레이어, 재질 이름) → [꼭짓점 목록, 부재 번호]
    mats = {}
    elems, elem_id = [], {}
    first = None
    for ent in doc.modelspace().query("3DFACE"):
        d = ent.dxf
        if d.layer in skip:
            continue
        v = [tuple(d.vtx0), tuple(d.vtx1), tuple(d.vtx2), tuple(d.vtx3)]
        if v[3] == v[2]:
            v = v[:3]
        if first is None:
            first = v[0]
        m = mat_of.get(d.handle) or layer_material(d.layer)
        mats[m.name] = m
        info = elem_of.get(d.handle, ("", "", "", ""))
        key_e = (info[0] or f"({d.layer})", d.layer)
        if key_e not in elem_id:
            elem_id[key_e] = len(elems)
            elems.append({"name": key_e[0], "layer": d.layer, "group": _group_of(d.layer), "level": info[1],
                          "material": info[2] or m.name, "type": info[3]})
        chunks.setdefault((d.layer, m.name), []).append((v, elem_id[key_e]))
    origin = np.floor(np.array(first if first is not None else (0.0, 0.0, 0.0), dtype=float))

    a, base = cfg.align, st.start_station
    lo = max(a.start_station, base - 300.0) - base
    hi = min(a.end_station, base + st.length + 300.0) - base
    sq = np.arange(lo, hi + 1e-9, 1.0)
    flq = np.array([cfg.lv(x) for x in sq]) - st.offset
    if len(sq) > 1:                                      # 선형 끝 밖(단부 벽·슬래브)은 끝 구배로 연장 (np.interp 는 끝값 고정)
        g0, g1 = flq[1] - flq[0], flq[-1] - flq[-2]
        sq = np.concatenate([[sq[0] - 100.0], sq, [sq[-1] + 100.0]])
        flq = np.concatenate([[flq[0] - 100.0 * g0], flq, [flq[-1] + 100.0 * g1]])

    blob, meta, tri_total = bytearray(), [], 0

    def put(arr):
        off = len(blob)
        blob.extend(np.ascontiguousarray(arr).tobytes())
        return off

    for (layer, mname), faces in chunks.items():
        pts = np.array([p for f, _ in faces for p in f], dtype=float)
        s = station_of(cfg, pts[:, :2], lo, hi)
        h = pts[:, 2] - np.interp(s, sq, flq)
        idx, tri_e, k = [], [], 0
        for f, eid in faces:
            idx += [k, k + 1, k + 2]
            tri_e.append(eid)
            if len(f) == 4:
                idx += [k, k + 2, k + 3]
                tri_e.append(eid)
            k += len(f)
        rel = (pts - origin).astype(np.float32)
        sh = np.stack([s, h], axis=1).astype(np.float32)
        m = mats[mname]
        meta.append({"layer": layer, "group": _group_of(layer), "material": mname,
                     "color": [round(c, 4) for c in m.color], "alpha": m.alpha,
                     "nv": len(pts), "nt": len(tri_e),
                     "pos": put(rel), "sh": put(sh), "idx": put(np.array(idx, dtype=np.uint32)),
                     "elem": put(np.array(tri_e, dtype=np.uint32))})
        tri_total += len(tri_e)

    # 선형 중심 표본 (걷기·STA 표시): s, 상대 x, y, FL 표고(상대)
    cs = np.arange(max(lo, -50.0), min(hi, st.length + 50.0) + 1e-9, 1.0)
    cl = [[round(float(x), 3), *[round(float(c), 4) for c in (np.array(cfg.to_world(x, 0.0)) - origin[:2])],
           round(float(cfg.lv(x) - st.offset - origin[2]), 4)] for x in cs]
    floors = [{"name": st.level_name(n), "fl": st.floor_level(n), "top": ceiling_rel(st, n)} for n in range(1, st.floors + 1)]
    data = {"origin": [float(c) for c in origin], "chunks": meta, "elements": elems,
            "groups": [{"name": n, "on": on} for n, _, on in LAYER_GROUPS] + [{"name": "기타", "on": True}],
            "floors": floors, "length": st.length,
            "platform_top": cfg.platform.top_level if cfg.platform.exists else None, "start_station": base, "centerline": cl,
            "title": "정거장 3D 뷰어", "triangles": tri_total}
    return data, gzip.compress(bytes(blob), compresslevel=6)


def export_web_viewer(engine, path, frames: bool = False) -> WebResult:
    """three.js 3D 뷰어 HTML (한 파일, 인터넷 없이 열림) 저장"""
    data, packed = build_web_data(engine, frames)
    html = TEMPLATE.read_text(encoding="utf-8")
    three = THREE_JS.read_text(encoding="utf-8")
    html = html.replace("/*__THREE__*/", lambda_safe(three)) \
        .replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")) \
        .replace("/*__BLOB__*/", base64.b64encode(packed).decode("ascii"))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return WebResult(str(path.resolve()), tuple(data["origin"]), data["triangles"], len(data["elements"]),
                     path.stat().st_size)


def lambda_safe(js: str) -> str:
    """<script> 안에 넣을 수 있게 (</script 끊김 방지)"""
    return js.replace("</script", "<\\/script")
