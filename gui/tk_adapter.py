from columns.column_params import ColumnParameters
from config.alignment_config import AlignmentConfig
from config.master_config import StationProjectConfig
from config.station_config import StationParameters
from gui.column_draft import ColumnDrafts, level_name
from platforms.platform_params import PlatformParameters
from platforms.platform_type import PlatformType

# 입력창 키 → 오류 메시지에 쓸 이름
LABELS = {
    "bp_x": "BP X", "bp_y": "BP Y", "bp_z": "BP Z", "ep_x": "EP X", "ep_y": "EP Y", "ep_z": "EP Z",
    "bp_station": "선형 시작 측점", "start_station": "정거장 시작 측점", "length": "정거장 전체 길이",
    "width": "정거장 전체 폭", "offset": "기준선~바닥 상단 오프셋", "floors": "층수",
    "floor_t": "본체 바닥 슬래브 두께", "mid_t": "중간층 바닥 슬래브 두께", "roof_t": "본체 천장 슬래브 두께",
    "track_spacing": "선로 간격", "plat_offset": "선로중심~승강장 끝단 거리", "plat_thick": "승강장 슬래브 두께",
    "plat_height": "승강장 높이", "support_t": "승강장 지지벽체 두께",
}


def _text(entries, key) -> str:
    return str(entries[key].get()).strip()


def _float(entries, key, label=None) -> float:
    label = label or LABELS.get(key, key)
    if key not in entries:
        raise ValueError(f"{label}: 입력칸이 없습니다")
    text = _text(entries, key)
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"{label}: 숫자가 아닙니다 ('{text}')") from None


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
        floors = _int(entries, "floors")
        if floors < 1:
            raise ValueError(f"층수: 1 이상이어야 합니다 ({floors})")
        # 층별 높이를 입력받아 합산 (총 높이 = 층 높이의 합). 슬래브는 본체 바닥 / 중간층 바닥 / 본체 천장 세 가지를 따로 받음
        floor_heights = [_float(entries, f"floor_height_{n}", f"{level_name(floors, n)} 층 높이") for n in range(1, floors + 1)]
        wall_ts = [_float(entries, f"wall_t_{n}", f"{level_name(floors, n)} 외벽 두께") for n in range(1, floors + 1)]
        station_p = StationParameters(
            start_station=_float(entries, "start_station"),
            length=_float(entries, "length"),
            width=_float(entries, "width"),
            offset=_float(entries, "offset"),
            floor_heights=floor_heights,
            wall_ts=wall_ts,
            floor_t=_float(entries, "floor_t"),
            mid_t=_float(entries, "mid_t"),
            roof_t=_float(entries, "roof_t")
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
