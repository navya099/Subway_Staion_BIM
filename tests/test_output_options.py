"""출력 옵션 (출력 탭): 성과물 선택, 층별 평면도, 종단 절단 축, 단면 측점·연속 단면"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import pytest

from config.output_config import MAX_SECTIONS, OutputOptions
from engine.bim_engine import BIMEngine
from engine.cad_engine import StationCADEngine
from gui.print_draft import PrintDraft, parse_station, preview
from test_curved import NO_COLS, curved_cfg
from test_patch import _q, make_cfg, user_example
from test_stairs import stair


def texts(path, prefix=""):
    return [t.dxf.text for t in ezdxf.readfile(path).modelspace().query("TEXT") if t.dxf.text.startswith(prefix)]


def circles(path):
    return list(ezdxf.readfile(path).modelspace().query('CIRCLE[layer=="PLAN_OUTLINE"]'))


# ===================================================== 성과물 선택
@pytest.mark.parametrize("flags,names", [
    ({}, ["정거장3d모델.dxf", "정거장단면도.dxf", "정거장평면도.dxf", "정거장종단면도.dxf", "station_model.ifc"]),
    ({"dxf3d": False, "ifc": False}, ["정거장단면도.dxf", "정거장평면도.dxf", "정거장종단면도.dxf"]),
    ({"plan": False, "profile": False, "section": False}, ["정거장3d모델.dxf", "station_model.ifc"]),
    ({"dxf3d": False, "plan": False, "profile": False, "section": False}, ["station_model.ifc"]),
])
def test_only_selected_outputs_are_written(tmp_path, flags, names):
    paths = BIMEngine.build(make_cfg(user_example()), tmp_path, OutputOptions(**flags))
    assert [os.path.basename(p) for p in paths] == names and sorted(os.listdir(tmp_path)) == sorted(names)


def test_nothing_selected_is_error_before_writing(tmp_path):
    off = dict(dxf3d=False, ifc=False, plan=False, profile=False, section=False)
    with pytest.raises(ValueError, match="하나 이상"):
        BIMEngine.build(make_cfg(user_example()), tmp_path / "out", OutputOptions(**off))
    assert not (tmp_path / "out").exists()


# ===================================================== 평면도: 층 선택 · 절단 높이
def test_plan_per_floor_titles_and_columns(tmp_path):
    eng = StationCADEngine(make_cfg(user_example()))
    one = eng.generate_plan_dxf(tmp_path / "1.dxf")                                       # 기본 = 최하층
    assert len(texts(one, "STATION PLAN VIEW")) == 1 and "B3F" in texts(one, "STATION PLAN VIEW")[0]
    b2 = eng.generate_plan_dxf(tmp_path / "2.dxf", floors=[2])
    n_b2 = sum(len(p.columns) for p in eng.columns.column_packages if p.level == "B2F")
    assert len(circles(b2)) == n_b2 and len(circles(one)) == 0                           # B3F 는 사각기둥만
    allf = eng.generate_plan_dxf(tmp_path / "a.dxf", floors=[3, 1, 2])
    titles = texts(allf, "STATION PLAN VIEW")
    assert [t.split()[3] for t in titles] == ["B3F", "B2F", "B1F"]                         # 아래층부터 위로
    ys = sorted(t.dxf.insert[1] for t in ezdxf.readfile(allf).modelspace().query("TEXT") if t.dxf.text.startswith("STATION PLAN"))
    assert ys[0] < ys[1] < ys[2]
    n_circ = sum(len(p.columns) for p in eng.columns.column_packages if p.level == "B2F") + \
        sum(1 for p in eng.columns.column_packages if p.level == "B1F" for c in p.columns if hasattr(c.shape, "radius"))
    assert len(circles(allf)) == n_circ
    first = {(round(c.dxf.center[0], 4), round(c.dxf.center[1], 4)) for c in circles(b2)}
    stacked = {(round(c.dxf.center[0], 4), round(c.dxf.center[1], 4)) for c in circles(allf)}
    assert not first & stacked                                                             # 위로 옮겨 그림 (첫 층만 실제 좌표)


def test_plan_shows_stair_only_on_its_floor(tmp_path):
    cfg = make_cfg(user_example())
    cfg.stairs = [stair(lower=2, s=40.0, name="ST2")]
    eng = StationCADEngine(cfg)
    assert not _q(eng.generate_plan_dxf(tmp_path / "1.dxf", floors=[1]), "PLAN_STAIR")
    assert _q(eng.generate_plan_dxf(tmp_path / "2.dxf", floors=[2]), "PLAN_STAIR")
    assert "ST2 UP >" in texts(eng.generate_plan_dxf(tmp_path / "3.dxf", floors=[2]))


def test_plan_cut_height_changes_title_and_curved_world_mode(tmp_path):
    eng = StationCADEngine(curved_cfg(columns=NO_COLS()))
    path = eng.generate_plan_dxf(tmp_path / "c.dxf", floors=[1, 2], cut_h=1.5)
    titles = texts(path, "STATION PLAN VIEW")
    assert len(titles) == 2 and all("FL+1.5m" in t and t.endswith("[WCS]") for t in titles)
    with pytest.raises(ValueError, match="범위"):
        eng.generate_plan_dxf(tmp_path / "x.dxf", floors=[9])


# ===================================================== 종단면도: 절단 축
def test_profile_offsets_cut_side_wall_and_platform(tmp_path):
    eng = StationCADEngine(make_cfg(user_example()))
    p = eng.cfg.station
    base = eng.generate_profile_dxf(tmp_path / "0.dxf")
    wall_t = p.width / 2.0 + p.wall_ts[0] / 2.0                                            # 왼쪽 측벽 두께 가운데
    side = eng.generate_profile_dxf(tmp_path / "w.dxf", offsets=[wall_t])
    widest = max(abs(pl.get_points()[0][0] - q[0]) for pl in _q(side, "PROF_CONCRETE") for q in pl.get_points())
    assert widest > p.length                                                              # 측벽 전체 길이가 잘림
    plat = eng.cfg.platform
    t_plat = plat.track_spacing / 2.0 + plat.plat_offset + 1.0                            # 왼쪽 승강장 슬래브 위
    assert {it.layer for it in eng.platform.profile_items(0.0)} == {"PROF_BEYOND"}            # 중심: 측면에 보임
    cut_items = [it for it in eng.platform.profile_items(t_plat) if it.layer == "PROF_CONCRETE"]
    assert cut_items and all(it.hatch_layer == "PROF_HATCH" for it in cut_items)              # 승강장 위: 단면(해치)
    beyond = [it for it in eng.platform.profile_items(t_plat) if it.layer == "PROF_BEYOND"]
    assert len(beyond) == len(eng.platform.profile_items(0.0)) and len(_q(base, "PROF_CONCRETE")) > 0   # 반대쪽 승강장은 측면에 보임


def test_profile_multiple_axes_stacked_with_axis_titles(tmp_path):
    eng = StationCADEngine(make_cfg(user_example()))
    path = eng.generate_profile_dxf(tmp_path / "m.dxf", offsets=[0.0, 2.2, -2.2])
    titles = texts(path, "STATION PROFILE VIEW")
    assert [t.split("AXIS: ")[1].rstrip(")") for t in titles] == ["C.L.", "C.L.+2.200m", "C.L.-2.200m"]
    ys = [t.dxf.insert[1] for t in ezdxf.readfile(path).modelspace().query("TEXT") if t.dxf.text.startswith("STATION PROFILE")]
    assert ys[0] > ys[1] > ys[2]
    single = texts(eng.generate_profile_dxf(tmp_path / "s.dxf"), "STATION PROFILE VIEW")[0]
    assert "AXIS" not in single                                                            # 기본(중심 1개)은 예전 제목


# ===================================================== 단면도: 측점 · 연속 단면
def test_section_positions():
    cfg = make_cfg(user_example())
    cfg.station.start_station = 1000.0
    assert OutputOptions().section_s(cfg) == pytest.approx([49.5, 99.0, 148.5])          # 기본 1/4 · 1/2 · 3/4
    o = OutputOptions(section_stations=[1150.0, 1010.0, 1010.0005], section_interval=50.0, section_from=1020.0)
    assert o.section_s(cfg) == pytest.approx([10.0, 20.0, 70.0, 120.0, 150.0, 170.0])      # 정렬 + 1mm 중복 제거
    assert OutputOptions(section_interval=99.0).section_s(cfg) == pytest.approx([0.0, 99.0, 198.0])


@pytest.mark.parametrize("kw,msg", [
    ({"section_stations": [5000.0]}, "내공 범위"),
    ({"section_interval": 0.0}, "0보다"),
    ({"section_interval": 10.0, "section_from": 150.0, "section_to": 100.0}, "앞입니다"),
    ({"section_interval": 10.0, "section_to": 900.0}, "범위"),
    ({"section_interval": 198.0 / (MAX_SECTIONS + 5)}, "너무 많습니다"),
    ({"plan_floors": []}, "층을 하나 이상"),
    ({"plan_floors": [4]}, "범위"),
    ({"plan_cut_h": 0.0}, "0보다"),
    ({"plan_cut_h": 5.9}, "내공 높이"),
    ({"profile_offsets": []}, "하나 이상"),
    ({"profile_offsets": [30.0]}, "외곽"),
])
def test_invalid_options(kw, msg):
    with pytest.raises(ValueError, match=msg):
        OutputOptions(**kw).validate(make_cfg(user_example()))


def test_disabled_output_options_are_not_checked():
    OutputOptions(plan=False, plan_floors=[], profile=False, profile_offsets=[], section=False,
                  section_stations=[1e9]).validate(make_cfg(user_example()))


def test_section_dxf_has_one_drawing_per_station(tmp_path):
    paths = BIMEngine.build(make_cfg(user_example()), tmp_path, OutputOptions(
        dxf3d=False, ifc=False, plan=False, profile=False, section_stations=[10.0], section_interval=60.0))
    assert len(texts(paths[0], "SECTION STA.")) == 5                                       # 10 + (0, 60, 120, 180)


# ===================================================== 입력 초안
def test_parse_station_formats():
    assert parse_station("0+134.45", "") == pytest.approx(134.45)
    assert parse_station(" 12 + 3.5 ", "") == pytest.approx(12003.5)
    assert parse_station("-5", "") == -5.0
    with pytest.raises(ValueError, match="측점이 올바르지"):
        parse_station("1+", "단면도")


def test_draft_to_options():
    d = PrintDraft(profile_track_l=True, profile_track_r=True, profile_offsets="1.5, 0, -2.2",
                   section_stations="0+010, 50; 60", section_continuous=True, section_interval="25", section_to="0+100",
                   plan_floors={2}, plan_cut_h="1.8", ifc=False)
    o = d.to_options(4.4)
    assert o.profile_offsets == pytest.approx([0.0, 2.2, -2.2, 1.5])                      # 중심 → 선로 → 직접, 중복 제거
    assert o.section_stations == [10.0, 50.0, 60.0] and (o.section_interval, o.section_from, o.section_to) == (25.0, None, 100.0)
    assert (o.plan_floors, o.plan_cut_h, o.ifc) == ([2], 1.8, False)
    assert PrintDraft(section_continuous=False).to_options(4.4).section_interval is None


@pytest.mark.parametrize("field,value,msg", [
    ("plan_cut_h", "x", "평면도: 절단 높이"),
    ("profile_offsets", "1, a", "종단면도: 축 offset"),
    ("section_stations", "1+2+3", "단면도: 측점"),
])
def test_draft_errors(field, value, msg):
    d = PrintDraft(**{field: value})
    with pytest.raises(ValueError, match=msg):
        d.to_options(4.4)
    setattr(d, field.split("_")[0] if field != "plan_cut_h" else "plan", False)          # 그 성과물을 끄면 검사하지 않음
    d.to_options(4.4)


def test_draft_floors_follow_floor_count():
    d = PrintDraft(plan_floors={1, 2})
    assert d.ensure_floors(3, 2) and d.plan_floors == {1, 2, 3}                           # 모두 골랐으면 새 층도
    d.plan_floors = {3}
    assert d.ensure_floors(2, 3) and d.plan_floors == set()
    d.plan_floors = {1}
    assert not d.ensure_floors(4, 2) and d.plan_floors == {1}


def test_preview_text():
    d = PrintDraft(section_continuous=True, section_interval="50")
    txt = preview(d, 100.0, 198.0, 4.4, level_name=lambda n: f"L{n}")
    assert "3D DXF, 평면도, 종단면도, 단면도, IFC" in txt and "L1, L2" in txt and "단면: 4개 (STA 100.00, 150.00, 200.00, 250.00)" in txt
    assert "기본 1/4" in preview(PrintDraft(), 0.0, 100.0, 4.4)
    assert "하나 이상" in preview(PrintDraft(dxf3d=False, ifc=False, plan=False, profile=False, section=False), 0, 1, 1)
    assert "확인" in preview(PrintDraft(plan_cut_h="?"), 0.0, 100.0, 4.4)
