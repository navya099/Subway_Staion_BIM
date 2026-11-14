from pathlib import Path

from config.master_config import StationProjectConfig
from config.output_config import OutputOptions
from engine.cad_engine import StationCADEngine


class BIMEngine:
    @staticmethod
    def build(cfg: StationProjectConfig, out_dir, options: OutputOptions = None) -> list[str]:
        """설정으로 성과물을 out_dir 에 생성하고 파일 경로 목록을 반환.
        options(출력 탭)로 무엇을 출력할지(3D DXF · 횡단 · 평면 · 종단 · IFC)와 세부 옵션을 정함 (기본: 모두)"""
        opt = options or OutputOptions()
        opt.validate(cfg)                       # 파일을 만들기 전에 검사
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        engine = StationCADEngine(cfg)
        paths = []
        if opt.dxf3d:
            paths.append(engine.generate_3d_dxf(out / "정거장3d모델.dxf"))
        if opt.section:
            paths.append(engine.generate_section_dxf(opt.section_s(cfg), out / "정거장단면도.dxf"))
        if opt.plan:
            paths.append(engine.generate_plan_dxf(out / "정거장평면도.dxf", floors=opt.floors(cfg), cut_h=opt.plan_cut_h))
        if opt.profile:
            paths.append(engine.generate_profile_dxf(out / "정거장종단면도.dxf", offsets=opt.profile_offsets))
        if opt.ifc:
            paths.append(engine.generate_ifc(out / "station_model.ifc"))
        return paths
