"""LandXML(.xml / .landxml) 선형 읽기. Civil 3D, Bentley(OpenRoads/MX), 기타 도로·철도 설계 프로그램이 내보내는 형식.

평면은 직선(Line) · 원곡선(Curve) · 완화곡선(Spiral), 종단은 변곡점(PVI) · 포물선 종곡선(ParaCurve) 을 정의 그대로 읽어
CurvedAlignment 로 만든다. 좌표를 샘플링한 파일과 달리 잡음이 없다.

- 좌표는 LandXML 규약대로 "북(N) 동(E)" 순서. 요소 끝점을 파일의 좌표와 대조해서 틀리면 "동 북" 순서도 시도한다 (axis="auto")
- 단위는 <Units> 의 linearUnit 으로 m 로 환산 (meter, millimeter, centimeter, kilometer, foot, USSurveyFoot, inch)
- 지원하지 않는 것(오류로 알림): 측점 방정식(StaEquation), 비대칭 종곡선(UnsymParaCurve), 불규칙선(IrregularLine), Chain
- 완화곡선: clothoid 는 곡률이 거리에 선형인 정확한 클로소이드, japaneseCubic / cubic / cubicParabola 는 정확한 3차 포물선
  (y = x³/(6·R·X), 한국·일본 철도). 그 밖의 종류(bloss, sinusoid 등)는 파일의 theta(끝 접선각)에 맞춘 클로소이드로 근사하고 경고한다
- 근사하는 것(경고): 위 이외의 완화곡선, 원형 종곡선(CircCurve → 같은 길이의 포물선)
"""
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from config.curved_alignment import CubicSpiral, CurvedAlignment, HElement, HorizontalAlignment, VerticalProfile

MAX_BYTES = 300 * 1024 * 1024
CLOSURE_WARN = 0.02       # 요소 끝점이 파일 좌표와 이만큼(m) 넘게 다르면 경고
CLOSURE_REJECT = 1.0      # 이만큼(m) 넘게 다르면 해석이 틀린 것 (좌표 순서/단위 오류)

ANGULAR_UNITS = {"decimal degrees": math.pi / 180.0, "degrees": math.pi / 180.0, "radians": 1.0, "grads": math.pi / 200.0,
                 "gradians": math.pi / 200.0}
CUBIC_TYPES = {"japanesecubic", "cubic", "cubicparabola"}

LINEAR_UNITS = {"meter": 1.0, "metre": 1.0, "millimeter": 0.001, "millimetre": 0.001, "centimeter": 0.01,
                "centimetre": 0.01, "kilometer": 1000.0, "kilometre": 1000.0, "foot": 0.3048,
                "ussurveyfoot": 1200.0 / 3937.0, "inch": 0.0254}


@dataclass
class LandXMLOptions:
    """alignment / profile: 이름(없으면 첫 번째). axis: 'auto' | 'NE' (북 동, LandXML 표준) | 'EN' (동 북)"""
    alignment: str | None = None
    profile: str | None = None
    axis: str = "auto"


@dataclass
class LandXMLAlignmentInfo:
    name: str
    length: float                    # m
    sta_start: float                 # m
    profiles: list = field(default_factory=list)      # 종단 이름 목록 (Profile / ProfAlign 이름)
    has_horizontal: bool = True


# ------------------------------------------------------------------ XML 도우미
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(el, name):
    return [c for c in el if _local(c.tag) == name]


def _kid(el, name):
    k = _kids(el, name)
    return k[0] if k else None


def _floats(text) -> list[float]:
    try:
        return [float(t) for t in (text or "").split()]
    except ValueError:
        raise ValueError(f"숫자로 읽을 수 없는 값입니다 → {text!r}") from None


def _attr(el, name, default=None):
    v = el.get(name)
    return default if v is None else v


def _radius(v) -> float:
    """곡선반경. INF / 없음 = 무한대"""
    if v is None or str(v).strip().upper() in ("INF", "INFINITY", "-INF", ""):
        return math.inf
    return abs(float(v))


