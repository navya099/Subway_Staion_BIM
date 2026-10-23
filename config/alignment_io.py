"""선형 입력 파일(JSON) 읽기. 파일 하나로 직선 / 방향각 직선 / 곡선(평면 + 종단) 선형을 정의한다.

type = "straight": BP/EP 좌표 직선 (GUI 입력과 같은 형식)
    {"type": "straight", "bp_station": 0, "bp_x": 0, "bp_y": 0, "bp_z": 100, "ep_x": 500, "ep_y": 0, "ep_z": 105}
type = "heading": 시점 + 방향각 + 구배 + 연장
    {"type": "heading", "bp_station": 0, "bp_x": 0, "bp_y": 0, "bp_z": 100, "heading_deg": 30, "grade_permil": 5, "length": 800}
type = "curve": 평면(교점 방식 또는 요소 나열) + 종단(변곡점)
    {"type": "curve",
     "horizontal": {"start_station": 0, "points": [[0,0],[500,0],[900,400],[1500,400]], "radii": [400,500], "spirals": [60,80]},
     "vertical": [[0,100,0],[450,104,150],[1000,98,0]]}          # [측점, 표고, 종곡선장]
    평면을 요소로 나열할 때:
    "horizontal": {"start_station": 0, "x": 0, "y": 0, "heading_deg": 0, "elements": [
        {"type": "line", "length": 100},
        {"type": "spiral", "length": 60, "radius_start": null, "radius_end": 400, "direction": "left"},
        {"type": "arc", "length": 150, "radius": 400, "direction": "left"}]}
"""
import json
import math

from config.alignment import Alignment, HeadingAlignment
from config.alignment_config import AlignmentConfig
from config.curved_alignment import CurvedAlignment, HElement, HorizontalAlignment, VerticalProfile, horizontal_from_pi


