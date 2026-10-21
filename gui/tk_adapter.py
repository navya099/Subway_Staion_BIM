from columns.column_params import (ColumnParameters, ColumnRowSpec, ColumnSpec, FloorColumnSpec)
from columns.column_shape_type import ColumnShapeType
from config.alignment_config import AlignmentConfig
from config.master_config import StationProjectConfig
from config.station_config import StationParameters
from platforms.platform_params import PlatformParameters


class TkAdapter:
    """TK변수 콜렉터"""

    @staticmethod
    def collect_entries(entries):
        """모든 탭의 데이터를 수집하여 Master Config 객체로 포장"""
        # 주의: floor_t = 바닥 슬래브, slab_t = 천장/중간 슬래브 (StationParameters 정의와 동일)
        station_p = StationParameters(
            start_station=float(entries["start_station"].get()),
            length=float(entries["length"].get()),
            width=float(entries["width"].get()),
            offset=float(entries["offset"].get()),
            height=float(entries["height"].get()),
            floors=int(entries["floors"].get()),
            wall_t=float(entries["wall_t"].get()),
            floor_t=float(entries["floor_t"].get()),
            slab_t=float(entries["slab_t"].get())
        )
        platform_p = PlatformParameters(
            track_spacing=float(entries["track_spacing"].get()),
            plat_offset=float(entries["plat_offset"].get()),
            plat_thick=float(entries["plat_thick"].get()),
            plat_height=float(entries["plat_height"].get()),
            plat_type=str(entries["platform_type"].get()),
            support_t=float(entries["support_t"].get())
        )
        column_p = TkAdapter._collect_columns(entries, station_p.floors)
        al = AlignmentConfig(
            bp_station=float(entries["bp_station"].get()),
            bp_x=float(entries["bp_x"].get()),
            bp_y=float(entries["bp_y"].get()),
            bp_z=float(entries["bp_z"].get()),
            ep_x=float(entries["ep_x"].get()),
            ep_y=float(entries["ep_y"].get()),
            ep_z=float(entries["ep_z"].get())
        )
        return StationProjectConfig(station=station_p, platform=platform_p, column=column_p, align=al)

    @staticmethod
    def _collect_columns(entries, floors: int) -> ColumnParameters:
        """층별 기둥 입력 → 층당 1열(중앙) 배치. 열별 입력 UI가 생기면 rows를 여러 개로 확장하면 됨."""
        interval = float(entries["col_interval"].get())
        g_w, g_d = float(entries["col_width"].get()), float(entries["col_depth"].get())

        def num(key, default):
            w = entries.get(key)
            return float(w.get()) if w is not None else default

        per_floor = {}
        for n in range(1, floors + 1):  # n=1: 최하층 (UI의 floor_{n-1}_* 와 대응)
            idx = n - 1
            type_w = entries.get(f"floor_{idx}_type")
            if type_w is not None and type_w.get() == '원기둥':
                spec = ColumnSpec(ColumnShapeType.CIRCLE, radius=num(f"floor_{idx}_radius", 0.5))
            else:
                spec = ColumnSpec(ColumnShapeType.RECTANGLE,
                                  width=num(f"floor_{idx}_width", g_w), depth=num(f"floor_{idx}_depth", g_d))
            per_floor[n] = FloorColumnSpec(rows=[ColumnRowSpec(t_offset=0.0, interval=interval, pattern=[spec])])
        return ColumnParameters(sync_with_platform=bool(entries["sync_all"].get()), floors=per_floor)
