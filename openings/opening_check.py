from openings.decompose import overlap_area
from openings.opening_kind import OpeningKind
from openings.opening_spec import resolve_names


def slab_label(slab_no: int, floors: int) -> str:
    """슬래브 번호의 한글 설명 (오류 메시지·GUI 공통)"""
    if slab_no == 0:
        return "본체 바닥 슬래브"
    if slab_no == floors:
        return "본체 천장 슬래브"
    return f"{slab_no}층/{slab_no + 1}층 중간 슬래브"


def check_openings(station, specs: list) -> list[str]:
    """오프닝 제원 검사. 이름 목록을 돌려줌. 오류는 ValueError.
    - 용도·치수·슬래브 번호가 올바를 것
    - 내공 영역(0~L x ±W/2) 안에 있을 것 (벽체 안으로 뚫지 않음)
    - 같은 슬래브에서 오프닝끼리 겹치지 않을 것"""
    names = resolve_names(specs)
    L, hw, floors = station.length, station.width / 2.0, station.floors
    eps = 1e-6
    for name, sp in zip(names, specs):
        if not isinstance(sp.kind, OpeningKind):
            raise ValueError(f"{name}: 오프닝 용도가 올바르지 않습니다 ({sp.kind!r})")
        if sp.length <= 0 or sp.width <= 0:
            raise ValueError(f"{name}: 오프닝 길이·폭은 0보다 커야 합니다")
        if not sp.slabs:
            raise ValueError(f"{name}: 뚫을 슬래브를 하나 이상 선택하세요")
        if len(set(sp.slabs)) != len(sp.slabs):
            raise ValueError(f"{name}: 슬래브 번호가 중복되었습니다")
        bad = [n for n in sp.slabs if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= floors]
        if bad:
            raise ValueError(f"{name}: 슬래브 번호 {bad} 이(가) 범위(0~{floors})를 벗어납니다")
        if sp.s_start < -eps or sp.s_end > L + eps:
            raise ValueError(f"{name}: 오프닝 s 범위 {sp.s_start:.3f} ~ {sp.s_end:.3f} 이(가) "
                             f"내공 길이(0 ~ {L:g}m)를 벗어납니다")
        if sp.t_lo < -hw - eps or sp.t_hi > hw + eps:
            raise ValueError(f"{name}: 오프닝 t 범위 {sp.t_lo:.3f} ~ {sp.t_hi:.3f} 이(가) "
                             f"내공 폭(±{hw:g}m)을 벗어납니다")
    for i, a in enumerate(specs):
        for j in range(i + 1, len(specs)):
            b = specs[j]
            shared = set(a.slabs) & set(b.slabs)
            if shared and overlap_area((a.s_start, a.s_end, a.t_lo, a.t_hi), (b.s_start, b.s_end, b.t_lo, b.t_hi)) > 1e-9:
                raise ValueError(f"{names[i]} 와 {names[j]} 오프닝이 {slab_label(min(shared), floors)} 에서 서로 겹칩니다")
    return names
