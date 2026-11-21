from finishes.finish_spec import FILLS, FRAMES, FinishSettings, FinishType

_EPS = 1e-9


def check_finish_type(ft: FinishType):
    w = f"마감 '{ft.name}'"
    if not isinstance(ft, FinishType):
        raise ValueError(f"마감 형식이 올바르지 않습니다 ({ft!r})")
    if not str(ft.name).strip():
        raise ValueError("마감 종류 이름을 입력하세요")
    for label, v in (("바닥 마감 높이", ft.ffl), ("바닥 마감재 두께", ft.floor_t), ("벽 마감 두께", ft.wall_t)):
        if not v >= 0:
            raise ValueError(f"{w}: {label}은(는) 0 이상이어야 합니다 ({v})")
    if ft.partition_face is not None and not ft.wall_t - _EPS <= ft.partition_face:
        raise ValueError(f"{w}: 칸막이벽 마감면 거리({ft.partition_face:g})가 마감재 두께({ft.wall_t:g})보다 작습니다")
    if ft.wall_face is not None:
        if not ft.wall_face >= 0:
            raise ValueError(f"{w}: 벽 마감면 거리는 0 이상이어야 합니다 ({ft.wall_face})")
        if ft.wall_face < ft.wall_t - _EPS:
            raise ValueError(f"{w}: 벽 마감면 거리({ft.wall_face:g})가 마감재 두께({ft.wall_t:g})보다 작습니다 "
                             "(구조체 면 → 마감 표면 거리 ≥ 마감재 두께)")
    if ft.floor_t > ft.ffl + _EPS:
        raise ValueError(f"{w}: 바닥 마감재 두께({ft.floor_t:g})가 마감 높이({ft.ffl:g})보다 큽니다")
    if ft.ffl > 0 and not ft.floor_t > 0:
        raise ValueError(f"{w}: 바닥 마감 높이가 있으면 마감재 두께도 0보다 커야 합니다")
    if ft.floor_fill not in FILLS:
        raise ValueError(f"{w}: 바닥 채움은 {', '.join(FILLS)} 중 하나여야 합니다 ({ft.floor_fill!r})")
    if ft.ceiling:
        for label, v in (("천장 높이", ft.ceiling_h), ("천장판 두께", ft.board_t), ("천장틀 바 간격", ft.bar_spacing),
                         ("캐링 채널 간격", ft.carrier_spacing), ("바 폭", ft.bar_w), ("바 높이", ft.bar_h),
                         ("캐링 채널 폭", ft.carrier_w), ("캐링 채널 높이", ft.carrier_h)):
            if not v > 0:
                raise ValueError(f"{w}: {label}은(는) 0보다 커야 합니다 ({v})")
        if ft.frame not in FRAMES:
            raise ValueError(f"{w}: 천장틀은 {' / '.join(FRAMES)} 중 하나여야 합니다 ({ft.frame!r})")
        if ft.bar_w >= ft.bar_spacing or ft.carrier_w >= ft.carrier_spacing:
            raise ValueError(f"{w}: 천장틀 바 폭이 간격 이상입니다")


def check_finishes(cfg):
    """마감표 검사 + 실의 마감 덮어쓰기 이름이 마감표에 있을 것"""
    fs = cfg.finish_settings
    if not isinstance(fs, FinishSettings) or not isinstance(fs.table, dict):
        raise ValueError(f"마감 설정 형식이 올바르지 않습니다 ({fs!r})")
    for key, ft in fs.table.items():
        check_finish_type(ft)
        if key != ft.name:
            raise ValueError(f"마감표 이름 불일치 ('{key}' / '{ft.name}')")
    for sp in cfg.rooms:
        name = (getattr(sp, "finish", "") or "").strip()
        if name and name not in fs.table:
            raise ValueError(f"실 {sp.name or sp.use}: 마감 종류 '{name}' 이(가) 마감표에 없습니다")