def _num(v, where: str, allow_inf: bool = False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ValueError(f"{where}: 숫자여야 합니다 ({v!r})")
    try:
        x = float(v)
    except ValueError:
        raise ValueError(f"{where}: 숫자가 아닙니다 ({v!r})") from None
    if math.isnan(x) or (math.isinf(x) and not allow_inf):
        raise ValueError(f"{where}: 유한한 숫자여야 합니다 ({v!r})")
    return x


def _need(d: dict, keys, where: str):
    if not isinstance(d, dict):
        raise ValueError(f"{where}: 객체({{...}})여야 합니다")
    missing = [k for k in keys if k not in d]
    if missing:
        raise ValueError(f"{where}: 필요한 항목이 없습니다 → {', '.join(missing)}")


def _radius(v, where: str) -> float:
    """곡선반경. null / "inf" = 무한대(직선 쪽 끝)"""
    if v is None or (isinstance(v, str) and v.strip().lower() in ("inf", "infinity", "∞")):
        return math.inf
    r = _num(v, where)
    if r <= 0:
        raise ValueError(f"{where}: 곡선반경은 0보다 커야 합니다 ({v!r})")
    return r


def _sign(v, where: str) -> float:
    s = str(v).strip().lower()
    if s in ("left", "l", "좌", "좌회전"):
        return 1.0
    if s in ("right", "r", "우", "우회전"):
        return -1.0
    raise ValueError(f"{where}: direction 은 left 또는 right 여야 합니다 ({v!r})")


def _elements(items, where: str) -> list:
    if not isinstance(items, list) or not items:
        raise ValueError(f"{where}: 요소 목록이 비어 있습니다")
    out = []
    for i, e in enumerate(items):
        w = f"{where}[{i}]"
        _need(e, ["type", "length"], w)
        length, kind = _num(e["length"], f"{w}.length"), str(e["type"]).strip().lower()
        if kind == "line":
            out.append(HElement(length))
        elif kind == "arc":
            _need(e, ["radius", "direction"], w)
            out.append(HElement(length, *(_sign(e["direction"], f"{w}.direction") / _radius(e["radius"], f"{w}.radius"),) * 2))
        elif kind == "spiral":
            _need(e, ["radius_start", "radius_end", "direction"], w)
            sg = _sign(e["direction"], f"{w}.direction")
            out.append(HElement(length, sg / _radius(e["radius_start"], f"{w}.radius_start"),
                                sg / _radius(e["radius_end"], f"{w}.radius_end")))
        else:
            raise ValueError(f"{w}.type: line / arc / spiral 중 하나여야 합니다 ({e['type']!r})")
    return out


def _horizontal(h: dict) -> HorizontalAlignment:
    _need(h, ["start_station"], "horizontal")
    sta = _num(h["start_station"], "horizontal.start_station")
    if "points" in h:                                    # 교점(IP) 방식
        _need(h, ["radii"], "horizontal")
        pts = []
        for i, p in enumerate(h["points"]):
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                raise ValueError(f"horizontal.points[{i}]: [x, y] 두 숫자여야 합니다")
            pts.append((_num(p[0], f"horizontal.points[{i}][0]"), _num(p[1], f"horizontal.points[{i}][1]")))
        radii = [_num(r, f"horizontal.radii[{i}]") for i, r in enumerate(h["radii"])]
        spirals = [_num(r, f"horizontal.spirals[{i}]") for i, r in enumerate(h["spirals"])] if "spirals" in h else None
        return horizontal_from_pi(sta, pts, radii, spirals)
    if "elements" in h:                                  # 요소 나열 방식
        _need(h, ["x", "y", "heading_deg"], "horizontal")
        return HorizontalAlignment(sta, _num(h["x"], "horizontal.x"), _num(h["y"], "horizontal.y"),
                                   math.radians(_num(h["heading_deg"], "horizontal.heading_deg")),
                                   _elements(h["elements"], "horizontal.elements"))
    raise ValueError("horizontal: points(교점 방식) 또는 elements(요소 나열 방식) 중 하나가 필요합니다")


def _vertical(v) -> VerticalProfile:
    if not isinstance(v, list):
        raise ValueError("vertical: 변곡점 목록([측점, 표고, 종곡선장] 또는 {station, elevation, curve_length})이어야 합니다")
    pvis = []
    for i, p in enumerate(v):
        w = f"vertical[{i}]"
        if isinstance(p, dict):
            _need(p, ["station", "elevation"], w)
            pvis.append((_num(p["station"], f"{w}.station"), _num(p["elevation"], f"{w}.elevation"),
                         _num(p.get("curve_length", 0.0), f"{w}.curve_length")))
        elif isinstance(p, (list, tuple)) and len(p) in (2, 3):
            pvis.append(tuple(_num(x, f"{w}[{j}]") for j, x in enumerate(p)))
        else:
            raise ValueError(f"{w}: [측점, 표고] 또는 [측점, 표고, 종곡선장] 이어야 합니다")
    return VerticalProfile(pvis)


def alignment_from_dict(d: dict) -> Alignment:
    _need(d, ["type"], "선형")
    kind = str(d["type"]).strip().lower()
    if kind == "straight":
        keys = ["bp_station", "bp_x", "bp_y", "bp_z", "ep_x", "ep_y", "ep_z"]
        _need(d, keys, "straight")
        a = AlignmentConfig(**{k: _num(d[k], k) for k in keys})
    elif kind == "heading":
        keys = ["bp_station", "bp_x", "bp_y", "bp_z", "heading_deg", "grade_permil", "length"]
        _need(d, keys, "heading")
        a = HeadingAlignment(**{k: _num(d[k], k) for k in keys})
    elif kind == "curve":
        _need(d, ["horizontal", "vertical"], "curve")
        a = CurvedAlignment(_horizontal(d["horizontal"]), _vertical(d["vertical"]))
    else:
        raise ValueError(f"선형 type 은 straight / heading / curve 중 하나여야 합니다 ({d['type']!r})")
    a.validate()
    return a


def load_alignment(path) -> Alignment:
    """JSON 파일에서 선형을 읽음. 형식이 틀리면 파일 이름과 위치를 밝혀 ValueError"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: JSON 형식 오류 (줄 {e.lineno}, 열 {e.colno}): {e.msg}") from None
    except OSError as e:
        raise ValueError(f"{path}: 파일을 열 수 없습니다 ({e.strerror})") from None
    try:
        return alignment_from_dict(data)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from None


def describe(a: Alignment) -> str:
    kind = {AlignmentConfig: "BP/EP 직선", HeadingAlignment: "방향각 직선"}.get(type(a), "곡선")
    return f"{kind}, STA {a.start_station:.2f} ~ {a.end_station:.2f}"
