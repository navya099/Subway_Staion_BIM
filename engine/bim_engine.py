from pathlib import Path

from config.master_config import StationProjectConfig
from engine.cad_engine import StationCADEngine


class BIMEngine:
    @staticmethod
    def build(cfg: StationProjectConfig, out_dir) -> list[str]:
        """설정으로 DXF(3D/횡단/평면/종단)와 IFC를 out_dir에 생성하고 파일 경로 목록을 반환"""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        engine = StationCADEngine(cfg)
        length = cfg.station.length
        return [
            engine.generate_3d_dxf(out / "정거장3d모델.dxf"),
            engine.generate_section_dxf([0.0, length / 2.0, length], out / "정거장단면도.dxf"),
            engine.generate_plan_dxf(out / "정거장평면도.dxf"),
            engine.generate_profile_dxf(out / "정거장종단면도.dxf"),
            engine.generate_ifc(out / "station_model.ifc"),
        ]
