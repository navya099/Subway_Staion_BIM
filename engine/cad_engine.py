import math
import os
import ezdxf

from columns.column_engine import ColumnEngine
from config.cadconfig import LAYER_DEFINITIONS
from config.master_config import StationProjectConfig
from exporter.ifc_exporter import IFCExporter
from helper.view_item import ViewItem, draw_view_items
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
    def generate_plan_dxf(self, filename="output/정거장평면도.dxf", mode="auto") -> str:
        """평면도. mode: 'developed' = 선형을 곧게 편 전개 평면도 (s → x, t → y),
        'world' = WCS 실제 평면도 (곡선을 따라 휜 모양), 'auto' = 직선 선형은 전개, 곡선 선형은 WCS"""
        if mode not in ("auto", "developed", "world"):
            raise ValueError(f"평면도 mode 는 auto / developed / world 중 하나여야 합니다 ({mode!r})")
        curved = not self.cfg.align.is_straight
        world_mode = mode == "world" or (mode == "auto" and curved)
        doc, msp = self._init_doc()
        p = self.cfg.station
        half_w = p.width / 2.0
        xy = self.cfg.to_world if world_mode else (lambda s, t: (s, t))

        # 중심선
        if world_mode:
            a, base = self.cfg.align, p.start_station
            lo, hi = max(a.start_station, base - 10.0), min(a.end_station, base + p.length + 10.0)
            msp.add_lwpolyline([a.point_at(st) for st in a.sample_stations(lo, hi)], dxfattribs={'layer': 'PLAN_CENTER'})
        else:
            msp.add_line((-10.0, 0), (p.length + 10.0, 0), dxfattribs={'layer': 'PLAN_CENTER'})
        msp.add_text("C.L.", dxfattribs={'height': 1.0, 'layer': 'PLAN_TEXT'}).set_placement(xy(p.length + 12.0, -0.5))

        # 측점선 (선형에 직교)
        for i in range(int(p.length / p.sta_tick + 1e-9) + 1):   # sta_tick > 0 은 StationParameters.validate 가 보장
            cur_sta = i * p.sta_tick
            msp.add_line(xy(cur_sta, -half_w - 2.0), xy(cur_sta, half_w + 2.0), dxfattribs={'layer': 'PLAN_SECTION_LINE'})
            attribs = {'height': 0.6, 'layer': 'PLAN_TEXT'}
            if world_mode:      # 글자를 선형 방향으로 돌리되 뒤집히지 않게
                rot = math.degrees(self.cfg.theta_at(cur_sta)) % 360.0
                attribs['rotation'] = rot + 180.0 if 90.0 < rot < 270.0 else rot
            msp.add_text(f"STA.{self._fmt_sta(cur_sta)}", dxfattribs=attribs).set_placement(xy(cur_sta - 1.5, half_w + 2.5))

        items = self._collect('plan_items', self.PLAN_CUT_H)
        draw_view_items(msp, self._plan_items_world(items) if world_mode else items)
        suffix = (" [WCS]" if world_mode else " [DEVELOPED]") if curved else ""
        if world_mode:     # 제목은 도면 윤곽(측점선 끝 포함) 바깥 위쪽에 둠
            edge = [self.cfg.to_world(s, t) for s in self.cfg.sample_s(0.0, p.length) for t in (-half_w - 2.0, half_w + 2.5)]
            title_at = (min(x for x, _ in edge), max(y for _, y in edge) + 6.0)
        else:
            title_at = (0, half_w + 6.0)
        msp.add_text(f"STATION PLAN VIEW (CUT LEVEL: FL+{self.PLAN_CUT_H:.1f}m, L={p.length}m, W={p.width}m){suffix}",
                     dxfattribs={'height': 1.5, 'layer': 'PLAN_TEXT'}).set_placement(title_at)

        self._save(doc, filename)
        return os.path.abspath(filename)

    def _plan_items_world(self, items):
        """전개 평면(u=s, v=t)의 윤곽을 WCS 로 변환: 직사각형은 선형을 따라 표본 측점마다 휜 다각형, 원은 중심 이동"""
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
            ss = cfg.sample_s(it.u0, it.u1)
            pts = [cfg.to_world(s, it.vb0) for s in ss] + [cfg.to_world(s, it.vt0) for s in reversed(ss)]
            out.append(ViewItem(it.name, it.layer, u0=it.u0, u1=it.u1, pts=pts, label=label))
        return out

    # --- [4. 2D 종단면도 생성 엔진] --- (선형 중심 t=0 절단)
    def generate_profile_dxf(self, filename="output/정거장종단면도.dxf") -> str:
        doc, msp = self._init_doc()
        p = self.cfg.station
        start_lv = self.cfg.lv(0)

        msp.add_line((-10.0, self.cfg.lv(-10.0)), (p.length + 10.0, self.cfg.lv(p.length + 10.0)), dxfattribs={'layer': 'PROF_CENTER'})

        draw_view_items(msp, self._collect('profile_items'))
        label = "SLOPE" if self.cfg.align.is_straight else "GRADE AT START"
        msp.add_text(f"STATION PROFILE VIEW ({label}: {self.cfg.grade_permil(0.0):.2f}‰)", dxfattribs={'height': 1.5, 'layer': 'PROF_TEXT'}).set_placement((0, start_lv + p.height + 5.0))

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