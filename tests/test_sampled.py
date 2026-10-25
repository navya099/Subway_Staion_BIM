"""좌표 목록(x, y, z) 선형: SampledAlignment + 텍스트 파서 테스트"""
import math, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import ifcopenshell
import pytest

from config.alignment_io import alignment_from_dict, describe, load_alignment
from config.alignment_text import XYZOptions, parse_xyz_text, preview_lines
from config.sampled_alignment import SampledAlignment
from engine.bim_engine import BIMEngine
from engine.cad_engine import StationCADEngine
from helper import prism_member as PM
from test_curved import (NO_COLS, ROOT, curved_cfg, interference_pairs, members, s_curve)
from test_patch import make_cfg, user_example

truth = s_curve()
SAMPLE_TXT = os.path.join(ROOT, "samples", "alignment_xyz_example.txt")


def sample_rows(a=300.0, b=800.0, step=1.0, dec=3, noise=0.0, seed=1):
    rnd, rows = random.Random(seed), []
    for i in range(int(round((b - a) / step)) + 1):
        sta = a + i * step
        x, y = truth.point_at(sta); z = truth.elevation_at(sta)
        if noise:
            x, y, z = x + rnd.gauss(0, noise), y + rnd.gauss(0, noise), z + rnd.gauss(0, noise)
        rows.append((round(x, dec), round(y, dec), round(z, dec)) if dec is not None else (x, y, z))
    return rows


def build(rows, start=300.0, **kw):
    xs, ys, zs = zip(*rows)
    return SampledAlignment(list(xs), list(ys), list(zs), start_station=start, **kw)


def errors(al, a=300.0, b=800.0):
    stas = [a + 20 + i * 0.37 for i in range(int((b - a - 40) / 0.37))]
    e = dict(pos=0.0, az=0.0, z=0.0, grade=0.0, curv=0.0)
    for s in stas:
        e["pos"] = max(e["pos"], math.hypot(*(u - v for u, v in zip(al.point_at(s), truth.point_at(s)))))
        e["az"] = max(e["az"], abs(al.azimuth_at(s) - truth.azimuth_at(s)))
        e["z"] = max(e["z"], abs(al.elevation_at(s) - truth.elevation_at(s)))
        e["grade"] = max(e["grade"], abs(al.grade_at(s) - truth.grade_at(s)) * 1000)
        e["curv"] = max(e["curv"], abs(al.curvature_at(s) - truth.curvature_at(s)))
    return e


# ===================================================== 복원 정확도
def test_reconstructs_exact_1m_coordinates():
    e = errors(build(sample_rows(dec=None)))
    assert e["pos"] < 3e-4 and e["z"] < 2e-4 and e["az"] < 3e-4 and e["grade"] < 0.3 and e["curv"] < 8e-5


def test_reconstructs_mm_rounded_coordinates():
    """Civil 3D / Bentley 의 일반적인 출력(소수 3자리)"""
    e = errors(build(sample_rows(dec=3)))
    assert e["pos"] < 1e-3 and e["z"] < 1e-3 and e["az"] < 8e-4 and e["grade"] < 0.8 and e["curv"] < 2e-4


def test_cm_rounded_coordinates_need_wider_smoothing_and_warn():
    rows = sample_rows(dec=2)
    narrow = build(rows)
    assert any("잡음" in w and "8~12m" in w for w in narrow.warnings)                 # 안내 경고
    wide = build(rows, smooth_m=10.0)
    assert not any("잡음" in w for w in wide.warnings)
    e_n, e_w = errors(narrow), errors(wide)
    assert e_w["curv"] < e_n["curv"] and e_w["az"] <= e_n["az"] * 1.01               # 넓힐수록 매끈
    assert e_w["pos"] < 8e-3 and e_w["curv"] < 4e-4 and e_w["az"] < 4e-3


def test_sparse_5m_spacing_is_still_accurate():
    assert errors(build(sample_rows(step=5.0, dec=None)))["pos"] < 4e-3


