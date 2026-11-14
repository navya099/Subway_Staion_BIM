import math
import os
import ezdxf

from columns.column_engine import ColumnEngine
from config.cadconfig import LAYER_DEFINITIONS
from config.master_config import StationProjectConfig
from config.output_config import PLAN_CUT_H
from exporter.ifc_exporter import IFCExporter
from helper.view_item import ViewItem, draw_view_items
from platforms.platform_engine import PlatformEngine
from slabs.slab_engine import SlabEngine
from entrances.entrance_engine import EntranceEngine
from escalators.escalator_engine import EscalatorEngine
from passages.passage_engine import PassageEngine
from stairs.stair_engine import StairEngine
from ventilations.vent_engine import VentEngine
from walls.wall_engine import WallEngine


class StationCADEngine:
    def __init__(self, config: StationProjectConfig):
        config.validate()
        self.cfg = config
        # --- [서브 부재 엔진 등록 리스트] ---
        # 추후 ColumnEngine, StairEngine 구현 시 이 리스트에 추가만 하면 자동 연동!
        self.platform = PlatformEngine(config)
        self.slabs = SlabEngine(config)
        self.walls = WallEngine(config)
        self.columns = ColumnEngine(config)
        self.stairs = StairEngine(config)
        self.escalators = EscalatorEngine(config)
        self.passages = PassageEngine(config)
        self.entrances = EntranceEngine(config)
        self.vents = VentEngine(config)
        self.slabs.check_columns(self.columns)
        self.stairs.check_columns(self.columns)
        self.escalators.check_columns(self.columns)
        self.sub_engines = [self.platform, self.slabs, self.walls, self.columns, self.stairs, self.escalators, self.passages,
                            self.entrances, self.vents]
    @staticmethod
    def _save(doc, filename):
        filename = str(filename)
        os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
        doc.saveas(filename)

    def _init_doc(self) -> tuple[ezdxf.document.Drawing, ezdxf.layouts.Modelspace]:
        doc = ezdxf.new('R2000')
        msp = doc.modelspace()
        for name, attribs in LAYER_DEFINITIONS.items():
            if name not in doc.layers:
                doc.layers.add(name, **attribs)
        return doc, msp

    # --- [1. 3D 메쉬 생성 엔진] ---
    def generate_3d_dxf(self, filename="output/정거장3d모델.dxf") -> str:
        doc, msp = self._init_doc()

        # 선형은 Alignment 인터페이스로만 접근: 중심선은 선형 전 구간, 부재 배치는 world(s, t) 변환
        a = self.cfg.align
        msp.add_polyline3d([(*a.point_at(st), a.elevation_at(st)) for st in a.polyline_stations()],
                           dxfattribs={"layer": "ALIGNMENT_CL"})

        # 모든 부재는 객체당 1회 작도 (구배는 부재 자체의 rise로 표현)
        for engine in self.sub_engines:
            if hasattr(engine, 'add_platform_mesh'):
                engine.add_platform_mesh(msp)
            if hasattr(engine, 'add_slab_mesh'):
                engine.add_slab_mesh(msp)
            if hasattr(engine, 'add_wall_mesh'):
                engine.add_wall_mesh(msp)
            if hasattr(engine, 'add_column_mesh'):
                engine.add_column_mesh(msp)
            if hasattr(engine, 'add_stair_mesh'):
                engine.add_stair_mesh(msp)
            if hasattr(engine, 'add_escalator_mesh'):
                engine.add_escalator_mesh(msp)
            if hasattr(engine, 'add_passage_mesh'):
                engine.add_passage_mesh(msp)
            if hasattr(engine, 'add_vent_mesh'):
                engine.add_vent_mesh(msp)
            if hasattr(engine, 'add_entrance_mesh'):
                engine.add_entrance_mesh(msp)

        self._save(doc, filename)
        return os.path.abspath(filename)

    # --- [2D 공통] ---
    PLAN_CUT_H = PLAN_CUT_H   # 평면도 절단 높이 기본값 (각 층 바닥 슬래브 상면 기준, m)

    def _fmt_sta(self, s: float) -> str:
        """정거장 로컬 거리 s → 절대 측점 문자열 (예: 134.45 → 0+134.45)"""
        sta = self.cfg.station.start_station + s
        km = int(sta // 1000)
        return f"{km}+{sta - km * 1000:06.2f}"

    def _collect(self, hook: str, *args):
        """서브 엔진 중 hook 메서드를 가진 엔진의 ViewItem 을 모두 모음"""
        items = []
        for engine in self.sub_engines:
            if hasattr(engine, hook):
                items.extend(getattr(engine, hook)(*args))
        return items

    # --- [2. 2D 횡단면도 생성 엔진] --- (측점 sta 의 절단면을 BIM 객체에서 직접 추출)
    def generate_section_dxf(self, sta_list: list[float], filename="output/정거장단면도.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.cfg.station
        half_w = p.width / 2.0 + p.max_wall_t                    # 가장 바깥 외곽 기준 (내공 + 가장 두꺼운 벽)
        drawing_spacing = (p.width + 2 * p.max_wall_t) * 2.5
        for idx, sta in enumerate(sta_list):
            x_offset = idx * drawing_spacing
            align_lv = self.cfg.lv(sta)

            floor_top_z = align_lv - p.offset
            floor_bot_z = floor_top_z - p.floor_t
            roof_top_z = floor_top_z + p.height

            # 주석 및 중심선
            msp.add_text(f"SECTION STA. {self._fmt_sta(sta)} (SLOPE {self.cfg.grade_permil(sta):.2f}‰)", dxfattribs={'height': 1.0, 'layer': 'SEC_TEXT'}).set_placement((x_offset, roof_top_z + 3.0))
            msp.add_line((x_offset, floor_bot_z - 2.0), (x_offset, roof_top_z + 2.0), dxfattribs={'layer': 'SEC_CENTER'})
            msp.add_text("C.L.", dxfattribs={'height': 0.6, 'layer': 'SEC_TEXT'}).set_placement((x_offset + 0.2, roof_top_z + 1.0))

            msp.add_text(f"Align.L = {align_lv:.2f}m", dxfattribs={'height': 0.5, 'layer': 'SEC_TEXT'}).set_placement((x_offset + half_w + 1.0, align_lv))
            msp.add_line((x_offset - half_w - 0.5, align_lv), (x_offset + half_w + 0.5, align_lv), dxfattribs={'layer': 'SEC_CENTER'})

            # 부재 단면: 각 엔진(벽체·슬래브·승강장·기둥)이 자기 객체의 절단면을 제공
            draw_view_items(msp, self._collect('section_items', sta), du=x_offset)

        self._save(doc, filename)
        return os.path.abspath(filename)

    # --- [3. 2D 평면도 생성 엔진] --- (층별 절단 높이 FL+cut_h 기준)
    def generate_plan_dxf(self, filename="output/정거장평면도.dxf", mode="auto", floors=None, cut_h=None) -> str:
        """평면도. mode: 'developed' = 선형을 곧게 편 전개 평면도 (s → x, t → y),
        'world' = WCS 실제 평면도 (곡선을 따라 휜 모양), 'auto' = 직선 선형은 전개, 곡선 선형은 WCS.
        floors: 출력할 층 번호 목록 (1 = 최하층, 기본 [1]). 여러 층이면 아래층부터 위로 세로로 늘어놓음
        (첫 층만 실제 좌표, 나머지는 위로 평행 이동). cut_h: 각 층 바닥(FL) 기준 절단 높이 (기본 PLAN_CUT_H)"""
        if mode not in ("auto", "developed", "world"):
            raise ValueError(f"평면도 mode 는 auto / developed / world 중 하나여야 합니다 ({mode!r})")
        p = self.cfg.station
        floors = sorted(set(floors)) if floors else [1]
        bad = [n for n in floors if not (isinstance(n, int) and 1 <= n <= p.floors)]
        if bad:
            raise ValueError(f"평면도 층 번호가 범위(1~{p.floors}) 밖입니다: {bad}")
        cut_h = self.PLAN_CUT_H if cut_h is None else float(cut_h)
        if cut_h <= 0:
            raise ValueError(f"평면도 절단 높이는 0보다 커야 합니다 ({cut_h})")
        curved = not self.cfg.align.is_straight
        world_mode = mode == "world" or (mode == "auto" and curved)
        doc, msp = self._init_doc()
        half_w = p.width / 2.0 + p.max_wall_t                    # 가장 바깥 외곽 기준
        xy = self.cfg.to_world if world_mode else (lambda s, t: (s, t))
        if world_mode:     # 도면 윤곽(측점선 끝 포함)
            edge = [self.cfg.to_world(s, t) for s in self.cfg.sample_s(-p.max_wall_t, p.length + p.max_wall_t) for t in (-half_w - 2.0, half_w + 2.5)]
            y_lo, y_hi = min(y for _, y in edge), max(y for _, y in edge)
            title_at = (min(x for x, _ in edge), y_hi + 6.0)
        else:
            y_lo, y_hi = -half_w - 2.0, half_w + 2.5
            title_at = (0, half_w + 6.0)
        step = (y_hi - y_lo) + 20.0                               # 층 사이 세로 간격 (제목 포함)
        suffix = (" [WCS]" if world_mode else " [DEVELOPED]") if curved else ""

        for k, n in enumerate(floors):
            dv = k * step
            self._plan_frame(msp, xy, world_mode, half_w, dv)
            items = self._collect('plan_items', p.floor_level(n) + cut_h, n)
            draw_view_items(msp, self._plan_items_world(items) if world_mode else items, dv=dv)
            level = f" {p.level_name(n)}" if p.floors > 1 else ""
            msp.add_text(f"STATION PLAN VIEW{level} (CUT LEVEL: FL+{cut_h:.1f}m, CLEAR L={p.length}m, W={p.width}m, STA {self._fmt_sta(0.0)} ~ {self._fmt_sta(p.length)}){suffix}",
                         dxfattribs={'height': 1.5, 'layer': 'PLAN_TEXT'}).set_placement((title_at[0], title_at[1] + dv))

        self._save(doc, filename)
        return os.path.abspath(filename)

    def _plan_frame(self, msp, xy, world_mode, half_w, dv):
        """평면도 바탕: 중심선 + 측점선(선형에 직교) + 측점 글자. dv = 세로 평행 이동량"""
        p = self.cfg.station
        sh = (lambda q: (q[0], q[1] + dv))
        if world_mode:
            a, base = self.cfg.align, p.start_station
            lo, hi = max(a.start_station, base - 10.0), min(a.end_station, base + p.length + 10.0)
            msp.add_lwpolyline([sh(a.point_at(st)) for st in a.sample_stations(lo, hi)], dxfattribs={'layer': 'PLAN_CENTER'})
        else:
            msp.add_line((-10.0, dv), (p.length + 10.0, dv), dxfattribs={'layer': 'PLAN_CENTER'})
        msp.add_text("C.L.", dxfattribs={'height': 1.0, 'layer': 'PLAN_TEXT'}).set_placement(sh(xy(p.length + 12.0, -0.5)))
        for i in range(int(p.length / p.sta_tick + 1e-9) + 1):   # sta_tick > 0 은 StationParameters.validate 가 보장
            cur_sta = i * p.sta_tick
            msp.add_line(sh(xy(cur_sta, -half_w - 2.0)), sh(xy(cur_sta, half_w + 2.0)), dxfattribs={'layer': 'PLAN_SECTION_LINE'})
            attribs = {'height': 0.6, 'layer': 'PLAN_TEXT'}
            if world_mode:      # 글자를 선형 방향으로 돌리되 뒤집히지 않게
                rot = math.degrees(self.cfg.theta_at(cur_sta)) % 360.0
                attribs['rotation'] = rot + 180.0 if 90.0 < rot < 270.0 else rot
            msp.add_text(f"STA.{self._fmt_sta(cur_sta)}", dxfattribs=attribs).set_placement(sh(xy(cur_sta - 1.5, half_w + 2.5)))

    def _plan_items_world(self, items):
        """전개 평면(u=s, v=t)의 윤곽을 WCS 로 변환: 직사각형은 선형을 따라 표본 측점마다 휜 다각형, 원은 중심 이동, 다각형은 꼭짓점 이동"""
        cfg, out = self.cfg, []
        for it in items:
            label = None
            if it.label:
                text, u, v, h, layer = it.label
                label = (text, *cfg.to_world(u, v), h, layer)
            if it.circle is not None:
                cu, cv, r = it.circle
                out.append(ViewItem(it.name, it.layer, circle=(*cfg.to_world(cu, cv), r), label=label))
                continue
            if it.pts is not None:                          # 다각형(출구통로 등 세계 좌표의 곧은 부재): 꼭짓점만 옮김
                out.append(ViewItem(it.name, it.layer, u0=it.u0, u1=it.u1,
                                    pts=[cfg.to_world(u, v) for u, v in it.pts], label=label))
                continue
            ss = cfg.sample_s(it.u0, it.u1)
            pts = [cfg.to_world(s, it.vb0) for s in ss] + [cfg.to_world(s, it.vt0) for s in reversed(ss)]
            out.append(ViewItem(it.name, it.layer, u0=it.u0, u1=it.u1, pts=pts, label=label))
        return out

    # --- [4. 2D 종단면도 생성 엔진] --- (선형 중심에서 offset 떨어진 연직면 절단, 기본 선형 중심)
    def generate_profile_dxf(self, filename="output/정거장종단면도.dxf", offsets=None) -> str:
        """종단면도. offsets: 절단 축 목록 = 선형 중심에서의 직교 거리 t (m, 진행방향 왼쪽 +, 기본 [0]).
        여러 축이면 입력 순서대로 아래로 늘어놓음 (첫 축만 실제 표고, 나머지는 아래로 평행 이동)"""
        doc, msp = self._init_doc()
        p = self.cfg.station
        start_lv = self.cfg.lv(0)
        offsets = [0.0] if not offsets else [float(t) for t in offsets]
        lo = min(self.cfg.lv(s) for s in self.cfg.sample_s(-10.0, p.length + 10.0)) - p.offset - p.floor_t
        hi = max(self.cfg.lv(s) for s in self.cfg.sample_s(-10.0, p.length + 10.0)) - p.offset + p.height
        step = (hi - lo) + 15.0                                   # 축 사이 세로 간격 (제목 포함)
        label = "SLOPE" if self.cfg.align.is_straight else "GRADE AT START"

        for k, t in enumerate(offsets):
            dv = -k * step
            msp.add_line((-10.0, self.cfg.lv(-10.0) + dv), (p.length + 10.0, self.cfg.lv(p.length + 10.0) + dv), dxfattribs={'layer': 'PROF_CENTER'})
            draw_view_items(msp, self._collect('profile_items', t), dv=dv)
            axis = "" if t == 0 and len(offsets) == 1 else f", AXIS: C.L.{t:+.3f}m" if t else ", AXIS: C.L."
            msp.add_text(f"STATION PROFILE VIEW ({label}: {self.cfg.grade_permil(0.0):.2f}‰{axis})", dxfattribs={'height': 1.5, 'layer': 'PROF_TEXT'}).set_placement((0, start_lv + p.height + 5.0 + dv))

        self._save(doc, filename)
        return os.path.abspath(filename)

    def generate_ifc(self, output_path: str = "output/station_model.ifc") -> str:
        exporter = IFCExporter(self.cfg)
        exporter.export_platforms(self.platform)
        exporter.export_slabs(self.slabs)
        exporter.export_walls(self.walls)
        exporter.export_columns(self.columns)
        exporter.export_stairs(self.stairs)
        exporter.export_escalators(self.escalators)
        exporter.export_passages(self.passages)
        exporter.export_vents(self.vents)
        exporter.export_entrances(self.entrances)
        exporter.save(str(output_path))
        return os.path.abspath(output_path)