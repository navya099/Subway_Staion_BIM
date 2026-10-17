import os
import ezdxf

from config.cadconfig import StationParameters, LAYER_DEFINITIONS


class StationCADEngine:
    def __init__(self, params: StationParameters):
        self.p = params

    def _init_doc(self) -> tuple[ezdxf.document.Drawing, ezdxf.layouts.Modelspace]:
        doc = ezdxf.new('R2000')
        msp = doc.modelspace()
        for name, attribs in LAYER_DEFINITIONS.items():
            if name not in doc.layers:
                doc.layers.add(name, **attribs)
        return doc, msp

    # --- [1. 3D 메쉬 생성 엔진] ---
    def generate_3d_dxf(self, filename="station_sloped_3d.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.p
        half_w = p.width / 2.0

        start_lv = p.calc_align_lv(0)
        end_lv = p.calc_align_lv(p.length)
        msp.add_line((0, 0, start_lv), (p.length, 0, end_lv), dxfattribs={"layer": "ALIGNMENT_CL"})

        seg_size = 5.0
        x_curr = 0.0
        while x_curr < p.length:
            x_next = min(x_curr + seg_size, p.length)
            lv1, lv2 = p.calc_align_lv(x_curr), p.calc_align_lv(x_next)

            f_top1, f_top2 = lv1 - p.offset, lv2 - p.offset
            f_bot1, f_bot2 = f_top1 - p.floor_t, f_top2 - p.floor_t
            r_top1, r_top2 = f_top1 + p.height, f_top2 + p.height
            r_bot1, r_bot2 = r_top1 - p.slab_t, r_top2 - p.slab_t

            # 바닥/천장 슬래브
            for f in self._create_sloped_faces(x_curr, x_next, -half_w, half_w, f_bot1, f_bot2, f_top1, f_top2):
                msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SLAB"})
            for f in self._create_sloped_faces(x_curr, x_next, -half_w, half_w, r_bot1, r_bot2, r_top1, r_top2):
                msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SLAB"})

            # 중간 슬래브
            story_h = p.height / p.floors
            for i in range(1, p.floors):
                z1, z2 = f_top1 + (i * story_h), f_top2 + (i * story_h)
                for f in self._create_sloped_faces(x_curr, x_next, -half_w, half_w, z1 - p.slab_t / 2, z2 - p.slab_t / 2, z1 + p.slab_t / 2, z2 + p.slab_t / 2):
                    msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SLAB"})

            # 좌/우 외벽
            for f in self._create_sloped_faces(x_curr, x_next, -half_w, -half_w + p.wall_t, f_top1, f_top2, r_bot1, r_bot2):
                msp.add_3dface(f, dxfattribs={"layer": "STRUCT_WALL"})
            for f in self._create_sloped_faces(x_curr, x_next, half_w - p.wall_t, half_w, f_top1, f_top2, r_bot1, r_bot2):
                msp.add_3dface(f, dxfattribs={"layer": "STRUCT_WALL"})

            # 시점/종점 마감 벽체
            if x_curr == 0.0:
                for f in self._create_flat_faces(0, p.wall_t, -half_w, half_w, f_top1, r_bot1):
                    msp.add_3dface(f, dxfattribs={"layer": "STRUCT_WALL"})
            if x_next == p.length:
                for f in self._create_flat_faces(p.length - p.wall_t, p.length, -half_w, half_w, f_top2, r_bot2):
                    msp.add_3dface(f, dxfattribs={"layer": "STRUCT_WALL"})

            x_curr = x_next

        doc.saveas(filename)
        return os.path.abspath(filename)

    # --- [2. 2D 횡단면도 생성 엔진] ---
    def generate_section_dxf(self, sta_list: list[float], filename="station_sloped_sections_2d.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.p
        half_w = p.width / 2.0
        drawing_spacing = p.width * 2.5

        for idx, sta in enumerate(sta_list):
            x_offset = idx * drawing_spacing
            align_lv = p.calc_align_lv(sta)

            floor_top_z = align_lv - p.offset
            floor_bot_z = floor_top_z - p.floor_t
            roof_top_z = floor_top_z + p.height
            roof_bot_z = roof_top_z - p.slab_t

            # 주석 및 중심선
            msp.add_text(f"SECTION STA. 0+{int(sta):03d} (SLOPE {p.slope_permil}‰)", dxfattribs={'height': 1.0, 'layer': 'SEC_TEXT'}).set_placement((x_offset, roof_top_z + 3.0))
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

            self._draw_polygons_with_hatch(msp, polygons, poly_layer="SEC_CONCRETE", hatch_layer="SEC_HATCH")

        doc.saveas(filename)
        return os.path.abspath(filename)

    # --- [3. 2D 평면도 생성 엔진] ---
    def generate_plan_dxf(self, filename="station_plan_2d.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.p
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
            cur_sta += p.interval

        msp.add_text(f"STATION PLAN VIEW (CUT LEVEL: FL+2.0m, L={p.length}m, W={p.width}m)", dxfattribs={'height': 1.5, 'layer': 'PLAN_TEXT'}).set_placement((0, half_w + 6.0))

        doc.saveas(filename)
        return os.path.abspath(filename)

    # --- [4. 2D 종단면도 생성 엔진] ---
    def generate_profile_dxf(self, filename="station_profile_2d.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.p

        seg_size = 5.0
        start_lv = p.calc_align_lv(0)
        end_lv = p.calc_align_lv(p.length)

        msp.add_line((-10.0, p.calc_align_lv(-10.0)), (p.length + 10.0, p.calc_align_lv(p.length + 10.0)), dxfattribs={'layer': 'PROF_CENTER'})

        polygons = []
        x_pts = []
        x_c = 0.0
        while x_c <= p.length:
            x_pts.append(x_c)
            x_c += seg_size
        if x_pts[-1] < p.length: x_pts.append(p.length)

        # 천장/바닥 슬래브 종단 띠
        roof_pts = [(x, p.calc_align_lv(x) - p.offset + p.height) for x in x_pts] + [(x, p.calc_align_lv(x) - p.offset + p.height - p.slab_t) for x in reversed(x_pts)]
        floor_pts = [(x, p.calc_align_lv(x) - p.offset) for x in x_pts] + [(x, p.calc_align_lv(x) - p.offset - p.floor_t) for x in reversed(x_pts)]
        polygons.extend([roof_pts, floor_pts])

        # 중간 슬래브
        story_h = p.height / p.floors
        for i in range(1, p.floors):
            mid_pts = [(x, p.calc_align_lv(x) - p.offset + (i * story_h) + p.slab_t / 2) for x in x_pts] + \
                      [(x, p.calc_align_lv(x) - p.offset + (i * story_h) - p.slab_t / 2) for x in reversed(x_pts)]
            polygons.append(mid_pts)

        # 마감 벽체
        f_top_start, f_top_end = start_lv - p.offset, end_lv - p.offset
        polygons.append([(0, f_top_start), (p.wall_t, f_top_start), (p.wall_t, f_top_start + p.height - p.slab_t), (0, f_top_start + p.height - p.slab_t)])
        polygons.append([(p.length - p.wall_t, f_top_end), (p.length, f_top_end), (p.length, f_top_end + p.height - p.slab_t), (p.length - p.wall_t, f_top_end + p.height - p.slab_t)])

        self._draw_polygons_with_hatch(msp, polygons, poly_layer="PROF_CONCRETE", hatch_layer="PROF_HATCH")

        msp.add_text(f"STATION PROFILE VIEW (SLOPE: {p.slope_permil}‰)", dxfattribs={'height': 1.5, 'layer': 'PROF_TEXT'}).set_placement((0, start_lv + p.height + 5.0))

        doc.saveas(filename)
        return os.path.abspath(filename)

    # --- [공통 헬퍼 메서드] ---
    def _draw_polygons_with_hatch(self, msp, polygons, poly_layer, hatch_layer):
        for poly_pts in polygons:
            msp.add_lwpolyline(poly_pts, close=True, dxfattribs={'layer': poly_layer})
            hatch = msp.add_hatch(color=8, dxfattribs={'layer': hatch_layer})
            hatch.set_pattern_fill('ANSI31', scale=0.5)
            path = hatch.paths.add_polyline_path(poly_pts)
            path.closed = True

    def _create_sloped_faces(self, x1, x2, y1, y2, zb1, zb2, zt1, zt2):
        p = [(x1, y1, zb1), (x2, y1, zb2), (x2, y2, zb2), (x1, y2, zb1),
             (x1, y1, zt1), (x2, y1, zt2), (x2, y2, zt2), (x1, y2, zt1)]
        return [(p[0], p[1], p[2], p[3]), (p[4], p[7], p[6], p[5]),
                (p[0], p[4], p[5], p[1]), (p[1], p[5], p[6], p[2]),
                (p[2], p[6], p[7], p[3]), (p[3], p[7], p[4], p[0])]

    def _create_flat_faces(self, x1, x2, y1, y2, z1, z2):
        p = [(x1, y1, z1), (x2, y1, z1), (x2, y2, z1), (x1, y2, z1),
             (x1, y1, z2), (x2, y1, z2), (x2, y2, z2), (x1, y2, z2)]
        return [(p[0], p[1], p[2], p[3]), (p[4], p[7], p[6], p[5]),
                (p[0], p[4], p[5], p[1]), (p[1], p[5], p[6], p[2]),
                (p[2], p[6], p[7], p[3]), (p[3], p[7], p[4], p[0])]