def test_no_noise_warning_for_clean_data():
    assert build(sample_rows(dec=3)).warnings == []


def test_smoothing_zero_uses_minimal_windows():
    al = build(sample_rows(dec=None), smooth_m=0.0)
    assert errors(al)["pos"] < 1e-3


# ===================================================== 선형 인터페이스 동작
def test_stations_come_from_plan_distance_plus_start():
    rows = sample_rows(dec=None)
    al = build(rows, start=1234.5)
    plan = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(rows, rows[1:]))
    assert al.start_station == 1234.5 and al.end_station == pytest.approx(1234.5 + plan)
    assert al.point_at(1234.5) == pytest.approx(rows[0][:2], abs=1e-3)
    assert al.point_at(al.end_station) == pytest.approx(rows[-1][:2], abs=1e-3)
    assert al.point_count == 501 and al.max_spacing == pytest.approx(1.0, abs=1e-3) and not al.is_straight
    al.validate()


def test_extrapolates_along_end_tangents():
    al = build(sample_rows(dec=None))
    x0, y0 = al.point_at(al.end_station); x1, y1 = al.point_at(al.end_station + 10.0)
    assert math.hypot(x1 - x0, y1 - y0) == pytest.approx(10.0, rel=1e-9)
    assert al.azimuth_at(al.end_station + 10.0) == pytest.approx(al.azimuth_at(al.end_station))
    assert al.elevation_at(al.start_station - 5.0) == pytest.approx(al.elevation_at(al.start_station) - 5.0 * al.grade_at(al.start_station))


def test_continuity_at_input_points():
    al = build(sample_rows(dec=3))
    for sta in (350.0, 400.0, 555.0, 700.0):
        for f in (lambda s: al.point_at(s)[0], lambda s: al.point_at(s)[1], al.elevation_at, al.grade_at):
            assert f(sta - 1e-6) == pytest.approx(f(sta + 1e-6), abs=2e-6)
        d = (al.azimuth_at(sta + 1e-6) - al.azimuth_at(sta - 1e-6) + math.pi) % (2 * math.pi) - math.pi
        assert abs(d) < 1e-6


def test_curvature_sign_and_values_follow_the_true_alignment():
    al = build(sample_rows(a=200.0, b=950.0, dec=3), start=200.0)
    assert truth.curvature_at(260.0) == 0.0 and abs(al.curvature_at(260.0)) < 1e-4            # TS(304) 앞의 직선
    assert al.curvature_at(320.0) == pytest.approx(truth.curvature_at(320.0), abs=1e-4)          # 완화곡선: 곡률이 거리에 따라 증가
    assert al.curvature_at(450.0) == pytest.approx(1 / 400, rel=0.05)                          # 첫 원곡선 R=400 좌회전
    assert truth.curvature_at(900.0) < 0 and al.curvature_at(900.0) < 0                         # 두 번째 곡선은 우회전
    assert al.curvature_at(900.0) == pytest.approx(truth.curvature_at(900.0), abs=2e-4)


def test_circle_radius_is_recovered():
    R = 100.0
    rows = [(R * math.sin(i / R), R - R * math.cos(i / R), 10.0 + 0.001 * i) for i in range(0, 301)]
    al = build(rows, start=0.0)
    for sta in (30.0, 150.0, 270.0):
        assert al.curvature_at(sta) == pytest.approx(1 / R, rel=1e-3)
        assert al.grade_at(sta) == pytest.approx(0.001, abs=1e-6)