def _parse(path):
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except OSError as e:
        raise ValueError(f"{path}: 파일을 열 수 없습니다 ({e.strerror})") from None
    if len(raw) > MAX_BYTES:
        raise ValueError(f"{path}: 파일이 너무 큽니다 (300MB 초과)")
    if b"<!ENTITY" in raw:
        raise ValueError(f"{path}: 엔티티 선언(<!ENTITY)이 있는 XML 은 안전을 위해 읽지 않습니다")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        line, col = e.position
        raise ValueError(f"{path}: XML 형식 오류 (줄 {line}, 열 {col}): {e}") from None
    if _local(root.tag) != "LandXML":
        raise ValueError(f"{path}: LandXML 파일이 아닙니다 (최상위 요소가 {_local(root.tag)})")
    return root


def _unit_factor(root, warns) -> float:
    units = _kid(root, "Units")
    sys_el = next((c for c in units if _local(c.tag) in ("Metric", "Imperial")), None) if units is not None else None
    if sys_el is None:
        warns.append("<Units> 정보가 없어 길이 단위를 m 로 가정했습니다")
        return 1.0
    unit = str(_attr(sys_el, "linearUnit", "meter")).strip().lower()
    if unit not in LINEAR_UNITS:
        raise ValueError(f"지원하지 않는 길이 단위입니다 → {_attr(sys_el, 'linearUnit')}")
    return LINEAR_UNITS[unit]


def _angle_factor(root):
    """<Units> 의 angularUnit → rad 환산 계수 (모르면 None)"""
    units = _kid(root, "Units")
    sys_el = next((c for c in units if _local(c.tag) in ("Metric", "Imperial")), None) if units is not None else None
    if sys_el is None:
        return None
    return ANGULAR_UNITS.get(str(_attr(sys_el, "angularUnit", "")).strip().lower())


def _profiles_of(alignment_el):
    """[(표시 이름, ProfAlign 요소)] — Profile 이름과 ProfAlign 이름을 합쳐 구별"""
    out = []
    for pi, prof in enumerate(_kids(alignment_el, "Profile"), start=1):
        for ai, pa in enumerate(_kids(prof, "ProfAlign"), start=1):
            pname, aname = _attr(prof, "name", f"Profile{pi}"), _attr(pa, "name", f"ProfAlign{ai}")
            out.append((aname if pname == aname else f"{pname} / {aname}", pa))
    return out


def _alignments(root):
    out = []
    for group in _kids(root, "Alignments"):
        out.extend(_kids(group, "Alignment"))
    out.extend(_kids(root, "Alignment"))
    return out


def scan_landxml(path) -> list[LandXMLAlignmentInfo]:
    """파일 안의 선형과 종단 이름 목록 (GUI 에서 고르게 하기 위함)"""
    root = _parse(path)
    warns = []
    f = _unit_factor(root, warns)
    infos = []
    for i, al in enumerate(_alignments(root), start=1):
        cg = _kid(al, "CoordGeom")
        infos.append(LandXMLAlignmentInfo(
            name=_attr(al, "name", f"Alignment{i}"),
            length=float(_attr(al, "length", 0.0)) * f,
            sta_start=float(_attr(al, "staStart", 0.0)) * f,
            profiles=[n for n, _ in _profiles_of(al)],
            has_horizontal=cg is not None and len(list(cg)) > 0))
    if not infos:
        raise ValueError(f"{path}: 선형(Alignment)이 없습니다")
    return infos


# ------------------------------------------------------------------ 평면
def _pt(el, name, axis):
    """(x=동, y=북, 단위 환산 전). LandXML 은 '북 동' 순서"""
    e = _kid(el, name)
    if e is None:
        return None
    v = _floats(e.text)
    if len(v) < 2:
        raise ValueError(f"<{name}> 좌표는 숫자 2개 이상이어야 합니다")
    return (v[0], v[1]) if axis == "EN" else (v[1], v[0])


def _horizontal_elements(cg, f, warns):
    """CoordGeom → [(HElement, 시작점, 끝점, 종류)] (좌표는 파일 원본 값, 길이/반경은 m)"""
    items = []
    for i, el in enumerate(cg, start=1):
        kind = _local(el.tag)
        where = f"평면 {i}번째 요소 <{kind}>"
        try:
            if kind == "Line":
                items.append((el, "Line", float(el.get("length", "nan")) * f))
            elif kind == "Curve":
                if el.get("radius") is None:
                    raise ValueError("radius 가 없습니다")
                items.append((el, "Curve", float(el.get("length", "nan")) * f))
            elif kind == "Spiral":
                items.append((el, "Spiral", float(el.get("length", "nan")) * f))
            else:
                raise ValueError("지원하지 않는 요소입니다 (Line, Curve, Spiral 만 가능)")
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None
    return items


