from columns.column_params import ColumnParameters
from config.alignment_config import AlignmentConfig
from config.master_config import StationProjectConfig
from config.station_config import StationParameters
from gui.column_draft import ColumnDrafts
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
        """기둥 탭의 층별·열별 초안(ColumnDrafts)에서 수집. 초안이 없으면 전 층 기본 1열"""
        drafts = entries.get("column_drafts") or ColumnDrafts()
        sync = entries["sync_all"].get() if "sync_all" in entries else True
        return drafts.to_params(floors, sync=bool(sync))
