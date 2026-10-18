from tkinter import Tk

from columns.column_params import ColumnParameters
from config.alignment_config import AlignmentConfig
from config.master_config import StationProjectConfig
from config.station_config import StationParameters
from platforms.platform_params import PlatformParameters


class TkAdapter:
    """TK변수 콜렉터"""
    @staticmethod
    def collect_entries(entries):
        """모든 탭의 데이터를 수집하여 Master Config 객체로 포장"""
        station_p = StationParameters(
            start_station=float(entries["start_station"].get()),
            length=float(entries["length"].get()),
            width=float(entries["width"].get()),
            offset=float(entries["offset"].get()),
            height=float(entries["height"].get()),
            floor=int(entries["floors"].get()),
            wall_t=float(entries["wall_t"].get()),
            floor_t=float(entries["floor_t"].get()),
            slab_t=float(entries["slab_t"].get())
        )
        platform_p = PlatformParameters(
            track_spacing=float(entries["track_spacing"].get()),
            plat_offset=float(entries["plat_offset"].get()),
            plat_thick=float(entries["plat_thick"].get()),
            plat_height=float(entries["plat_height"].get()),
            plat_type=str(entries["platform_type"].get())
        )
        column_p = ColumnParameters(
            interval=float(entries["col_interval"].get()),
            width=float(entries["col_width"].get()),
            depth=float(entries["col_depth"].get()),
            sync_with_platform=entries['sync_all'].get(),
            target_floors=entries['target_floors'].get(),  # 필요시 확장 가능
        )
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