# ===================================================== 입력 점검
@pytest.mark.parametrize("make,msg", [
    (lambda: SampledAlignment([0, 1], [0, 0], [0, 0]), "3점 이상"),
    (lambda: SampledAlignment([0, 1, 1.0000001], [0, 0, 0], [0, 0, 0]), "3점 이상"),
    (lambda: SampledAlignment([0, 1, 2], [0, 0], [0, 0, 0]), "개수가 다릅니다"),
    (lambda: SampledAlignment([0, 1, float("nan")], [0, 0, 0], [0, 0, 0]), "유한하지 않은"),
    (lambda: SampledAlignment([0, 1, 2], [0, 0, 0], [0, 0, 0], smooth_m=-1), "평활 구간"),
    (lambda: SampledAlignment([0, 1, 2, 2.2], [0, 0, 0, 1.0], [0, 0, 0, 0]), "3번째 점.*꺾입니다"),            # 직각 꺾임
    (lambda: SampledAlignment([0, 1, 2, 3], [0, 0, 0, 0], [0, 0, 0, 9.0]), "4번째 점 부근 구배.*9000‰"),
])
def test_input_checks(make, msg):
    import re
    with pytest.raises(ValueError) as e:
        make()
    assert re.search(msg, str(e.value)), str(e.value)


def test_duplicates_are_dropped_with_a_warning_and_sparse_spacing_warns():
    rows = sample_rows(dec=3)
    rows = rows[:50] + [rows[49]] * 3 + rows[50:]
    al = build(rows)
    assert al.point_count == 501 and any("중복 점 3개" in w for w in al.warnings)
    sparse = build(sample_rows(step=25.0, dec=None))
    assert any("최대 25.0m" in w for w in sparse.warnings)


def test_reversed_point_order_is_detected_or_gives_reversed_alignment():
    """점 순서가 뒤집혀도 그 방향으로 진행하는 선형으로 읽힘 (방향 판단은 사용자의 파일 순서를 따름)"""
    fwd = build(sample_rows(dec=3))
    rev = build(list(reversed(sample_rows(dec=3))))
    assert rev.point_at(rev.start_station) == pytest.approx(fwd.point_at(fwd.end_station), abs=2e-3)
    assert abs((rev.azimuth_at(rev.start_station) - fwd.azimuth_at(fwd.end_station)) % (2 * math.pi) - math.pi) < 2e-3


# ===================================================== 텍스트 파서
BASE = [(300 + i * 1.0, 10 + i * 0.5, 50 + i * 0.01) for i in range(40)]


def fmt(rows, sep=" ", dec=".", cols=None, prec=3):
    out = []
    for r in rows:
        vals = [f"{v:.{prec}f}".replace(".", dec) for v in (cols(r) if cols else r)]
        out.append(sep.join(vals))
    return "\n".join(out)


def raw(al):
    return list(zip(al.raw_x, al.raw_y, al.raw_z))


@pytest.mark.parametrize("text,order", [
    (fmt(BASE), "xyz"),
    (fmt(BASE, sep=","), "xyz"),
    (fmt(BASE, sep=", "), "xyz"),
    (fmt(BASE, sep="\t"), "xyz"),
    (fmt(BASE, sep=";", dec=","), "xyz"),                                       # 세미콜론 + 소수점 쉼표 (유럽/한국 엑셀)
    (fmt(BASE, sep="   ") + "\n\n   \n", "xyz"),                                # 공백 여러 개, 끝의 빈 줄
    ("# 주석\n// 주석2\n" + fmt(BASE), "xyz"),
    ("X,Y,Z\r\n" + fmt(BASE, sep=",").replace("\n", "\r\n"), "xyz"),            # CRLF + 머리글
    ("X Y Z\n" + fmt(BASE), "xyz"),
    ("Easting,Northing,Elevation\n" + fmt(BASE, sep=","), "xyz"),
    ("E N Z\n" + fmt(BASE), "xyz"),
    ("\ufeffX,Y,Z\n" + fmt(BASE, sep=","), "xyz"),                              # BOM
    (fmt(BASE, sep=",", prec=6).replace("300.000000,", "3.0e2,", 1), "xyz"),    # 과학 표기
])
def test_parser_formats(text, order):
    al = parse_xyz_text(text.lstrip("\ufeff"))
    assert al.order == order and al.point_count == 40
    assert raw(al)[0] == pytest.approx((300.0, 10.0, 50.0), abs=1e-6) and raw(al)[-1] == pytest.approx(BASE[-1], abs=1e-6)


