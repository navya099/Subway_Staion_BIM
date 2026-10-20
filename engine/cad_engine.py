import os
import ezdxf
import math

from columns.column_engine import ColumnEngine
from config.cadconfig import LAYER_DEFINITIONS
from config.master_config import StationProjectConfig
from exporter.ifc_exporter import IFCExporter
from helper.box_helper import CommonHelper
from platforms.platform_engine import PlatformEngine
from walls.wall_engine import WallEngine


class StationCADEngine:
    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        # --- [서브 부재 엔진 등록 리스트] ---
        # 추후 ColumnEngine, StairEngine 구현 시 이 리스트에 추가만 하면 자동 연동!
        self.platform = PlatformEngine(config)
        self.walls = WallEngine(config)
        self.columns = ColumnEngine(config)
        self.sub_engines = [self.platform, self.walls, self.columns]
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
    def generate_3d_dxf(self, filename="c:/temp/정거장3d모델.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.cfg.station

        # 선형 제원(BP/EP)은 설정값 사용. bp_x, bp_y = 정거장 시점(s=0)의 WCS 좌표
        a = self.cfg.align
        theta = a.theta
        bp_x, bp_y = self.cfg.origin()
        half_w = p.width / 2.0

        msp.add_line((a.bp_x, a.bp_y, a.bp_z), (a.ep_x, a.ep_y, a.ep_z), dxfattribs={"layer": "ALIGNMENT_CL"})

        seg_size = 5.0
        x_curr = 0.0
        while x_curr < p.length:
            x_next = min(x_curr + seg_size, p.length)
            lv1, lv2 = self.cfg.lv(x_curr), self.cfg.lv(x_next)

            f_top1, f_top2 = lv1 - p.offset, lv2 - p.offset
            f_bot1, f_bot2 = f_top1 - p.floor_t, f_top2 - p.floor_t
            r_top1, r_top2 = f_top1 + p.height, f_top2 + p.height
            r_bot1, r_bot2 = r_top1 - p.slab_t, r_top2 - p.slab_t

            # 바닥/천장 슬래브
            for f in CommonHelper.create_sloped_box_faces_global(x_curr, x_next, -half_w, half_w, f_bot1, f_bot2, f_top1, f_top2, bp_x, bp_y, theta):
                msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SLAB"})
            for f in CommonHelper.create_sloped_box_faces_global(x_curr, x_next, -half_w, half_w, r_bot1, r_bot2, r_top1, r_top2, bp_x, bp_y, theta):
                msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SLAB"})

            # 중간 슬래브
            story_h = p.height / p.floors
            for i in range(1, p.floors):
                z1, z2 = f_top1 + (i * story_h), f_top2 + (i * story_h)
                for f in CommonHelper.create_sloped_box_faces_global(x_curr, x_next, -half_w, half_w, z1 - p.slab_t / 2, z2 - p.slab_t / 2, z1 + p.slab_t / 2, z2 + p.slab_t / 2, bp_x, bp_y, theta):
                    msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SLAB"})

            # --- [서브 엔진들 3D 메쉬 자동 일괄 추가] ---
            for engine in self.sub_engines:
                if hasattr(engine, 'add_platform_mesh'):
                    engine.add_platform_mesh(msp, x_curr, x_next, f_top1, f_top2, half_w, bp_x, bp_y, theta)
            x_curr = x_next

        # 벽체·기둥은 세그먼트 루프 밖에서 한 번만 작도 (구배는 부재 자체의 rise로 표현)
        for engine in self.sub_engines:
            if hasattr(engine, 'add_wall_mesh'):
                engine.add_wall_mesh(msp, bp_x, bp_y, theta)
            if hasattr(engine, 'add_column_mesh'):
                engine.add_column_mesh(msp, bp_x, bp_y, theta)

        self._save(doc, filename)
        return os.path.abspath(filename)

    # --- [2. 2D 횡단면도 생성 엔진] ---
    def generate_section_dxf(self, sta_list: list[float], filename="c:/temp/정거장단면도.dxf") -> str:
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
            roof_bot_z = roof_top_z - p.slab_t

            # 주석 및 중심선
            msp.add_text(f"SECTION STA. 0+{int(sta):03d} (SLOPE {self.cfg.align.slope:.2f}‰)", dxfattribs={'height': 1.0, 'layer': 'SEC_TEXT'}).set_placement((x_offset, roof_top_z + 3.0))
            msp.add_line((x_offset, floor_bot_z - 2.0), (x_offset, roof_top_z + 2.0), dxfattribs={'layer': 'SEC_CENTER'})
            msp.add_text("C.L.", dxfattribs={'height': 0.6, 'layer': 'SEC_TEXT'}).set_placement((x_offset + 0.2, roof_top_z + 1.0))

            msp.add_text(f"Align.L = {align_lv:.2f}m", dxfattribs={'height': 0.5, 'layer': 'SEC_TEXT'}).set_placement((x_offset + half_w + 1.0, align_lv))
            msp.add_line((x_offset - half_w - 0.5, align_lv), (x_offset + half_w + 0.5, align_lv), dxfattribs={'layer': 'SEC_CENTER'})

            # 다각형 부재 생성
            polygons = [
                [(x_offset - half_w, floor_bot_z), (x_offset + half_w, floor_bot_z), (x_offset + half_w, floor_top_z), (x_offset - half_w, floor_top_z)],
                [(x_offset - half_w, roof_bot_z), (x_offset + half_w, roof_bot_z), (x_offset + half_w, roof_top_z), (x_offset - half_w, roof_top_z)],
                [(x_offset - half_w, floor_top_z), (x_offset - half_w + p.wall_t, floor_top_z), (x_offset - half_w + p.wall_t, roof_bot_z), (x_offset - half_w, roof_bot_z)],
                [(x_offset + half_w - p.wall_t, floor_top_z), (x_offset + half_w, floor_top_z), (x_offset + half_w, roof_bot_z), (x_offset + half_w - p.wall_t, roof_bot_z)]
            ]

            # 승강장 추가
            # --- [서브 엔진들 2D 횡단면 일괄 추가] ---
            for engine in self.sub_engines:
                if hasattr(engine, 'add_platform_section'):
                    engine.add_platform_section(floor_top_z, x_offset, half_w, msp)
                if hasattr(engine, 'add_column_section'):
                    engine.add_column_section(sta, x_offset, msp)

            story_h = p.height / p.floors
            for i in range(1, p.floors):
                z_pos = floor_top_z + (i * story_h)
                polygons.append([
                    (x_offset - half_w + p.wall_t, z_pos - p.slab_t / 2),
                    (x_offset + half_w - p.wall_t, z_pos - p.slab_t / 2),
                    (x_offset + half_w - p.wall_t, z_pos + p.slab_t / 2),
                    (x_offset - half_w + p.wall_t, z_pos + p.slab_t / 2)
                ])
                msp.add_text(f"B{p.floors - i + 1}F SLAB", dxfattribs={'height': 0.4, 'layer': 'SEC_TEXT'}).set_placement((x_offset + half_w + 1.0, z_pos))

            CommonHelper.draw_polygons_with_hatch(msp, polygons, poly_layer="SEC_CONCRETE", hatch_layer="SEC_HATCH")


        self._save(doc, filename)
        return os.path.abspath(filename)

    # --- [3. 2D 평면도 생성 엔진] ---
    def generate_plan_dxf(self, filename="c:/temp/정거장평면도.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.cfg.station
        half_w = p.width / 2.0

        msp.add_line((-10.0, 0), (p.length + 10.0, 0), dxfattribs={'layer': 'PLAN_CENTER'})
        msp.add_text("C.L.", dxfattribs={'height': 1.0, 'layer': 'PLAN_TEXT'}).set_placement((p.length + 12.0, -0.5))

        msp.add_lwpolyline([(0, -half_w), (p.length, -half_w), (p.length, half_w), (0, half_w)], close=True, dxfattribs={'layer': 'PLAN_OUTLINE'})
        msp.add_lwpolyline([(p.wall_t, -half_w + p.wall_t), (p.length - p.wall_t, -half_w + p.wall_t),
                            (p.length - p.wall_t, half_w - p.wall_t), (p.wall_t, half_w - p.wall_t)], close=True, dxfattribs={'layer': 'PLAN_OUTLINE'})

        cur_sta = 0.0
        while cur_sta <= p.length:
            msp.add_line((cur_sta, -half_w - 2.0), (cur_sta, half_w + 2.0), dxfattribs={'layer': 'PLAN_SECTION_LINE'})
            msp.add_text(f"STA.0+{int(cur_sta):03d}", dxfattribs={'height': 0.6, 'layer': 'PLAN_TEXT'}).set_placement((cur_sta - 1.5, half_w + 2.5))
            cur_sta += p.sta_tick

        # --- [서브 엔진들 2D 평면 요소 일괄 추가] ---
        for engine in self.sub_engines:
            if hasattr(engine, 'add_platform_plan'):
                engine.add_platform_plan(msp)
            if hasattr(engine, 'add_column_plan'):
                engine.add_column_plan(msp)
        msp.add_text(f"STATION PLAN VIEW (CUT LEVEL: FL+2.0m, L={p.length}m, W={p.width}m)", dxfattribs={'height': 1.5, 'layer': 'PLAN_TEXT'}).set_placement((0, half_w + 6.0))

        self._save(doc, filename)
        return os.path.abspath(filename)

    # --- [4. 2D 종단면도 생성 엔진] ---
    def generate_profile_dxf(self, filename="c:/temp/정거장종단면도.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.cfg.station

        seg_size = 5.0
        start_lv = self.cfg.lv(0)
        end_lv = self.cfg.lv(p.length)

        msp.add_line((-10.0, self.cfg.lv(-10.0)), (p.length + 10.0, self.cfg.lv(p.length + 10.0)), dxfattribs={'layer': 'PROF_CENTER'})

        polygons = []
        x_pts = []
        x_c = 0.0
        while x_c <= p.length:
            x_pts.append(x_c)
            x_c += seg_size
        if x_pts[-1] < p.length: x_pts.append(p.length)

        # 천장/바닥 슬래브 종단 띠
        roof_pts = [(x, self.cfg.lv(x) - p.offset + p.height) for x in x_pts] + [(x, self.cfg.lv(x) - p.offset + p.height - p.slab_t) for x in reversed(x_pts)]
        floor_pts = [(x, self.cfg.lv(x) - p.offset) for x in x_pts] + [(x, self.cfg.lv(x) - p.offset - p.floor_t) for x in reversed(x_pts)]
        polygons.extend([roof_pts, floor_pts])

        # 중간 슬래브
        story_h = p.height / p.floors
        for i in range(1, p.floors):
            mid_pts = [(x, self.cfg.lv(x) - p.offset + (i * story_h) + p.slab_t / 2) for x in x_pts] + \
                      [(x, self.cfg.lv(x) - p.offset + (i * story_h) - p.slab_t / 2) for x in reversed(x_pts)]
            polygons.append(mid_pts)

        # 마감 벽체
        f_top_start, f_top_end = start_lv - p.offset, end_lv - p.offset
        polygons.append([(0, f_top_start), (p.wall_t, f_top_start), (p.wall_t, f_top_start + p.height - p.slab_t), (0, f_top_start + p.height - p.slab_t)])
        polygons.append([(p.length - p.wall_t, f_top_end), (p.length, f_top_end), (p.length, f_top_end + p.height - p.slab_t), (p.length - p.wall_t, f_top_end + p.height - p.slab_t)])

        CommonHelper.draw_polygons_with_hatch(msp, polygons, poly_layer="PROF_CONCRETE", hatch_layer="PROF_HATCH")

        # --- [서브 엔진들 2D 종단면 일괄 추가] ---
        for engine in self.sub_engines:
            if hasattr(engine, 'add_platform_profile'):
                engine.add_platform_profile(msp, x_pts)
            if hasattr(engine, 'add_column_profile'):
                engine.add_column_profile(msp, x_pts)
        msp.add_text(f"STATION PROFILE VIEW (SLOPE: {self.cfg.align.slope:.2f}‰)", dxfattribs={'height': 1.5, 'layer': 'PROF_TEXT'}).set_placement((0, start_lv + p.height + 5.0))

        self._save(doc, filename)
        return os.path.abspath(filename)

    def generate_ifc(self, output_path: str = "c:/temp/station_model.ifc") -> str:
        exporter = IFCExporter(self.cfg)
        exporter.export_walls(self.walls)
        exporter.export_columns(self.columns)
        # 추후 Slab, Platform 등도 exporter.export_slabs(...) 형태로 확장
        exporter.save(str(output_path))
        return os.path.abspath(output_path)