"""LandXML 선형 읽기 테스트"""
import math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import ifcopenshell
import pytest

from config.alignment_io import alignment_from_dict, describe, file_kind, load_alignment
from config.alignment_landxml import LandXMLOptions, load_landxml_alignment, scan_landxml
from config.alignment_text import XYZOptions
from config.curved_alignment import CurvedAlignment, HElement, HorizontalAlignment, VerticalProfile
from engine.bim_engine import BIMEngine
from engine.cad_engine import StationCADEngine
from landxml_maker import make_landxml
from test_curved import ROOT, curved_cfg, members, s_curve
from test_patch import make_cfg

truth = s_curve()
SAMPLE = os.path.join(ROOT, "samples", "alignment_landxml_example.xml")


def write(tmp_path, text, name="a.xml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def same(a, t, tol=1e-4, stations=range(5, 995, 13), ang=1e-6):
    """ang: 방향·곡률·구배 허용 오차. 파일에 쓰인 값의 자릿수(km 단위는 1mm)에 맞춰 조절"""
    for s in stations:
        assert a.point_at(s) == pytest.approx(t.point_at(s), abs=tol), s
        assert a.azimuth_at(s) == pytest.approx(t.azimuth_at(s), abs=ang), s
        assert a.curvature_at(s) == pytest.approx(t.curvature_at(s), abs=ang), s
        assert a.elevation_at(s) == pytest.approx(t.elevation_at(s), abs=tol), s
        assert a.grade_at(s) == pytest.approx(t.grade_at(s), abs=ang), s


def small_alignment(elements, theta0=0.5, start=5000.0, x0=120.0, y0=-40.0):
    return CurvedAlignment(HorizontalAlignment(start, x0, y0, theta0, elements),
                           VerticalProfile([(start, 10, 0), (start + 200, 12, 80), (start + 400, 11, 0)]))


# ===================================================== 정상 읽기
def test_roundtrip_matches_original_alignment(tmp_path):
    a = load_landxml_alignment(write(tmp_path, make_landxml(truth)))
    assert isinstance(a, CurvedAlignment) and a.warnings == [] and not a.is_straight
    assert (a.alignment_name, a.profile_name) == ("CL", "Design / FG")
    assert a.start_station == 0 and a.end_station == pytest.approx(1000.0)        # 평면 ~1626, 종단 1000 의 교집합
    same(a, truth)
    a.validate()


def test_sample_file_and_description():
    a = load_alignment(SAMPLE)
    same(a, truth)
    assert "LandXML 선형 'Subway-Main'" in describe(a) and file_kind(SAMPLE) == "landxml"
    assert file_kind("x.LANDXML") == "landxml" and file_kind("x.json") == "json" and file_kind("x.txt") == "text"


def test_namespace_is_optional_and_unrelated_elements_are_ignored(tmp_path):
    xml = make_landxml(truth, ns=False, extra_root='<CgPoints><CgPoint name="1">1 2 3</CgPoint></CgPoints><Surfaces/>',
                       extra_align="<Feature code='x'/>", ground=True)
    same(load_landxml_alignment(write(tmp_path, xml)), truth)


@pytest.mark.parametrize("unit,f", [("foot", 0.3048), ("USSurveyFoot", 1200 / 3937), ("millimeter", 0.001),
                                    ("centimeter", 0.01), ("kilometer", 1000.0), ("inch", 0.0254)])
def test_unit_conversion(tmp_path, unit, f):
    a = load_landxml_alignment(write(tmp_path, make_landxml(truth, unit=unit, f=f)))
    if unit == "kilometer":                         # 소수 6자리 = 1mm 정밀도의 파일
        same(a, truth, tol=2e-3, ang=2e-5)
    else:
        same(a, truth)
    assert any("환산" in w for w in a.warnings)


def test_missing_units_assumes_meters_with_warning(tmp_path):
    a = load_landxml_alignment(write(tmp_path, make_landxml(truth, units=False)))
    same(a, truth)
    assert any("<Units> 정보가 없어" in w for w in a.warnings)


def test_station_start_offset_is_honored(tmp_path):
    shifted = CurvedAlignment(HorizontalAlignment(2000.0, *truth.horizontal.point_at(0), 0.0, truth.horizontal.elements),
                              VerticalProfile([(2000 + s, z, v) for s, z, v in zip(truth.vertical.sta, truth.vertical.z, truth.vertical.vc)]))
    a = load_landxml_alignment(write(tmp_path, make_landxml(shifted)))
    assert a.start_station == 2000.0 and a.end_station == pytest.approx(3000.0)
    assert a.point_at(2400.0) == pytest.approx(truth.point_at(400.0), abs=1e-4)


# ===================================================== 좌표 순서
def test_axis_auto_detects_east_north_files(tmp_path):
    p = write(tmp_path, make_landxml(truth, axis="EN"))
    a = load_landxml_alignment(p)
    same(a, truth)
    assert any("'동 북' 순서로 해석" in w for w in a.warnings)
    same(load_landxml_alignment(p, LandXMLOptions(axis="EN")), truth)           # 직접 지정하면 경고 없음
    assert load_landxml_alignment(p, LandXMLOptions(axis="EN")).warnings == []


def test_explicit_wrong_axis_is_rejected_with_numbers(tmp_path):
    with pytest.raises(ValueError, match=r"요소 끝점이 파일의 좌표와 크게 어긋납니다 \(NE: 끝점 어긋남"):
        load_landxml_alignment(write(tmp_path, make_landxml(truth, axis="EN")), LandXMLOptions(axis="NE"))
    with pytest.raises(ValueError, match="axis 는 auto / NE / EN"):
        load_landxml_alignment(SAMPLE, LandXMLOptions(axis="XY"))


# ===================================================== 첫 요소 종류별 시작 방향
@pytest.mark.parametrize("elements,theta0", [
    ([HElement(120.0), HElement(80.0, 0, 1 / 300), HElement(150.0, 1 / 300, 1 / 300), HElement(80.0, 1 / 300, 0)], 0.5),   # 직선 시작
    ([HElement(150.0, 1 / 300, 1 / 300), HElement(60.0, 1 / 300, 0), HElement(100.0)], 0.5),                               # 좌회전 원곡선 시작
    ([HElement(150.0, -1 / 300, -1 / 300), HElement(60.0, -1 / 300, 0), HElement(100.0)], -2.2),                           # 우회전 원곡선 시작
    ([HElement(80.0, 0, 1 / 250), HElement(120.0, 1 / 250, 1 / 250), HElement(80.0, 1 / 250, 0)], 1.0),                     # 진입 완화곡선 시작
    ([HElement(80.0, 0, -1 / 250), HElement(120.0, -1 / 250, -1 / 250)], 3.0),                                              # 우회전 진입 완화곡선
    ([HElement(80.0, 1 / 250, 0), HElement(100.0)], 1.0),                                                                    # 진출 완화곡선 시작
])
def test_first_element_kinds(tmp_path, elements, theta0):
    t = small_alignment(elements, theta0)
    a = load_landxml_alignment(write(tmp_path, make_landxml(t)))
    same(a, t, stations=[5000 + i * 7.0 for i in range(0, 40)])
    assert a.warnings == []


def test_compound_spiral_first_cannot_give_start_direction(tmp_path):
    t = small_alignment([HElement(80.0, 1 / 400, 1 / 200), HElement(100.0, 1 / 200, 1 / 200)])
    with pytest.raises(ValueError, match="양 끝 곡률이 모두 있는 완화곡선"):
        load_landxml_alignment(write(tmp_path, make_landxml(t)))


# ===================================================== 선형 / 종단 선택
def two_alignments(tmp_path):
    other = small_alignment([HElement(300.0)], theta0=0.1, start=100.0)
    xml = make_landxml(truth, name="Main", extra_align="")
    second = make_landxml(other, name="Branch", profile_name="Alt", prof_name="Opt").split('<Alignments name="Alignments">')[1].split("</Alignments>")[0]
    xml = xml.replace("</Alignments>", second + "</Alignments>")
    # Main 에 두 번째 종단 추가
    alt = '<Profile name="Alt"><ProfAlign name="Opt"><PVI>0 100</PVI><PVI>1000 120</PVI></ProfAlign></Profile>'
    xml = xml.replace("</Alignment>", alt + "</Alignment>", 1)
    return write(tmp_path, xml)


def test_multiple_alignments_and_profiles(tmp_path):
    p = two_alignments(tmp_path)
    infos = scan_landxml(p)
    assert [(i.name, i.profiles) for i in infos] == [("Main", ["Design / FG", "Alt / Opt"]), ("Branch", ["Alt / Opt"])]
    default = load_landxml_alignment(p)
    assert default.alignment_name == "Main" and default.profile_name == "Design / FG"
    assert any("선형이 2개" in w for w in default.warnings) and any("종단이 2개" in w for w in default.warnings)
    alt = load_landxml_alignment(p, LandXMLOptions(alignment="Main", profile="Opt"))              # ProfAlign 이름만으로도 선택
    assert alt.profile_name == "Alt / Opt" and alt.elevation_at(500) == pytest.approx(110.0)
    assert load_landxml_alignment(p, LandXMLOptions(alignment="Main", profile="Alt / Opt")).elevation_at(1000) == pytest.approx(120.0)
    branch = load_landxml_alignment(p, LandXMLOptions(alignment="Branch"))
    assert branch.alignment_name == "Branch" and branch.start_station == 100.0
    with pytest.raises(ValueError, match="선형 'Nope' 이\\(가\\) 없습니다. 파일 안의 선형: Main, Branch"):
        load_landxml_alignment(p, LandXMLOptions(alignment="Nope"))
    with pytest.raises(ValueError, match="종단 'X' 이\\(가\\) 없습니다.*Design / FG, Alt / Opt"):
        load_landxml_alignment(p, LandXMLOptions(alignment="Main", profile="X"))


# ===================================================== 지원하지 않는 요소 / 입력 오류
def test_unsupported_content_is_reported(tmp_path):
    base = make_landxml(truth)
    cases = [
        (base.replace("</Alignment>", '<StaEquation staAhead="100" staBack="90" staInternal="90"/></Alignment>'), "측점 방정식"),
        (base.replace("<PVI>1000.000000", '<UnsymParaCurve lengthIn="40" lengthOut="60">450 104</UnsymParaCurve><PVI>1000.000000'), "비대칭 포물선 종곡선"),
        (base.replace("<Line ", '<IrregularLine><PntList2D>0 0 1 1</PntList2D></IrregularLine><Line ', 1), "평면 1번째 요소 <IrregularLine>: 지원하지 않는 요소"),
        (re.sub(r"<CoordGeom>.*?</CoordGeom>", "", base, flags=re.S), "평면 기하\\(CoordGeom\\)가 없습니다"),
        (re.sub(r"<Profile .*?</Profile>", "", base, flags=re.S), "종단\\(Profile\\)이 없습니다"),
        (re.sub(r"<Alignments.*</Alignments>", "", base, flags=re.S), "선형\\(Alignment\\)이 없습니다"),
        (base.replace('linearUnit="meter"', 'linearUnit="furlong"'), "지원하지 않는 길이 단위입니다 → furlong"),
        (base.replace("<ParaCurve length=", "<ParaCurve foo=", 1), "ParaCurve> 에 length 가 없습니다"),
        (base.replace("<PVI>0.000000 100.000000</PVI>", "<PVI>0.000000</PVI>"), "측점과 표고가 필요합니다"),
        (re.sub(r'(<Curve [^>]*?) radius="[^"]*"', r"\1", base, count=1), "평면 3번째 요소 <Curve>: radius 가 없습니다"),
    ]
    for i, (xml, msg) in enumerate(cases):
        with pytest.raises(ValueError, match=msg):
            load_landxml_alignment(write(tmp_path, xml, f"c{i}.xml"))


def test_file_level_errors(tmp_path):
    with pytest.raises(ValueError, match=r"bad\.xml: XML 형식 오류 \(줄 2, 열"):
        load_landxml_alignment(write(tmp_path, '<LandXML>\n<Alignments></LandXML>', "bad.xml"))
    with pytest.raises(ValueError, match="LandXML 파일이 아닙니다 \\(최상위 요소가 svg\\)"):
        load_landxml_alignment(write(tmp_path, "<svg/>", "n.xml"))
    with pytest.raises(ValueError, match="엔티티 선언"):
        load_landxml_alignment(write(tmp_path, '<!DOCTYPE x [<!ENTITY a "aaaa">]><LandXML>&a;</LandXML>', "e.xml"))
    with pytest.raises(ValueError, match="파일을 열 수 없습니다"):
        load_landxml_alignment(tmp_path / "missing.xml")
    p = write(tmp_path, make_landxml(truth).replace("0.000000 304.164900</End>", "abc def</End>", 1), "num.xml")
    with pytest.raises(ValueError, match="숫자로 읽을 수 없는 값"):
        load_landxml_alignment(p)


# ===================================================== 좌표 대조
def perturb_first_curve_end(xml, dn):
    return re.sub(r"(<Curve[^>]*>.*?<End>)([-\d.]+)( [-\d.]+</End>)",
                  lambda m: f"{m.group(1)}{float(m.group(2)) + dn:.6f}{m.group(3)}", xml, count=1, flags=re.S)


def test_closure_warning_and_rejection(tmp_path):
    a = load_landxml_alignment(write(tmp_path, perturb_first_curve_end(make_landxml(truth), 0.05)))
    assert any("요소 3 의 끝점이 파일 좌표와 5.0cm 다릅니다" in w for w in a.warnings)
    with pytest.raises(ValueError, match="요소 끝점이 파일의 좌표와 크게 어긋납니다"):
        load_landxml_alignment(write(tmp_path, perturb_first_curve_end(make_landxml(truth), 3.0), "far.xml"))


def test_unsupported_spiral_type_is_matched_to_theta_with_warning(tmp_path):
    """bloss 등 지원하지 않는 종류: 파일의 theta(끝 접선각)에 맞춘 클로소이드로 근사해 방향 오차가 누적되지 않게 함"""
    a = load_landxml_alignment(write(tmp_path, make_landxml(truth, spi_type="bloss")))
    assert sum("bloss" in w and "theta" in w for w in a.warnings) == 1            # 같은 종류는 한 번만 경고
    same(a, truth)                                                                  # truth 의 theta = L/2R 이라 그대로 일치


def test_unsupported_spiral_type_without_theta_warns_about_drift(tmp_path):
    a = load_landxml_alignment(write(tmp_path, make_landxml(truth, spi_type="sinusoid", spiral_extras=False)))
    assert any("sinusoid" in w and "누적" in w for w in a.warnings)
    same(a, truth)


def test_circular_vertical_curve_is_approximated_with_warning(tmp_path):
    a = load_landxml_alignment(write(tmp_path, make_landxml(truth).replace("<ParaCurve", "<CircCurve radius=\"9000\"").replace("</ParaCurve>", "</CircCurve>")))
    assert any("CircCurve" in w for w in a.warnings)
    same(a, truth)


# ===================================================== 다른 입구: JSON / 확장자 / 옵션 전달
def test_json_landxml_type_and_dispatch(tmp_path):
    (tmp_path / "road.xml").write_text(make_landxml(truth, name="R1"), encoding="utf-8")
    j = tmp_path / "a.json"
    j.write_text('{"type": "landxml", "file": "road.xml", "alignment": "R1", "axis": "NE"}', encoding="utf-8")
    assert load_alignment(j).alignment_name == "R1"
    with pytest.raises(ValueError, match="landxml: 필요한 항목이 없습니다 → file"):
        alignment_from_dict({"type": "landxml"})
    (tmp_path / "b.json").write_text('{"type": "landxml", "file": "road.xml", "alignment": "Zzz"}', encoding="utf-8")
    with pytest.raises(ValueError, match="선형 'Zzz' 이\\(가\\) 없습니다"):
        load_alignment(tmp_path / "b.json")
    # 확장자로 분기: .landxml, 대소문자 무시, 옵션 형식이 달라도 무시
    (tmp_path / "x.LANDXML").write_text(make_landxml(truth), encoding="utf-8")
    assert load_alignment(tmp_path / "x.LANDXML", XYZOptions(order="yxz")).alignment_name == "CL"
    assert load_alignment(tmp_path / "x.LANDXML", LandXMLOptions(profile="FG")).profile_name == "Design / FG"


# ===================================================== 전체 모델
def test_model_built_from_landxml_equals_model_from_original(tmp_path):
    a = load_landxml_alignment(write(tmp_path, make_landxml(truth)))
    ref = StationCADEngine(curved_cfg())
    cfg = curved_cfg(); cfg.align = a
    got = StationCADEngine(cfg)
    for m1, m2 in zip(members(ref), members(got)):
        assert m2.shape.volume == pytest.approx(m1.shape.volume, rel=1e-6), m1.name
    paths = BIMEngine.build(cfg, tmp_path / "out")
    assert len(paths) == 5 and all(os.path.exists(p) for p in paths)
    assert any("[WCS]" in t.dxf.text for t in ezdxf.readfile(next(p for p in paths if "평면도" in p)).modelspace().query("TEXT"))
    assert len(ifcopenshell.open(paths[-1]).by_type("IfcColumn")) == 85


def test_station_outside_landxml_alignment_is_reported(tmp_path):
    cfg = make_cfg(); cfg.align = load_landxml_alignment(write(tmp_path, make_landxml(truth)))
    cfg.station.start_station = 900.0
    with pytest.raises(ValueError, match="선형 범위"):
        cfg.validate()


# ===================================================== 3차 포물선 완화곡선 (Civil 3D japaneseCubic)
import xml.etree.ElementTree as ET

from config.curved_alignment import CubicSpiral

REAL = os.path.join(ROOT, "samples", "civil3d_korea_cubic_spiral.xml")      # 실제 Civil 3D 2026 내보내기 (한국 중부원점, 21km, 3차 포물선 20개)


def cubic_alignment():
    els = [HElement(300.0), CubicSpiral(160.0, radius=650.0), HElement(220.0, 1 / 650, 1 / 650), CubicSpiral(160.0, radius=650.0, exit=True),
           HElement(180.0), CubicSpiral(140.0, radius=500.0, sign=-1.0), HElement(120.0, -1 / 500, -1 / 500),
           CubicSpiral(140.0, radius=500.0, sign=-1.0, exit=True), HElement(200.0)]
    return CurvedAlignment(HorizontalAlignment(0.0, 1000.0, 2000.0, 0.4, els), VerticalProfile([(0, 50, 0), (900, 55, 100), (1620, 52, 0)]))


def test_cubic_spirals_roundtrip_through_landxml(tmp_path):
    t = cubic_alignment()
    xml = make_landxml(t)
    assert xml.count('spiType="japaneseCubic"') == 4 and "totalX=" in xml
    a = load_landxml_alignment(write(tmp_path, xml))
    assert a.warnings == [] and sum(isinstance(e, CubicSpiral) for e in a.horizontal.elements) == 4
    same(a, t, stations=range(5, 1615, 11))


def test_cubic_without_total_x_or_with_a_wrong_one_falls_back_to_arc_length(tmp_path):
    t = cubic_alignment()
    xml = make_landxml(t)
    no_x = re.sub(r' totalX="[^"]*"', "", xml)
    same(load_landxml_alignment(write(tmp_path, no_x, "n.xml")), t, stations=range(5, 1615, 11))
    wrong = re.sub(r'totalX="([\d.]+)"', lambda m: f'totalX="{float(m.group(1)) * 1.05:.6f}"', xml)     # 5% 어긋난 값은 무시
    same(load_landxml_alignment(write(tmp_path, wrong, "w.xml")), t, stations=range(5, 1615, 11))


def test_treating_cubic_as_clothoid_would_drift():
    """왜 3차 포물선을 정확히 다뤄야 하는지: 같은 R·L 의 클로소이드와는 끝 접선각이 0.06° 다르고, 이 차이가 직선 위에서 누적된다"""
    cubic = HorizontalAlignment(0, 0, 0, 0.0, [CubicSpiral(162.3, radius=600.0), HElement(2000.0, 1 / 600, 1 / 600)])
    clothoid = HorizontalAlignment(0, 0, 0, 0.0, [HElement(162.3, 0.0, 1 / 600), HElement(2000.0, 1 / 600, 1 / 600)])
    d = math.hypot(*(a - b for a, b in zip(cubic.point_at(1500.0), clothoid.point_at(1500.0))))
    assert d > 1.0                                                                       # 1.5km 지점에서 1m 이상 어긋남


# ---- 실제 Civil 3D 파일 ----
def file_geometry(path):
    """로더와 무관하게 XML 을 직접 읽어 (종류, 호 길이, 끝점 (x=동, y=북), theta(°) 또는 None, rot) 목록을 만든다"""
    root = ET.parse(path).getroot()
    ns = {"l": "http://www.landxml.org/schema/LandXML-1.2"}
    out = []
    for el in root.find(".//l:CoordGeom", ns):
        n, e = (float(v) for v in el.find("l:End", ns).text.split())             # LandXML: 북 동
        out.append((el.tag.split("}")[1], float(el.get("length")), (e, n), el.get("theta"), el.get("rot"), el.get("spiType")))
    return out, float(root.find(".//l:Alignment", ns).get("staStart").rstrip("."))


def test_real_civil3d_file_matches_every_element_end_point():
    a = load_landxml_alignment(REAL)
    assert a.warnings == [] and (a.alignment_name, a.start_station) == ("초안1구간", 0.0)
    elements, sta0 = file_geometry(REAL)
    assert len(elements) == 47 and sum(k == "Spiral" for k, *_ in elements) == 20
    assert {e[5] for e in elements if e[0] == "Spiral"} == {"japaneseCubic"}
    sta, worst = sta0, 0.0
    for kind, length, end, theta, rot, _ in elements:
        start_sta, sta = sta, sta + length
        worst = max(worst, math.hypot(*(u - v for u, v in zip(a.point_at(sta), end))))      # 21km 에 걸친 모든 요소 끝점
        if kind == "Spiral":                                                                 # 완화곡선의 방향 변화 = 파일의 theta
            turn = a.azimuth_at(sta) - a.azimuth_at(start_sta)
            assert math.degrees(turn) == pytest.approx(float(theta) * (1 if rot == "ccw" else -1), abs=1e-6)
    assert worst < 1e-4                                                                      # 0.1mm 이내
    assert a.end_station == pytest.approx(21120.0716, abs=1e-3)


def test_real_civil3d_profile_matches_the_file():
    a = load_landxml_alignment(REAL)
    assert (a.elevation_at(0.0), a.elevation_at(a.end_station)) == pytest.approx((88.441635207087, 81.533668142783), abs=1e-6)
    vp = a.vertical
    assert len(vp.sta) == 19 and sum(v > 0 for v in vp.vc) == 17
    i = vp.sta.index(400.0)                                                                  # 종곡선(길이 35) 중앙 오프셋 = Δg·L/8
    assert a.elevation_at(400.0) == pytest.approx(89.641635207087 + (vp.g[i] - vp.g[i - 1]) * 35.0 / 8.0, abs=1e-6)
    for sta in (400 - 17.5, 400 + 17.5, 1040 - 32.5, 5560 + 33.6):                           # 종곡선 시작/끝에서 표고·구배 연속
        assert a.elevation_at(sta - 1e-6) == pytest.approx(a.elevation_at(sta + 1e-6), abs=1e-5)
        assert a.grade_at(sta - 1e-6) == pytest.approx(a.grade_at(sta + 1e-6), abs=1e-7)


@pytest.mark.parametrize("start", [1500.0, 1780.0, 990.0])
def test_real_civil3d_alignment_builds_models(tmp_path, start):
    """직선→완화곡선→원곡선, 원곡선→진출 완화곡선, 직선+종곡선 구간에 정거장을 놓아 모델 생성"""
    cfg = curved_cfg(); cfg.align = load_landxml_alignment(REAL); cfg.station.start_station = start
    eng = StationCADEngine(cfg)
    for m in members(eng):
        assert PM_mesh(eng.cfg, m) == pytest.approx(m.shape.volume, rel=1e-3), m.name
    from test_curved import interference_pairs
    assert interference_pairs(eng) == []
    paths = BIMEngine.build(cfg, tmp_path)
    assert len(paths) == 5 and all(os.path.exists(p) for p in paths)


def PM_mesh(cfg, m):
    from helper import prism_member as PM
    return PM.mesh_volume(PM.sweep_quads(PM.rings(cfg, m)))


def test_real_civil3d_file_scan_and_description():
    infos = scan_landxml(REAL)
    assert len(infos) == 1 and infos[0].name == "초안1구간" and infos[0].length == pytest.approx(21120.0716, abs=1e-3)
    assert infos[0].profiles == ["초안1구간 / 1구간 (1) (1)"]
    assert "LandXML 선형 '초안1구간'" in describe(load_alignment(REAL))