def _curvatures(el, kind, f):
    sign = 1.0 if str(_attr(el, "rot", "ccw")).lower() == "ccw" else -1.0
    if kind == "Line":
        return 0.0, 0.0
    if kind == "Curve":
        k = sign / (float(el.get("radius")) * f)
        return k, k
    r0, r1 = _radius(el.get("radiusStart")), _radius(el.get("radiusEnd"))
    r0, r1 = (r0 * f if r0 != math.inf else r0), (r1 * f if r1 != math.inf else r1)
    return (0.0 if r0 == math.inf else sign / r0), (0.0 if r1 == math.inf else sign / r1)


def _initial_heading(items, axis, f, first_element):
    """첫 요소의 시작 접선 방향각 (rad, +X=동 기준 반시계). first_element: 이미 만든 HElement (방향 변화 계산용)"""
    el, kind, length = items[0]
    s, e = _pt(el, "Start", axis), _pt(el, "End", axis)
    if s is None:
        raise ValueError("첫 요소에 <Start> 좌표가 없습니다")
    if kind == "Line":
        if e is None or math.hypot(e[0] - s[0], e[1] - s[1]) < 1e-9:
            raise ValueError("첫 직선의 <End> 좌표가 없거나 시점과 같습니다")
        return math.atan2(e[1] - s[1], e[0] - s[0])
    if kind == "Curve":
        c = _pt(el, "Center", axis)
        if c is None:
            raise ValueError("첫 원곡선에 <Center> 좌표가 없습니다")
        rad = math.atan2(s[1] - c[1], s[0] - c[0])                  # 중심 → 시점 방향
        return rad + (math.pi / 2 if str(_attr(el, "rot", "ccw")).lower() == "ccw" else -math.pi / 2)
    # Spiral: 진입 완화곡선은 시점 접선이 PI 를 지나고, 진출 완화곡선은 끝점 접선이 PI 를 지남
    k0, k1 = _curvatures(el, kind, f)
    pi_ = _pt(el, "PI", axis)
    if pi_ is None:
        raise ValueError("첫 완화곡선에 <PI> 좌표가 없어 시작 방향을 알 수 없습니다")
    if k0 == 0.0:
        return math.atan2(pi_[1] - s[1], pi_[0] - s[0])
    if k1 == 0.0 and e is not None:
        return math.atan2(e[1] - pi_[1], e[0] - pi_[0]) - first_element.heading_at(first_element.length)
    raise ValueError("첫 요소가 양 끝 곡률이 모두 있는 완화곡선이라 시작 방향을 알 수 없습니다. 앞에 직선을 포함해 내보내세요")


def _spiral_element(el, length, k0, k1, f, ang, warns, seen):
    """완화곡선 요소: 3차 포물선은 정확히, 그 밖의 종류는 theta 에 맞춘 클로소이드로 근사"""
    st = str(_attr(el, "spiType", "clothoid")).strip().lower()
    entry, exit_ = k0 == 0.0 and k1 != 0.0, k1 == 0.0 and k0 != 0.0
    if st == "clothoid" or not (entry or exit_):
        return HElement(length, k0, k1)
    k = k1 if entry else k0
    if st in CUBIC_TYPES:
        total_x = float(el.get("totalX", 0.0)) * f
        trial = CubicSpiral(length, radius=1.0 / abs(k), sign=1.0 if k > 0 else -1.0, exit=exit_)
        if total_x > 0 and abs(total_x - trial.x_length) <= 0.005 * trial.x_length:      # 파일 값이 호 길이와 0.5% 이내로 맞을 때만 사용
            return CubicSpiral(length, radius=1.0 / abs(k), sign=1.0 if k > 0 else -1.0, exit=exit_, total_x=total_x)
        return trial
    theta = el.get("theta")
    if st not in seen:
        seen.add(st)
        warns.append(f"완화곡선 종류 {_attr(el, 'spiType')} 는 지원하지 않아 " +
                     ("끝 접선각(theta)에 맞춘 클로소이드로 근사했습니다 (완화곡선 끝점이 수 cm 어긋날 수 있습니다)"
                      if theta is not None and ang else "클로소이드로 근사했습니다 (방향 오차가 누적될 수 있으니 좌표 대조 경고를 확인하세요)"))
    if theta is not None and ang:
        k_eff = 2.0 * float(theta) * ang / length          # 방향 변화 (k0 + k1) / 2 · L = theta
        return HElement(length, 0.0, math.copysign(k_eff, k)) if entry else HElement(length, math.copysign(k_eff, k), 0.0)
    return HElement(length, k0, k1)


