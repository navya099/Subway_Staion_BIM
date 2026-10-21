import os
import ezdxf

from columns.column_engine import ColumnEngine
from config.cadconfig import LAYER_DEFINITIONS
from config.master_config import StationProjectConfig
from exporter.ifc_exporter import IFCExporter
from helper.view_item import draw_view_items
from platforms.platform_engine import PlatformEngine
from slabs.slab_engine import SlabEngine
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
        self.sub_engines = [self.platform, self.slabs, self.walls, self.columns]
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
        world = self.cfg.to_world
        msp.add_polyline3d([(*a.point_at(st), a.elevation_at(st)) for st in a.polyline_stations()],
                           dxfattribs={"layer": "ALIGNMENT_CL"})

        # 모든 부재는 객체당 1회 작도 (구배는 부재 자체의 rise로 표현)
        for engine in self.sub_engines:
            if hasattr(engine, 'add_platform_mesh'):
                engine.add_platform_mesh(msp, world)
            if hasattr(engine, 'add_slab_mesh'):
                engine.add_slab_mesh(msp, world)
            if hasattr(engine, 'add_wall_mesh'):
                engine.add_wall_mesh(msp, world)
            if hasattr(engine, 'add_column_mesh'):
                engine.add_column_mesh(msp, world)

        self._save(doc, filename)
        return os.path.abspath(filename)

    # --- [2D 공통] ---
    PLAN_CUT_H = 2.0   # 평면도 절단 높이 (바닥 슬래브 상면 기준, m)

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
        half_w = p.width / 2.0
        drawing_spacing = p.width * 2.5
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

    # --- [3. 2D 평면도 생성 엔진] --- (절단 높이 FL+PLAN_CUT_H 기준)
    def generate_plan_dxf(self, filename="output/정거장평면도.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.cfg.station
        half_w = p.width / 2.0

        msp.add_line((-10.0, 0), (p.length + 10.0, 0), dxfattribs={'layer': 'PLAN_CENTER'})
        msp.add_text("C.L.", dxfattribs={'height': 1.0, 'layer': 'PLAN_TEXT'}).set_placement((p.length + 12.0, -0.5))

        for i in range(int(p.length / p.sta_tick + 1e-9) + 1):   # sta_tick > 0 은 StationParameters.validate 가 보장
            cur_sta = i * p.sta_tick
            msp.add_line((cur_sta, -half_w - 2.0), (cur_sta, half_w + 2.0), dxfattribs={'layer': 'PLAN_SECTION_LINE'})
            msp.add_text(f"STA.{self._fmt_sta(cur_sta)}", dxfattribs={'height': 0.6, 'layer': 'PLAN_TEXT'}).set_placement((cur_sta - 1.5, half_w + 2.5))

        draw_view_items(msp, self._collect('plan_items', self.PLAN_CUT_H))
        msp.add_text(f"STATION PLAN VIEW (CUT LEVEL: FL+{self.PLAN_CUT_H:.1f}m, L={p.length}m, W={p.width}m)", dxfattribs={'height': 1.5, 'layer': 'PLAN_TEXT'}).set_placement((0, half_w + 6.0))

        self._save(doc, filename)
        return os.path.abspath(filename)

    # --- [4. 2D 종단면도 생성 엔진] --- (선형 중심 t=0 절단)
    def generate_profile_dxf(self, filename="output/정거장종단면도.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.cfg.station
        start_lv = self.cfg.lv(0)

        msp.add_line((-10.0, self.cfg.lv(-10.0)), (p.length + 10.0, self.cfg.lv(p.length + 10.0)), dxfattribs={'layer': 'PROF_CENTER'})

        draw_view_items(msp, self._collect('profile_items'))
        msp.add_text(f"STATION PROFILE VIEW (SLOPE: {self.cfg.grade_permil(0.0):.2f}‰)", dxfattribs={'height': 1.5, 'layer': 'PROF_TEXT'}).set_placement((0, start_lv + p.height + 5.0))

        self._save(doc, filename)
        return os.path.abspath(filename)

    def generate_ifc(self, output_path: str = "output/station_model.ifc") -> str:
        exporter = IFCExporter(self.cfg)
        exporter.export_platforms(self.platform)
        exporter.export_slabs(self.slabs)
        exporter.export_walls(self.walls)
        exporter.export_columns(self.columns)
        # 추후 Slab, Platform 등도 exporter.export_slabs(...) 형태로 확장
        exporter.save(str(output_path))
        return os.path.abspath(output_path)