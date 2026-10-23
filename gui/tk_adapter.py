from columns.column_params import ColumnParameters
from config.alignment_config import AlignmentConfig
from config.master_config import StationProjectConfig
from config.station_config import StationParameters
from gui.column_draft import ColumnDrafts
from platforms.platform_params import PlatformParameters
from platforms.platform_type import PlatformType

# 입력창 키 → 오류 메시지에 쓸 이름
LABELS = {
    "bp_x": "BP X", "bp_y": "BP Y", "bp_z": "BP Z", "ep_x": "EP X", "ep_y": "EP Y", "ep_z": "EP Z",
    "bp_station": "선형 시작 측점", "start_station": "정거장 시작 측점", "length": "정거장 전체 길이",
    "width": "정거장 전체 폭", "offset": "기준선~바닥 상단 오프셋", "height": "정거장 총 높이", "floors": "층수",
    "wall_t": "외벽 두께", "floor_t": "바닥슬래브 두께", "slab_t": "천장 및 중간슬래브 두께",
    "track_spacing": "선로 간격", "plat_offset": "선로중심~승강장 끝단 거리", "plat_thick": "승강장 슬래브 두께",
    "plat_height": "승강장 높이", "support_t": "승강장 지지벽체 두께",
}


def _text(entries, key) -> str:
    return str(entries[key].get()).strip()


def _float(entries, key) -> float:
    text = _text(entries, key)
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"{LABELS.get(key, key)}: 숫자가 아닙니다 ('{text}')") from None


def _int(entries, key) -> int:
    text = _text(entries, key)
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{LABELS.get(key, key)}: 정수가 아닙니다 ('{text}')") from None


class TkAdapter:
    """TK변수 콜렉터"""

    @staticmethod
    def collect_entries(entries) -> StationProjectConfig:
        """모든 탭의 데이터를 수집하여 Master Config 객체로 포장하고 제원을 검증"""
        # 주의: floor_t = 바닥 슬래브, slab_t = 천장/중간 슬래브 (StationParameters 정의와 동일)
        station_p = StationParameters(
            start_station=_float(entries, "start_station"),
            length=_float(entries, "length"),
            width=_float(entries, "width"),
            offset=_float(entries, "offset"),
            height=_float(entries, "height"),
            floors=_int(entries, "floors"),
            wall_t=_float(entries, "wall_t"),
            floor_t=_float(entries, "floor_t"),
            slab_t=_float(entries, "slab_t")
        )
        platform_p = PlatformParameters(
            track_spacing=_float(entries, "track_spacing"),
            plat_offset=_float(entries, "plat_offset"),
            plat_thick=_float(entries, "plat_thick"),
            plat_height=_float(entries, "plat_height"),
            plat_type=PlatformType(int(entries["platform_type"].get())),
            support_t=_float(entries, "support_t")
        )
        column_p = TkAdapter._collect_columns(entries, station_p.floors)
        al = TkAdapter._collect_alignment(entries)
        cfg = StationProjectConfig(station=station_p, platform=platform_p, column=column_p, align=al)
        cfg.validate()
        return cfg

    @staticmethod
    def _collect_alignment(entries):
        """불러온 선형 파일이 있으면 그것을, 없으면 BP/EP 좌표 입력으로 만든 직선을 사용"""
        source = entries.get("alignment_source")
        if source is not None and source.alignment is not None:
            return source.alignment
        return AlignmentConfig(
            bp_station=_float(entries, "bp_station"),
            bp_x=_float(entries, "bp_x"), bp_y=_float(entries, "bp_y"), bp_z=_float(entries, "bp_z"),
            ep_x=_float(entries, "ep_x"), ep_y=_float(entries, "ep_y"), ep_z=_float(entries, "ep_z")
        )

    @staticmethod
    def _collect_columns(entries, floors: int) -> ColumnParameters:
        """기둥 탭의 층별·열별 초안(ColumnDrafts)에서 수집. 초안이 없으면 전 층 기본 1열"""
        drafts = entries.get("column_drafts") or ColumnDrafts()
        sync = entries["sync_all"].get() if "sync_all" in entries else True
        return drafts.to_params(floors, sync=bool(sync))