def _build_horizontal(cg, sta_start, f, axis, warns, ang=None):
    items = _horizontal_elements(cg, f, warns)
    if not items:
        raise ValueError("평면 기하(CoordGeom)에 요소가 없습니다")
    # 길이가 0 이거나 없는 요소: 시작~끝 좌표의 거리로 대체
    elements, starts_end, seen = [], [], set()
    for el, kind, length in items:
        if not math.isfinite(length):
            s, e = _pt(el, "Start", axis), _pt(el, "End", axis)
            if s is None or e is None:
                raise ValueError(f"<{kind}> 의 length 도 시작/끝 좌표도 없습니다")
            length = math.hypot(e[0] - s[0], e[1] - s[1]) * f
        if length <= 1e-9:
            continue
        k0, k1 = _curvatures(el, kind, f)
        elements.append(_spiral_element(el, length, k0, k1, f, ang, warns, seen) if kind == "Spiral" else HElement(length, k0, k1))
        starts_end.append((el, kind))
    theta0 = _initial_heading([(starts_end[0][0], starts_end[0][1], elements[0].length)], axis, f, elements[0])
    s0 = _pt(starts_end[0][0], "Start", axis)
    ha = HorizontalAlignment(sta_start, s0[0] * f, s0[1] * f, theta0, elements)
    # 요소 끝점을 파일의 좌표와 대조: 좌표 순서/단위가 틀리면 여기서 크게 어긋난다
    worst, where, sta = 0.0, 0, sta_start
    for n, ((el, kind), he) in enumerate(zip(starts_end, elements), start=1):
        sta += he.length
        e = _pt(el, "End", axis)
        if e is not None:
            px, py = ha.point_at(sta)
            d = math.hypot(px - e[0] * f, py - e[1] * f)
            if d > worst:
                worst, where = d, n
    return ha, worst, where


# ------------------------------------------------------------------ 종단
def _build_profile(pa, f, warns):
    pvis = []
    for el in pa:
        kind = _local(el.tag)
        if kind in ("PVI", "ParaCurve", "CircCurve"):
            v = _floats(el.text)
            if len(v) < 2:
                raise ValueError(f"종단 <{kind}> 에 측점과 표고가 필요합니다")
            if kind == "PVI":
                length = 0.0
            else:
                if el.get("length") is None:
                    raise ValueError(f"종단 <{kind}> 에 length 가 없습니다")
                length = float(el.get("length")) * f
                if kind == "CircCurve":
                    warns.append("원형 종곡선(CircCurve)을 같은 길이의 포물선 종곡선으로 근사했습니다")
            pvis.append((v[0] * f, v[1] * f, length))
        elif kind == "UnsymParaCurve":
            raise ValueError("비대칭 포물선 종곡선(UnsymParaCurve)은 지원하지 않습니다")
    if len(pvis) < 2:
        raise ValueError("종단 변곡점(PVI)이 2개 이상 필요합니다")
    return VerticalProfile(pvis)


# ------------------------------------------------------------------ 진입점
def load_landxml_alignment(path, options: LandXMLOptions | None = None) -> CurvedAlignment:
    opt = options or LandXMLOptions()
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    try:
        return _load(path, opt)
    except ValueError as e:
        msg = str(e)
        raise ValueError(msg if msg.startswith(str(path)) else f"{name}: {msg}") from None