def test_header_selects_order_and_northing_easting_is_swapped():
    swapped = fmt(BASE, sep=",", cols=lambda r: (r[1], r[0], r[2]))              # N, E, Z 순서로 저장된 파일
    al = parse_xyz_text("Northing, Easting, Elevation\n" + swapped)
    assert al.order == "yxz" and raw(al)[5] == pytest.approx(BASE[5], abs=1e-6)
    al2 = parse_xyz_text(swapped, XYZOptions(order="yxz"))                         # 머리글 없이 직접 지정
    assert raw(al2)[5] == pytest.approx(BASE[5], abs=1e-6)
    assert parse_xyz_text(swapped).order == "xyz" and any("Y X Z" in w for w in parse_xyz_text(swapped).warnings)   # 자동은 xyz + 안내


def test_explicit_order_overrides_header():
    al = parse_xyz_text("X,Y,Z\n" + fmt(BASE, sep=","), XYZOptions(order="yxz"))
    assert al.order == "yxz" and raw(al)[3] == pytest.approx((10 + 3 * 0.5, 300 + 3, 50.03), abs=1e-6)


def test_penzd_civil3d_with_description_column():
    lines = [f"{i + 1},{r[1]:.3f},{r[0]:.3f},{r[2]:.3f},CL{i}" for i, r in enumerate(BASE)]       # 점번호, N, E, Z, 설명
    al = parse_xyz_text("\n".join(lines), XYZOptions(order="-yxz"))
    assert al.point_count == 40 and raw(al)[7] == pytest.approx(BASE[7], abs=1e-6)
    hdr = parse_xyz_text("Point,Northing,Easting,Elevation,Description\n" + "\n".join(lines))
    assert hdr.order == "-yxz" and raw(hdr)[7] == pytest.approx(BASE[7], abs=1e-6)


def test_station_column_is_detected_and_sets_start_station():
    lines = [f"{2000 + i * math.hypot(1.0, 0.5):.3f} {r[0]:.3f} {r[1]:.3f} {r[2]:.3f}" for i, r in enumerate(BASE)]
    al = parse_xyz_text("\n".join(lines))
    assert al.order == "sxyz" and al.start_station == pytest.approx(2000.0) and al.warnings[0].startswith("열 순서를 측점")
    al2 = parse_xyz_text("\n".join(lines), XYZOptions(order="sxyz", start_station=5.0))
    assert al2.start_station == pytest.approx(2000.0)                              # 측점 열이 있으면 파일 값 우선
    sw = [f"{l.split()[0]} {l.split()[2]} {l.split()[1]} {l.split()[3]}" for l in lines]
    assert raw(parse_xyz_text("\n".join(sw), XYZOptions(order="syxz")))[9] == pytest.approx(BASE[9], abs=1e-6)
    hdr = parse_xyz_text("Station,X,Y,Z\n" + "\n".join(lines))
    assert hdr.order == "sxyz" and hdr.start_station == pytest.approx(2000.0)
    scaled = [f"{2000 + i * 1.5:.3f} {r[0]:.3f} {r[1]:.3f} {r[2]:.3f}" for i, r in enumerate(BASE)]
    assert any("측점 열의 간격" in w for w in parse_xyz_text("\n".join(scaled), XYZOptions(order="sxyz")).warnings)


def test_start_station_option_without_station_column():
    assert parse_xyz_text(fmt(BASE), XYZOptions(start_station=1500.0)).start_station == 1500.0


