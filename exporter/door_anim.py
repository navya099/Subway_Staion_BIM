"""웹 뷰어 실 문 애니메이션 자료: 문짝(+ 손잡이·유리) 3DFACE 에 태그 'D|문 순번|문짝' 을 붙여 뷰어가 태그별 메쉬를 돌리거나 민다.

형상은 닫힌 문의 3DFACE 그대로(단일 원천), 움직임은 DoorData.motions (정거장 로컬) 를 세계 좌표로 옮긴 것.
자료 doors[i] = {name, kind, auto, x, y, z(문 가운데 바닥 마감면), width, parts: [부재 이름],
leaves: {태그: {kind 'swing', px, py, angle(도, 왼쪽 회전 +)} | {kind 'slide', dx, dy}}} — 좌표는 정수 원점 기준 상대 (web_viewer 가 원점을 뺌).
"""
from rooms.door_parts import AUTO


def build(engine) -> tuple:
    """(doors 자료, {3DFACE 핸들: 태그}). 3D 면을 만든 뒤에 부를 것"""
    cfg, rooms = engine.cfg, getattr(engine, "rooms", None)
    out, tags = [], {}
    for i, d in enumerate(rooms.doors if rooms is not None else []):
        leaves = {}
        for m in d.motions:
            tag = f"D|{i}|{m.leaf}"
            if m.kind == "swing":
                px, py = cfg.to_world(*m.pivot)
                leaves[tag] = {"kind": "swing", "px": px, "py": py, "angle": m.angle}
            else:
                x0, y0 = cfg.to_world(d.pos_x, d.pos_y)
                x1, y1 = cfg.to_world(d.pos_x + m.move[0], d.pos_y + m.move[1])
                leaves[tag] = {"kind": "slide", "dx": round(x1 - x0, 5), "dy": round(y1 - y0, 5)}
            for p in d.parts:
                if p.leaf == m.leaf:
                    for ent in p.source_element or []:
                        tags[ent.dxf.handle] = tag
        x, y = cfg.to_world(d.pos_x, d.pos_y)
        out.append({"name": d.name, "kind": d.kind, "auto": d.kind == AUTO, "x": x, "y": y, "z": d.pos_z, "width": d.width,
                    "parts": [p.name for p in d.parts], "leaves": leaves})
    return out, tags


def shift(doors, origin) -> None:
    """원점을 빼서 상대 좌표로"""
    ox, oy, oz = (float(c) for c in origin)
    for d in doors:
        d["x"], d["y"], d["z"] = round(d["x"] - ox, 5), round(d["y"] - oy, 5), round(d["z"] - oz, 5)
        for lf in d["leaves"].values():
            if lf["kind"] == "swing":
                lf["px"], lf["py"] = round(lf["px"] - ox, 5), round(lf["py"] - oy, 5)