def _load(path, opt):
    if opt.axis not in ("auto", "NE", "EN"):
        raise ValueError(f"axis 는 auto / NE / EN 중 하나여야 합니다 ({opt.axis!r})")
    root = _parse(path)
    warns: list[str] = []
    f = _unit_factor(root, warns)
    if _kid(root, "Units") is not None and f != 1.0:
        warns.append(f"길이 단위를 m 로 환산했습니다 (×{f:.6g})")

    aligns = _alignments(root)
    if not aligns:
        raise ValueError("선형(Alignment)이 없습니다")
    names = [_attr(a, "name", f"Alignment{i}") for i, a in enumerate(aligns, start=1)]
    if opt.alignment is None:
        idx = 0
        if len(aligns) > 1:
            warns.append(f"선형이 {len(aligns)}개라서 첫 번째 '{names[0]}' 를 사용했습니다 (다른 선형: {', '.join(names[1:4])}{' …' if len(names) > 4 else ''})")
    elif opt.alignment in names:
        idx = names.index(opt.alignment)
    else:
        raise ValueError(f"선형 '{opt.alignment}' 이(가) 없습니다. 파일 안의 선형: {', '.join(names)}")
    al = aligns[idx]
    if _kid(al, "StaEquation") is not None:
        raise ValueError("측점 방정식(StaEquation)이 있는 선형은 지원하지 않습니다")
    cg = _kid(al, "CoordGeom")
    if cg is None:
        raise ValueError(f"선형 '{names[idx]}' 에 평면 기하(CoordGeom)가 없습니다")
    sta_start = float(_attr(al, "staStart", 0.0)) * f

    profiles = _profiles_of(al)
    if not profiles:
        raise ValueError(f"선형 '{names[idx]}' 에 종단(Profile)이 없습니다. 표고가 필요하므로 종단을 포함해 내보내세요")
    pnames = [n for n, _ in profiles]
    if opt.profile is None:
        pi = 0
        if len(profiles) > 1:
            warns.append(f"종단이 {len(profiles)}개라서 첫 번째 '{pnames[0]}' 를 사용했습니다 (다른 종단: {', '.join(pnames[1:4])})")
    else:
        pi = next((i for i, n in enumerate(pnames) if n == opt.profile or n.split(" / ")[-1] == opt.profile), None)
        if pi is None:
            raise ValueError(f"종단 '{opt.profile}' 이(가) 없습니다. 선형 '{names[idx]}' 의 종단: {', '.join(pnames)}")
    vertical = _build_profile(profiles[pi][1], f, warns)

    # 좌표 순서: 표준(북 동)을 먼저, 끝점 대조가 틀리면 (동 북)도 시도
    axes = ("NE", "EN") if opt.axis == "auto" else (opt.axis,)
    results, failures = {}, []
    for axis in axes:
        w = []
        try:
            ha, worst, where = _build_horizontal(cg, sta_start, f, axis, w, _angle_factor(root))
        except ValueError as e:
            if len(axes) == 1:
                raise
            failures.append(f"{axis}: {e}")
            continue
        results[axis] = (ha, worst, where, w)
        if worst <= CLOSURE_REJECT:
            break
    good = [a for a, v in results.items() if v[1] <= CLOSURE_REJECT]
    if not good:
        detail = " / ".join([f"{a}: 끝점 어긋남 {v[1]:.2f}m(요소 {v[2]})" for a, v in results.items()] + failures)
        raise ValueError(f"요소 끝점이 파일의 좌표와 크게 어긋납니다 ({detail}). 좌표 순서나 단위를 확인하세요")
    axis = good[0]
    ha, worst, where, w = results[axis]
    warns.extend(w)
    if axis == "EN" and opt.axis == "auto":
        warns.append("좌표를 '동 북' 순서로 해석했습니다 (LandXML 표준은 '북 동'). 파일이 표준과 다르게 내보내졌을 수 있습니다")
    if worst > CLOSURE_WARN:
        warns.append(f"요소 {where} 의 끝점이 파일 좌표와 {worst * 100:.1f}cm 다릅니다 (좌표 반올림이나 완화곡선 종류 차이일 수 있습니다)")

    a = CurvedAlignment(ha, vertical)
    a.warnings = warns
    a.source = "LandXML"
    a.alignment_name, a.profile_name = names[idx], pnames[pi]
    a.validate()
    return a
