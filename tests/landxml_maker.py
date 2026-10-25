"""테스트/샘플용 LandXML 생성기: CurvedAlignment → LandXML 1.2 텍스트 (읽기 결과를 원래 선형과 비교하기 위함)"""
import math

from config.curved_alignment import CubicSpiral, CurvedAlignment

NS = ' xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2"'


def _pt(x, y, axis, f, tag):
    a, b = (y, x) if axis == "NE" else (x, y)                 # LandXML 표준은 "북 동"
    return f"<{tag}>{a / f:.6f} {b / f:.6f}</{tag}>"


def _tangent_intersection(p0, th0, p1, th1):
    d0, d1 = (math.cos(th0), math.sin(th0)), (math.cos(th1), math.sin(th1))
    cross = d0[0] * d1[1] - d0[1] * d1[0]
    if abs(cross) < 1e-12:
        return ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    a = ((p1[0] - p0[0]) * d1[1] - (p1[1] - p0[1]) * d1[0]) / cross
    return (p0[0] + a * d0[0], p0[1] + a * d0[1])


def coord_geom(ha, axis="NE", f=1.0, spi_type="clothoid", sta_offset=0.0, spiral_extras=True):
    out = []
    for e, st in zip(ha.elements, ha._starts):
        en = st + e.length
        p0, p1 = ha.point_at(st), ha.point_at(en)
        th0, th1 = ha.azimuth_at(st), ha.azimuth_at(en)
        sta = f'staStart="{(st + sta_offset) / f:.6f}"'
        length = f'length="{e.length / f:.6f}"'
        if e.k0 == 0 and e.k1 == 0:
            out.append(f'<Line {length} {sta}>{_pt(*p0, axis, f, "Start")}{_pt(*p1, axis, f, "End")}</Line>')
        elif e.k0 == e.k1:
            r = 1 / abs(e.k0)
            rot = "ccw" if e.k0 > 0 else "cw"
            c = (p0[0] - math.sin(th0) / e.k0, p0[1] + math.cos(th0) / e.k0)
            pi_ = _tangent_intersection(p0, th0, p1, th1)
            out.append(f'<Curve rot="{rot}" crvType="arc" radius="{r / f:.6f}" {length} {sta}>{_pt(*p0, axis, f, "Start")}'
                       f'{_pt(*c, axis, f, "Center")}{_pt(*p1, axis, f, "End")}{_pt(*pi_, axis, f, "PI")}</Curve>')
        else:
            sign = e.k0 if e.k0 != 0 else e.k1
            rot = "ccw" if sign > 0 else "cw"
            if isinstance(e, CubicSpiral):                     # Civil 3D 의 japaneseCubic 처럼 totalX/totalY/theta 를 함께 기록
                R, X = e.radius, e.x_length
                rs, re_ = ("INF", f"{R / f:.6f}") if not e.exit else (f"{R / f:.6f}", "INF")
                kind_attr = f'spiType="japaneseCubic" theta="{math.degrees(math.atan(X / (2 * R))):.12f}" totalX="{X / f:.12f}" totalY="{X * X / (6 * R) / f:.12f}"'
            else:
                rs = "INF" if e.k0 == 0 else f"{1 / abs(e.k0) / f:.6f}"
                re_ = "INF" if e.k1 == 0 else f"{1 / abs(e.k1) / f:.6f}"
                theta = math.degrees((e.k0 + e.k1) / 2 * e.length)
                kind_attr = f'spiType="{spi_type}"' + (f' theta="{abs(theta):.12f}"' if spiral_extras else "")
            pi_ = _tangent_intersection(p0, th0, p1, th1)
            out.append(f'<Spiral rot="{rot}" {kind_attr} radiusStart="{rs}" radiusEnd="{re_}" {length} {sta}>'
                       f'{_pt(*p0, axis, f, "Start")}{_pt(*pi_, axis, f, "PI")}{_pt(*p1, axis, f, "End")}</Spiral>')
    return "\n        ".join(out)


def prof_align(vp, f=1.0, name="FG", extra=""):
    rows = []
    for sta, z, vc in zip(vp.sta, vp.z, vp.vc):
        rows.append(f'<ParaCurve length="{vc / f:.6f}">{sta / f:.6f} {z / f:.6f}</ParaCurve>' if vc > 0
                    else f"<PVI>{sta / f:.6f} {z / f:.6f}</PVI>")
    return f'<ProfAlign name="{name}">\n          ' + "\n          ".join(rows) + f"{extra}\n        </ProfAlign>"


def make_landxml(truth: CurvedAlignment, *, ns=True, axis="NE", unit="meter", f=1.0, name="CL", sta_offset=0.0,
                 profile_name="Design", prof_name="FG", spi_type="clothoid", extra_align="", prof_extra="",
                 extra_root="", units=True, ground=True, spiral_extras=True) -> str:
    unit_el = f'<Units><{"Imperial" if f > 0.29 and f < 0.31 or abs(f - 1200 / 3937) < 1e-9 else "Metric"} linearUnit="{unit}" angularUnit="decimal degrees" /></Units>' if units else ""
    ground_el = ('<ProfSurf name="EG" surfName="Existing"><PntList2D>0 99 1000 99</PntList2D></ProfSurf>' if ground else "")
    ha, vp = truth.horizontal, truth.vertical
    total = ha.end_station - ha.start_station
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<LandXML{NS if ns else ""}>
  {unit_el}
  <Project name="test" />
  <Application name="TestExporter" />
  {extra_root}
  <Alignments name="Alignments">
    <Alignment name="{name}" length="{total / f:.6f}" staStart="{(ha.start_station + sta_offset) / f:.6f}" state="proposed">
      <CoordGeom>
        {coord_geom(ha, axis, f, spi_type, sta_offset, spiral_extras)}
      </CoordGeom>
      <Profile name="{profile_name}">
        {ground_el}
        {prof_align(vp, f, prof_name, prof_extra)}
      </Profile>
      {extra_align}
    </Alignment>
  </Alignments>
</LandXML>
'''
