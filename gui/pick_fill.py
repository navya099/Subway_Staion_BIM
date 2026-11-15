"""미리보기에서 고른 점 → 입력 탭 초안 값 (화면 비의존). 점은 정거장 로컬 (s, t), base = 정거장 시작 측점.
각 함수는 {초안 속성: 입력창 문자열} 을 돌려주고, 탭이 그 값을 입력칸 변수에 넣는다."""
from gui.passage_draft import MODE_WORLD, VertexDraft
from gui.room_draft import DOOR_SIDE_LABELS


def num(v: float) -> str:
    """입력창 숫자 문자열 (mm 까지, 뒤 0 제거)"""
    out = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if out in ("-0", "") else out


def rect_fields(points, base: float) -> dict:
    """실 영역: 시작/끝 STA, t 시작(−)/끝(+)"""
    (a, b), (c, d) = points[:2]
    return {"sta0": num(base + min(a, c)), "sta1": num(base + max(a, c)), "t0": num(min(b, d)), "t1": num(max(b, d))}


def opening_fields(points, base: float) -> dict:
    """오프닝: 시작 STA·길이·t 중심·폭"""
    (a, b), (c, d) = points[:2]
    return {"sta_start": num(base + min(a, c)), "length": num(abs(c - a)),
            "t_center": num((b + d) / 2.0), "width": num(abs(d - b))}


def point_fields(points, base: float, sta_attr: str, t_attr: str = "t_center") -> dict:
    """점 1개: STA 칸 + t 칸 (계단 첫 단, 에스컬레이터 하부 WP, 엘리베이터 승강로 중심)"""
    s, t = points[0]
    return {sta_attr: num(base + s), t_attr: num(t)}


_SIDE_LABEL = {v: k for k, v in DOOR_SIDE_LABELS.items()}


def door_fields(room, point, base: float) -> dict:
    """문: 클릭한 점에서 가장 가까운 실의 변 → {'side': 변 이름표, 'center': ±t 변이면 STA, ±s 변이면 t}.
    room = RoomDraft (시작/끝 STA·t 문자열)"""
    s0, s1 = float(room.sta0) - base, float(room.sta1) - base
    t0, t1 = float(room.t0), float(room.t1)
    s0, s1 = min(s0, s1), max(s0, s1)
    t0, t1 = min(t0, t1), max(t0, t1)
    s, t = point
    cands = [(abs(t - t0), "-t"), (abs(t - t1), "+t"), (abs(s - s0), "-s"), (abs(s - s1), "+s")]
    side = min(cands)[1]
    if side in ("+t", "-t"):
        center = num(base + min(max(s, s0), s1))
    else:
        center = num(min(max(t, t0), t1))
    return {"side": _SIDE_LABEL[side], "center": center}


def path_vertices(points, mode: str, base: float, to_world, old=()) -> list:
    """경로 꼭짓점 초안 목록. 높이(z)는 같은 순번의 기존 값을 유지 (없으면 첫 점 = 비움(FL), 나머지 = '0').
    절대 좌표 방식이면 to_world(s, t) 로 X, Y"""
    out = []
    for j, (s, t) in enumerate(points):
        z = old[j].z if j < len(old) else ("" if j == 0 else "0")
        if mode == MODE_WORLD:
            x, y = to_world(s, t)
            out.append(VertexDraft(num(x), num(y), z))
        else:
            out.append(VertexDraft(num(base + s), num(t), z))
    return out


def opening_floor(slabs, floors: int) -> int:
    """오프닝을 그릴 평면 층: 가장 낮은 슬래브 k 위의 층 (k+1), 천장 슬래브면 최상층"""
    k = min(slabs) if slabs else 0
    return min(max(k + 1, 1), floors)