@pytest.mark.parametrize("text,opt,msg", [
    ("", None, "좌표 줄이 없습니다"),
    ("# 주석뿐\n", None, "좌표 줄이 없습니다"),
    ("X,Y,Z\n", None, "머리글만 있고"),
    (fmt(BASE, cols=lambda r: r[:2]), None, "표고\\(z\\) 열이 없습니다"),
    (fmt(BASE, cols=lambda r: (1, *r)), None, "첫 열이 측점으로 보이지 않습니다"),                     # 4열인데 측점이 아님
    (fmt(BASE, cols=lambda r: (1, *r, 1)), None, "열이 5개입니다.*-yxz"),
    ("A,B,C\n" + fmt(BASE, sep=","), None, "X, Y, Z 열을 찾지 못했습니다"),
    (fmt(BASE)[:-8] + "abc 1 2", None, "숫자로 읽을 수 없는 값"),
    (fmt(BASE).replace("\n", "\n", 5), XYZOptions(order="qzx"), "올바르지 않습니다"),
    (fmt(BASE), XYZOptions(order="xxz"), "같은 열이 두 번"),
    (fmt(BASE), XYZOptions(order="xy"), "z 가 없습니다"),
    (fmt(BASE), XYZOptions(order="sxyz"), "열이 3개입니다.*4개 이상"),
    ("1 2 3\n4 5\n6 7 8", None, "2번째 줄: 열이 2개"),
])
def test_parser_errors_are_specific(text, opt, msg):
    import re
    with pytest.raises(ValueError) as e:
        parse_xyz_text(text, opt, name="a.txt")
    assert re.search(msg, str(e.value)), str(e.value)


