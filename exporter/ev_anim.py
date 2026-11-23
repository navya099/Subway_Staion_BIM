"""웹 뷰어 엘리베이터 애니메이션 자료 (내부·외부 엘리베이터 공통).

움직이는 부재(3DFACE)마다 태그를 붙여 뷰어가 태그별 메쉬를 옮긴다 — 형상은 3D DXF 그대로(단일 원천), 움직임은 BIM 객체의
car_z(카 바닥) · travel · slide(문짝 방향·최대 이동) · stop(승강장 문 층)에서.
- 'i|CAR'            : 카 (연직 이동)
- 'i|CD|면|k'        : 카 문짝 (카와 함께 + 열림 × slide)
- 'i|LD|정지|면|k'   : 승강장 문짝 (그 정지층에서 열림 × slide)
- 'i|IND|정지|면'    : 층 표시기 (이미지 바꿈)
자료 evs[i] = {name, stops: [{label, z, faces}], z(카 바닥), open, parts: {태그: {role, stop, face, d: [dx, dy, dz](전부 열림 이동)}},
box: 카 평면 [x0, y0, x1, y1](외접)·높이, buttons: {부재 이름: [정지 번호, 'up'|'down']}} — 좌표는 정수 원점 기준 상대.
"""
from elevators import hall_fixture as HF


def _vec(to_world, axis_dir, mid, length):
    """정거장(또는 EV) 좌표 방향 (ds, dt) 로 length 만큼의 세계 변위"""
    x0, y0 = to_world(*mid)
    x1, y1 = to_world(mid[0] + axis_dir[0] * length, mid[1] + axis_dir[1] * length)
    return [x1 - x0, y1 - y0, 0.0]


def _add(evs, tags, name, elements, to_world, center, stops, labels, car_z, door_open, stop_no):
    """elements: (부재, 코드, 종류 이름, 카 여부). stop_no(부재) = 정지 순번(0 부터) 또는 None"""
    i = len(evs)
    parts, buttons, faces = {}, {}, {}
    cnt = {}
    for e, kind, is_car in elements:
        tag = None
        if kind == "CAR_DOOR" or (is_car and e.slide):
            _, axis, sign = HF.parse_code(e.code)
            f = HF.face_code(axis, sign)
            cnt["CD" + f] = k = cnt.get("CD" + f, 0) + 1
            tag = f"{i}|CD|{f}|{k}"
            parts[tag] = {"role": "cardoor", "face": f, "d": _vec(to_world, e.slide[0], center, e.slide[1])}
        elif is_car:
            tag = f"{i}|CAR"
            parts[tag] = {"role": "car"}
        elif kind == "LANDING_DOOR":
            _, axis, sign = HF.parse_code(e.code)
            f, n = HF.face_code(axis, sign), stop_no(e)
            key = f"LD{n}{f}"
            cnt[key] = k = cnt.get(key, 0) + 1
            tag = f"{i}|LD|{n}|{f}|{k}"
            parts[tag] = {"role": "landing", "stop": n, "face": f, "d": _vec(to_world, e.slide[0], center, e.slide[1])}
            faces.setdefault(n, set()).add(f)
        elif kind == "INDICATOR":
            _, axis, sign = HF.parse_code(e.code)
            tag = f"{i}|IND|{stop_no(e)}|{HF.face_code(axis, sign)}"
            parts[tag] = {"role": "indicator", "stop": stop_no(e)}
        elif kind == "CALL_BUTTON":
            buttons[e.name] = [stop_no(e), HF.DIR_UP if e.code.startswith("CALLU") else HF.DIR_DOWN]
        if tag is not None:
            for ent in e.source_element or []:
                tags[ent.dxf.handle] = tag
    evs.append({"name": name, "stops": [{"label": lb, "z": z, "faces": sorted(faces.get(k, ()))} for k, (lb, z) in enumerate(zip(labels, stops))],
                "z": car_z, "open": door_open, "parts": parts, "buttons": buttons})


def build(engine, origin) -> tuple:
    """(evs 자료, {3DFACE 핸들: 태그}). build_3d_doc 뒤에 부를 것"""
    evs, tags = [], {}
    cfg = engine.cfg
    inner = getattr(engine, "elevators", None)
    for ev in (inner.elevators if inner is not None else []):
        nos = sorted(ev.stops)
        _add(evs, tags, ev.name, [(e, e.kind.name, e.kind.is_car) for e in ev.elements], cfg.to_world, (ev.pos_x, ev.pos_y),
             [ev.stops[n] for n in nos], [cfg.station.level_name(n) for n in nos], ev.car_z, ev.door_open,
             lambda e, nos=nos: nos.index(e.stop))
    ext = getattr(engine, "ext_evs", None)
    for x in (ext.ext_evs if ext is not None else []):
        lab = ext.stop_labels(x)
        sp = x.layout.spec
        _add(evs, tags, x.name, [(e, e.kind, e.is_car) for e in x.elements], x.frame.to_world, (sp.u, sp.t),
             [x.stops[n] for n in (1, 2)], [lab[1], lab[2]], x.car_z, x.door_open, lambda e: e.stop - 1)
    for ev in evs:                                                  # 상대 좌표
        ev["z"] = round(ev["z"] - float(origin[2]), 5)
        for s in ev["stops"]:
            s["z"] = round(s["z"] - float(origin[2]), 5)
        for p in ev["parts"].values():
            if "d" in p:
                p["d"] = [round(v, 6) for v in p["d"]]
    return evs, tags


def indicator_images(evs) -> dict:
    """표시기 이미지 {키: PIL} — 나오는 층 이름 × 방향"""
    out = {}
    for lb in sorted({s["label"] for ev in evs if any(p["role"] == "indicator" for p in ev["parts"].values()) for s in ev["stops"]}):
        for d in (HF.DIR_NONE, HF.DIR_UP, HF.DIR_DOWN):
            out[HF.indicator_key(lb, d)] = HF.render_indicator(lb, d)
    return out
