"""입력 탭의 [선택] 버튼 공통: 미리보기 평면에서 위치를 골라 입력칸을 채움.

탭은 entries['pick'] (StationBIMApp.request_pick) 으로 PickRequest 를 보낸다. 없으면(탭 단독 테스트 등) 버튼은 아무것도 안 함.
채우기는 탭의 입력칸 변수(_vars[(번호, 속성)])에 값을 넣는 방식이라, 변수의 trace 가 초안과 안내문을 함께 갱신한다.
"""
import tkinter as tk

from gui import pick_fill as F
from preview.pick import PATH, POINT, RECT, PickRequest

FONT = ("Malgun Gothic", 9)
PICK_BG = "#FFF3E0"


def base_station(entries) -> float:
    try:
        return float(entries["start_station"].get())
    except (KeyError, ValueError, AttributeError):
        return 0.0


def button(parent, text, command) -> tk.Button:
    return tk.Button(parent, text=text, font=FONT, bg=PICK_BG, command=command)


def request(tab, kind, floor, title, on_done, holder=None) -> bool:
    """holder: 만든 PickRequest 를 담을 목록 (on_done 에서 request.to_world 를 쓰려면)"""
    fn = tab.entries.get("pick")
    if fn is None:
        return False
    req = PickRequest(kind=kind, floor=max(1, int(floor)), title=title, on_done=on_done)
    if holder is not None:
        holder.append(req)
    return bool(fn(req))


def fill(tab, i, values: dict):
    """입력칸 변수에 값 넣기 (변수가 없으면 초안에 직접)"""
    it = tab.drafts.items[i]
    for attr, v in values.items():
        var = tab._vars.get((i, attr))
        if var is not None:
            var.set(v)
        else:
            setattr(it, attr, v)


# ------------------------------------------------------------------ 탭별
def pick_room_rect(tab, i):
    it = tab.drafts.items[i]
    request(tab, RECT, it.floor, f"실 {i + 1} 영역",
            lambda pts: fill(tab, i, F.rect_fields(pts, base_station(tab.entries))))


def pick_door(tab, i, k):
    it = tab.drafts.items[i]

    def done(pts):
        v = F.door_fields(it, pts[0], base_station(tab.entries))
        tab.set_door_side(i, k, v["side"])
        combo = tab._combos.get((i, "door", k, "side"))
        if combo is not None:
            combo.set(v["side"])
        var = tab._vars.get((i, "door", k, "center"))
        if var is not None:
            var.set(v["center"])
        else:
            it.doors[k].center = v["center"]
    request(tab, POINT, it.floor, f"실 {i + 1} 문{k + 1} 위치 (가까운 변에 붙음)", done)


def pick_opening_rect(tab, i):
    it = tab.drafts.items[i]
    request(tab, RECT, F.opening_floor(it.slabs, max(1, tab.floor_count)), f"오프닝 {i + 1} 영역",
            lambda pts: fill(tab, i, F.opening_fields(pts, base_station(tab.entries))))


def pick_point(tab, i, title, floor, sta_attr, t_attr="t_center"):
    """계단 첫 단·에스컬레이터 하부 WP·엘리베이터 승강로 중심"""
    request(tab, POINT, floor, title,
            lambda pts: fill(tab, i, F.point_fields(pts, base_station(tab.entries), sta_attr, t_attr)))


def pick_path(tab, i, what):
    """출구통로·환기구 경로: 꼭짓점 표를 고른 점으로 바꿈 (높이는 같은 순번 값 유지)"""
    it = tab.drafts.items[i]
    holder = []

    def done(pts):
        to_world = holder[0].to_world if holder else None          # 미리보기 창이 넣어 줌 (절대 좌표 방식)
        it.vertices[:] = F.path_vertices(pts, it.mode, base_station(tab.entries), to_world, list(it.vertices))
        tab.render()
    request(tab, PATH, it.floor, f"{what} {i + 1} 경로", done, holder)
