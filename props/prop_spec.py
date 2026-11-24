"""배치 객체(비품) 입력: 종류·층·위치·방향·치수"""
import dataclasses
import re

from props.prop_kinds import INT, KINDS, NUM, TEXT


@dataclasses.dataclass
class PropSpec:
    """비품 1개.
    kind: prop_kinds.KINDS 의 코드, floor: 층 번호 (1 = 최하층)
    s, t: 평면 위치 (정거장 로컬, 바닥·천장·매달림 = 중심, 벽 부착 = 고른 점 — 0.5m 안의 벽 마감 표면에 붙음)
    angle: 앞면 방향 (도): 0 = +s(종점 쪽), 90 = +t(왼쪽), 180 = −s, 270 = −t. 벽 부착은 벽을 등지게 자동 (angle 안 씀)
    values: 치수·문구 (비운 항목은 종류 기본값), name: 비우면 종류 이름 + 번호"""
    kind: str = "BENCH"
    floor: int = 1
    s: float = 0.0
    t: float = 0.0
    angle: float = 0.0
    values: dict = dataclasses.field(default_factory=dict)
    name: str = ""

    def resolved(self) -> dict:
        """기본값을 채운 입력 값"""
        k = KINDS[self.kind]
        return {f.key: self.values.get(f.key, f.default) for f in k.fields}


def resolve_prop_names(specs) -> list:
    """이름 목록 (비우면 종류 이름(괄호 앞) + 같은 종류 순번)"""
    cnt, out = {}, []
    for sp in specs:
        cnt[sp.kind] = cnt.get(sp.kind, 0) + 1
        label = KINDS[sp.kind].label.split(" (")[0] if sp.kind in KINDS else sp.kind
        out.append(sp.name.strip() or f"{label} {cnt[sp.kind]}")
    return out


def check_props(cfg) -> None:
    """입력 형식·범위 검사 (겹침은 엔진이 만든 뒤 prop_check)"""
    st = cfg.station
    for sp in cfg.props:
        if not isinstance(sp, PropSpec) or sp.kind not in KINDS:
            raise ValueError(f"비품 종류가 올바르지 않습니다 ({getattr(sp, 'kind', sp)!r})")
    names = resolve_prop_names(cfg.props)
    for nm, sp in zip(names, cfg.props):
        w = f"비품 {nm}"
        if not isinstance(sp.floor, int) or isinstance(sp.floor, bool) or not 1 <= sp.floor <= st.floors:
            raise ValueError(f"{w}: 층 번호 {sp.floor!r} 이(가) 범위(1 ~ {st.floors})를 벗어납니다")
        known = {f.key for f in KINDS[sp.kind].fields}
        for k in sp.values:
            if k not in known:
                raise ValueError(f"{w}: 알 수 없는 입력 '{k}'")
        for f in KINDS[sp.kind].fields:
            v = sp.resolved()[f.key]
            if f.type == TEXT:
                if f.key == "bg" and not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
                    raise ValueError(f"{w}: 배경색은 #RRGGBB 형식이어야 합니다 ('{v}')")
                continue
            if f.type == INT and (not isinstance(v, int) or isinstance(v, bool)):
                raise ValueError(f"{w}: {f.label}은(는) 정수여야 합니다 ({v!r})")
            if f.type in (NUM, INT) and not v > f.lo:
                raise ValueError(f"{w}: {f.label}({v:g})은(는) {f.lo:g}보다 커야 합니다" if f.lo > 0 else f"{w}: {f.label}({v:g})이(가) 너무 작습니다")
        if sp.kind == "BENCH" and not sp.resolved()["back_h"] > sp.resolved()["seat_h"] + 0.12:
            raise ValueError(f"{w}: 등받이 높이가 앉는 높이보다 0.12m 넘게 높아야 합니다")
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"비품 이름이 중복됩니다: {', '.join(dup)}")