def test_error_reports_line_number_and_file(tmp_path):
    body = fmt(BASE).splitlines(); body[17] = "301.5 oops 50"
    f = tmp_path / "bad.txt"; f.write_text("# 헤더 주석\n" + "\n".join(body), encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.txt: 19번째 줄: 숫자로 읽을 수 없는 값이 있습니다"):
        load_alignment(f)


def test_station_column_must_increase():
    lines = [f"{i * 1.0:.3f} {r[0]:.3f} {r[1]:.3f} {r[2]:.3f}" for i, r in enumerate(BASE)]
    lines[10], lines[11] = lines[11], lines[10]
    with pytest.raises(ValueError, match="측점 열이 증가하지 않습니다"):
        parse_xyz_text("\n".join(lines), XYZOptions(order="sxyz"))


def test_encodings_utf8_bom_and_cp949(tmp_path):
    body = "# 한글 주석: 서울 정거장 선형\nX,Y,Z\n" + fmt(BASE, sep=",")
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        f = tmp_path / f"{enc}.txt"; f.write_bytes(body.encode(enc))
        assert load_alignment(f).point_count == 40, enc
    assert preview_lines(tmp_path / "cp949.txt")[0].startswith("# 한글")
    bad = tmp_path / "bin.txt"; bad.write_bytes(b"\xff\xfe\x00\x81\x81\x81")
    with pytest.raises(ValueError, match="인코딩"):
        load_alignment(bad)


# ===================================================== 파일 / JSON 연계
def test_sample_file_loads_and_matches_truth():
    al = load_alignment(SAMPLE_TXT, XYZOptions(start_station=300.0))
    assert isinstance(al, SampledAlignment) and al.point_count == 501 and al.order == "xyz"
    assert errors(al)["pos"] < 1e-3
    assert "좌표 목록 501점" in describe(al)


def test_json_points_type_resolves_relative_file(tmp_path):
    (tmp_path / "cl.txt").write_text("Northing Easting Elevation\n" + fmt(BASE, cols=lambda r: (r[1], r[0], r[2])), encoding="utf-8")
    j = tmp_path / "a.json"
    j.write_text('{"type": "points", "file": "cl.txt", "order": "auto", "start_station": 7000, "smooth_m": 3}', encoding="utf-8")
    al = load_alignment(j)
    assert al.start_station == 7000 and al.smooth_m == 3 and al.order == "yxz" and raw(al)[0] == pytest.approx(BASE[0], abs=1e-6)
    with pytest.raises(ValueError, match="points: 필요한 항목이 없습니다 → file"):
        alignment_from_dict({"type": "points"})
    (tmp_path / "b.json").write_text('{"type": "points", "file": "missing.txt"}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"b\.json: .*missing\.txt: 파일을 열 수 없습니다"):
        load_alignment(tmp_path / "b.json")


# ===================================================== 전체 모델
def sampled_cfg(rows=None, **kw):
    cfg = curved_cfg()
    cfg.align = build(rows or sample_rows(dec=3), **kw)
    return cfg


def test_model_on_sampled_alignment_matches_analytic_model():
    ref, got = StationCADEngine(curved_cfg()), StationCADEngine(sampled_cfg())
    for a, b in zip(members(ref), members(got)):
        assert a.name == b.name
        assert b.shape.volume == pytest.approx(a.shape.volume, rel=1e-3), a.name
    cols_ref = {c.name: c for pk in ref.columns.column_packages for c in pk.columns}
    for pk in got.columns.column_packages:
        for c in pk.columns:
            r = cols_ref[c.name]
            assert got.cfg.to_world(c.pos_x, c.pos_y) == pytest.approx(ref.cfg.to_world(r.pos_x, r.pos_y), abs=3e-3)
            assert got.cfg.theta_at(c.pos_x) == pytest.approx(ref.cfg.theta_at(r.pos_x), abs=8e-4)
            assert c.pos_z == pytest.approx(r.pos_z, abs=2e-3)


def test_sampled_model_mesh_matches_formula_and_has_no_interference():
    eng = StationCADEngine(sampled_cfg())
    for m in members(eng):
        assert PM.mesh_volume(PM.sweep_quads(PM.rings(eng.cfg, m))) == pytest.approx(m.shape.volume, rel=1e-3), m.name
    assert interference_pairs(eng) == []


def test_sampled_alignment_builds_all_outputs(tmp_path):
    cfg = sampled_cfg()
    paths = BIMEngine.build(cfg, tmp_path)
    assert len(paths) == 5 and all(os.path.exists(p) for p in paths)
    plan = ezdxf.readfile(next(p for p in paths if "평면도" in p))
    assert any("[WCS]" in t.dxf.text for t in plan.modelspace().query("TEXT"))
    f = ifcopenshell.open(paths[-1])
    assert {e.Representation.Representations[0].RepresentationType for e in f.by_type("IfcWall")} == {"Tessellation"}
    assert len(f.by_type("IfcColumn")) == 85


def test_station_outside_sampled_alignment_is_reported():
    cfg = sampled_cfg(); cfg.station.start_station = 700.0           # 정거장 끝 900 > 좌표 끝(800)
    with pytest.raises(ValueError, match="선형 범위"):
        cfg.validate()
    cfg.station.start_station = 330.0; cfg.validate()


def test_cm_noisy_alignment_still_builds_a_clean_model():
    cfg = curved_cfg(columns=NO_COLS()); cfg.align = build(sample_rows(dec=2, noise=0.002), smooth_m=10.0)
    eng = StationCADEngine(cfg)
    for m in members(eng):
        assert PM.mesh_volume(PM.sweep_quads(PM.rings(cfg, m))) == pytest.approx(m.shape.volume, rel=3e-3), m.name


# ===================================================== 성능
def test_large_file_is_fast_enough(tmp_path):
    R, n = 2000.0, 20000                                               # 20 km, 1m 간격
    rows = [(R * math.sin(i / R), R - R * math.cos(i / R), 10.0 + 0.002 * i) for i in range(n)]
    f = tmp_path / "big.txt"; f.write_text("X,Y,Z\n" + "\n".join(f"{x:.3f},{y:.3f},{z:.3f}" for x, y, z in rows), encoding="utf-8")
    t0 = time.perf_counter()
    al = load_alignment(f)
    load_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    for i in range(10000):
        al.point_at(1000.0 + i * 1.7); al.azimuth_at(1000.0 + i * 1.7)
    query_s = time.perf_counter() - t0
    assert al.point_count == n and load_s < 10.0 and query_s < 3.0, (load_s, query_s)
