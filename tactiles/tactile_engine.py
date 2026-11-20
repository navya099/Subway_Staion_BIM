"""점자블록 BIM 객체: 층·종류(점형/선형)마다 1개, 조각 = 선형 각기둥(RoomPiece).

배치는 tactile_layout.layout_tactile. 높이: 바닥 마감이 있는 곳은 그 마감재를 대체(finish_layout 이 마감재에서 빼고
같은 높이·두께로 넘겨줌 — FinishEngine.rooms[].tactile), 마감이 없는 곳(마감 끔, 마감 없는 실)은 기준 바닥 위 block_t.
3D DXF(FIN_TACTILE) / 횡단·종단(SEC_TACTILE 윤곽) / 평면(PLAN_TACTILE, 그 층 블록 윤곽) / IFC(IfcCovering FLOORING) 의 단일 원천.
"""
from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from finishes.finish_engine import column_footprints, room_piece
from helper import prism_member as PM
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from tactiles.tactile_layout import board_blocks, layout_tactile, minus
from tactiles.tactile_spec import BOARD, GUIDE, KIND_LABEL, WARNING

MATERIALS = {WARNING: "점자블록 점형", GUIDE: "점자블록 선형", BOARD: "승하차위치표시"}
CODES = {WARNING: "WARN", GUIDE: "GUIDE", BOARD: "BOARD"}
LABEL_H = 0.3                    # 평면도 승하차 위치 번호 글자 높이


@dataclass
class TactileElementData(CommonBIMData):
    """한 층의 한 종류 점자블록. pieces = RoomPiece"""
    floor: int = 1
    kind: str = WARNING
    pieces: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.pieces)

    @property
    def area(self) -> float:
        return sum(p.shape.length * p.shape.width for p in self.pieces)


class TactileEngine:
    def __init__(self, config, column_engine=None, finish_engine=None):
        self.cfg = config
        self.elements: list[TactileElementData] = []
        self.labels: list = []                                # 승하차 위치 번호 [(층, s, t, '차량-문')] (평면도 글자)
        self._build(column_engine, finish_engine)

    def _build(self, column_engine, finish_engine):
        cfg = self.cfg
        ts = cfg.tactile_settings
        blocks = layout_tactile(cfg, column_footprints(cfg, column_engine))
        if not blocks:
            return
        if any(b.kind == BOARD for b in blocks):
            self.labels = [(1, (r[0] + r[1]) / 2.0, (r[2] + r[3]) / 2.0, lb) for _, r, lb in board_blocks(cfg, ts)]
        covered = {}                                          # 층 → [(s0, s1, t0, t1, z0, z1, 종류)] 마감재 대체 조각
        for r in (finish_engine.rooms if finish_engine is not None else []):
            covered.setdefault(r.floor, []).extend(r.tactile)
        rects = {}                                            # (층, 종류) → [(s0, s1, t0, t1, z0, z1)]
        for n in sorted({b.floor for b in blocks}):
            cov = covered.get(n, [])
            for c in cov:
                rects.setdefault((n, c[6]), []).append(c[:6] + c[7:8])          # 사다리꼴(구조물 확폭)이면 trap 이 끝에
            if any(len(c) > 7 for c in cov):                    # 구조물 확폭 층: 사다리꼴 영역 연산
                from finishes.finish_pocket import piece_region
                from helper import trap_region as T
                holes_t = [piece_region(c[:6] + c[7:8]) for c in cov]
                for b in (b for b in blocks if b.floor == n):
                    for q in T.subtract([T.rect(*b.rect)], holes_t):
                        tr = T.trap_of(q)
                        rects.setdefault((n, b.kind), []).append((*T.bbox(q), b.base, b.base + ts.block_t) + ((tr,) if tr else ()))
                continue
            holes = [c[:4] for c in cov]
            for b in (b for b in blocks if b.floor == n):
                for r in minus([b.rect], holes):              # 바닥 마감이 없는 곳: 기준 바닥 위에 블록 두께
                    rects.setdefault((n, b.kind), []).append((*r, b.base, b.base + ts.block_t))
        for (n, kind), rs in sorted(rects.items()):
            level = cfg.station.level_name(n)
            name = f"TB_{level}_{CODES[kind]}"
            pieces = [room_piece(cfg, f"{name}_P{k}", *r) for k, r in enumerate(sorted(rs, key=lambda x: x[:6]), start=1)]
            self.elements.append(TactileElementData(
                name=name, family_name="점자블록", type_name=f"{KIND_LABEL[kind]} {ts.size * 1000:g}mm", level=level,
                material=MATERIALS[kind], floor=n, kind=kind, pieces=pieces))

    # ---------- 작도 ----------
    def add_tactile_mesh(self, msp):
        """3D 메쉬 (FIN_TACTILE). 한 번만 호출할 것"""
        for e in self.elements:
            faces = [f for p in e.pieces for f in PM.mesh_faces(self.cfg, p)]
            e.source_element = [msp.add_3dface(f, dxfattribs={"layer": "FIN_TACTILE"}) for f in faces]

    def section_items(self, sta):
        items = []
        for e in self.elements:
            for p in e.pieces:
                cut = PM.section_rect(self.cfg, p, sta)
                if cut:
                    t0, t1, zb = cut
                    items.append(ViewItem.rect(e.name, "SEC_TACTILE", t0, t1, zb, zb + p.shape.height))
        return items

    def profile_items(self, t_cut=0.0):
        return [PM.profile_view(self.cfg, p, "SEC_TACTILE") for e in self.elements for p in e.pieces
                if CommonHelper.cut_by_t(*PM.t_range(p), t_cut)]

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층): 그 층 점자블록 윤곽 (절단 높이와 관계없이 바닥 패턴으로 표시) + 승하차 위치 번호 '차량-문'"""
        items = [ViewItem.rect(e.name, "PLAN_TACTILE", *PM.s_range(p), *PM.t_range(p))
                 for e in self.elements if e.floor == floor for p in e.pieces]
        for n, s, t, text in self.labels:
            if n == floor:
                items.append(ViewItem(f"BOARD_{text}", "PLAN_TACTILE", u0=s, u1=s, pts=[],
                                      label=(text, s - 0.15 * LABEL_H * len(text) * 2, t - LABEL_H / 2, LABEL_H, "PLAN_TACTILE")))
        return items
