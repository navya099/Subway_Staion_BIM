"""성과물 출력 옵션 (출력 탭). 무엇을 출력할지와 평면·종단·단면의 세부 옵션"""
from dataclasses import dataclass, field
from typing import Optional

PLAN_CUT_H = 2.0                 # 평면도 절단 높이 기본값 (각 층 FL 기준, m)
SECTION_RATIOS = (0.25, 0.5, 0.75)   # 측점을 입력하지 않았을 때의 단면 위치 (내공 길이 비율)
MAX_SECTIONS = 500               # 연속 단면 개수 상한 (간격을 너무 작게 준 실수 방지)


@dataclass
class OutputOptions:
    """
    dxf3d / ifc / plan / profile / section / dae / web: 각 성과물 출력 여부 (dae = 텍스처 3D 모델 COLLADA, web = 3D 웹 뷰어 HTML, 기본 끔)
    plan_floors: 평면도 층 번호 목록 (1 = 최하층). None 이면 모든 층
    plan_cut_h: 평면도 절단 높이 (각 층 바닥 FL 기준, m, 모든 층 공통)
    profile_offsets: 종단면 절단 축 = 선형 중심에서의 직교 거리 t 목록 (m, 진행방향 왼쪽 +)
    section_stations: 단면 측점 (절대 STA, m) 목록
    section_interval: 연속 단면 간격 (m). None 이면 연속 단면 없음
    section_from / section_to: 연속 단면 범위 (절대 STA). None 이면 정거장 내공 시점 / 종점
    측점도 연속 단면도 없으면 내공 길이의 1/4 · 1/2 · 3/4 위치
    """
    dxf3d: bool = True
    ifc: bool = True
    plan: bool = True
    plan_floors: Optional[list] = None
    plan_cut_h: float = PLAN_CUT_H
    plan_ground: bool = True     # 지상 평면 (출입구·외부 EV·환기구 지상부가 있을 때)
    profile: bool = True
    profile_outer: str = "both"  # 종단면도의 본체 밖 구조물 투영: both | left(+t) | right(−t) | none
    profile_offsets: list = field(default_factory=lambda: [0.0])
    section: bool = True
    section_stations: list = field(default_factory=list)
    section_interval: Optional[float] = None
    section_from: Optional[float] = None
    section_to: Optional[float] = None
    dae: bool = False
    web: bool = False            # 3D 웹 뷰어 (three.js HTML 한 파일)
    path_profile: bool = False   # 통로 종단면도 (출구통로마다 경로를 따라 펼친 종단 + 끝 출입구)

    def floors(self, cfg) -> list:
        """평면도 층 번호 (지상 = 층수 + 1 — plan_ground 이고 지상 구조물이 있을 때)"""
        from engine.outer_views import ground_floor, has_ground
        n = cfg.station.floors
        out = list(range(1, n + 1)) if self.plan_floors is None else sorted(set(self.plan_floors))
        return out + [ground_floor(cfg)] if self.plan_ground and has_ground(cfg) else out

    def section_s(self, cfg) -> list:
        """단면을 자를 정거장 로컬 거리 s 목록 (오름차순, 1mm 안의 중복 제거)"""
        return self.section_s_at(cfg.station.start_station, cfg.station.length)

    def section_s_at(self, base: float, length: float) -> list:
        """section_s 의 계산부 (정거장 시작 측점 base, 내공 길이 length)"""
        ss = [sta - base for sta in self.section_stations]
        if self.section_interval is not None:
            a = (self.section_from if self.section_from is not None else base) - base
            b = (self.section_to if self.section_to is not None else base + length) - base
            k = 0
            while a + k * self.section_interval <= b + 1e-6:
                ss.append(a + k * self.section_interval)
                k += 1
        if not ss:
            ss = [length * r for r in SECTION_RATIOS]
        out = []
        for s in sorted(ss):
            if not out or s - out[-1] > 1e-3:
                out.append(s)
        return out

    def validate(self, cfg):
        """설정(층수·정거장 범위)에 맞는지 검사. 잘못되면 ValueError"""
        p = cfg.station
        if not any((self.dxf3d, self.ifc, self.plan, self.profile, self.section, self.dae, self.web, self.path_profile)):
            raise ValueError("출력: 출력할 성과물을 하나 이상 선택하세요")
        lo, hi = p.start_station, p.start_station + p.length

        def fmt(sta):
            return f"{sta:.2f}"
        if self.plan:
            if self.plan_floors is not None and not self.plan_floors:
                raise ValueError("평면도: 출력할 층을 하나 이상 선택하세요")
            body = list(range(1, p.floors + 1)) if self.plan_floors is None else sorted(set(self.plan_floors))   # 지상 제외
            bad = [n for n in body if not 1 <= n <= p.floors]
            if bad:
                raise ValueError(f"평면도: 층 번호가 범위(1~{p.floors}) 밖입니다 ({bad})")
            if not self.plan_cut_h > 0:
                raise ValueError(f"평면도: 절단 높이는 0보다 커야 합니다 ({self.plan_cut_h})")
            low = min((p.clear_height(n) for n in body), default=1e9)
            if self.plan_cut_h >= low:
                raise ValueError(f"평면도: 절단 높이({self.plan_cut_h:g}m)가 선택한 층의 내공 높이({low:.2f}m) 이상입니다")
        if self.profile:
            if self.profile_outer not in ("both", "left", "right", "none"):
                raise ValueError(f"종단면도: 외부 구조물 투영 값이 올바르지 않습니다 ({self.profile_outer!r})")
            if not self.profile_offsets:
                raise ValueError("종단면도: 절단 축(선형 중심 offset)을 하나 이상 입력하세요")
            half = p.width / 2.0 + p.max_wall_t
            far = [t for t in self.profile_offsets if abs(t) > half + 1e-9]
            if far:
                raise ValueError(f"종단면도: 절단 축 offset {far} 이(가) 본체 외곽(±{half:.2f}m) 밖입니다")
        if self.section:
            out = [sta for sta in self.section_stations if not lo - 1e-6 <= sta <= hi + 1e-6]
            if out:
                raise ValueError(f"단면도: 측점 {', '.join(fmt(x) for x in out)} 이(가) 정거장 내공 범위(STA {fmt(lo)} ~ {fmt(hi)}) 밖입니다")
            if self.section_interval is not None:
                if not self.section_interval > 0:
                    raise ValueError(f"단면도: 연속 단면 간격은 0보다 커야 합니다 ({self.section_interval})")
                a = lo if self.section_from is None else self.section_from
                b = hi if self.section_to is None else self.section_to
                if not (lo - 1e-6 <= a <= hi + 1e-6 and lo - 1e-6 <= b <= hi + 1e-6):
                    raise ValueError(f"단면도: 연속 단면 범위 STA {fmt(a)} ~ {fmt(b)} 이(가) 정거장 내공 범위(STA {fmt(lo)} ~ {fmt(hi)}) 밖입니다")
                if b < a:
                    raise ValueError(f"단면도: 연속 단면 끝 측점({fmt(b)})이 시작 측점({fmt(a)})보다 앞입니다")
                if (b - a) / self.section_interval + 1 > MAX_SECTIONS:
                    raise ValueError(f"단면도: 연속 단면이 너무 많습니다 ({int((b - a) / self.section_interval) + 1}개 > {MAX_SECTIONS}개). 간격을 늘리세요")
