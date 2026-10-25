"""좌표 목록 텍스트 파일(txt / csv / dat 등) → SampledAlignment.

Bentley(OpenRoads), Civil 3D, 기타 프로그램에서 선형을 일정 간격으로 내보낸 파일을 읽는다.
- 구분자: 쉼표, 세미콜론, 탭, 공백 (첫 데이터 줄로 판단). 세미콜론/탭 파일의 소수점 쉼표(12,5)도 읽음
- 빈 줄, # 또는 // 로 시작하는 주석 줄, 머리글 줄은 건너뜀. 인코딩은 UTF-8(BOM 포함) → CP949 순으로 시도
- 열 순서(order): 문자 하나가 열 하나. s=측점, x=동(Easting), y=북(Northing), z=표고, -=무시. 문자열보다 열이 많으면 나머지 열은 무시
    "xyz"  : X Y Z                      "yxz"  : Y(N) X(E) Z  (Civil 3D 의 N,E,Z 순서)
    "sxyz" : 측점 X Y Z                  "syxz" : 측점 Y X Z
    "-yxz" : 점번호 N E Z (PENZD 형식, 뒤의 설명 열은 무시)
  "auto" 는 머리글이 있으면 머리글(X/Y/Z, Easting/Northing/Elevation, Station 등)로, 없으면 열 개수로 판단하며,
  판단이 모호하면(예: 열 4개인데 첫 열이 측점이 아님) 오류로 알려 직접 지정하게 한다.
- 길이 단위는 m 로 간주한다.
"""
import math
import re
from dataclasses import dataclass

from config.sampled_alignment import SampledAlignment

# GUI 선택지: (표시 이름, order)
ORDER_PRESETS = [
    ("자동 판단 (머리글 / 열 개수)", "auto"),
    ("X Y Z  (X=동, Y=북)", "xyz"),
    ("Y X Z  (북, 동, 표고)", "yxz"),
    ("측점 X Y Z", "sxyz"),
    ("측점 Y X Z", "syxz"),
    ("점번호 Y X Z  (PENZD)", "-yxz"),
]

_HEADER_WORDS = {
    "s": {"s", "sta", "sta.", "stn", "station", "chainage", "chain", "ch", "측점", "누가거리"},
    "x": {"x", "e", "east", "easting", "동", "동거리"},
    "y": {"y", "n", "north", "northing", "북", "북거리"},
    "z": {"z", "el", "elev", "elevation", "h", "ht", "height", "표고", "고도"},
}


@dataclass
class XYZOptions:
    """텍스트 선형 읽기 옵션
    start_station: 측점 열이 없을 때 첫 점의 측점 (m). 측점 열이 있으면 그 첫 값을 씀
    smooth_m: 방향·곡률·구배 평활 반폭 (m). 좌표가 cm 단위로 거칠면 8~12 권장
    """
    order: str = "auto"
    start_station: float = 0.0
    smooth_m: float = 5.0


def read_text(path) -> str:
    """파일을 텍스트로 읽음 (UTF-8 → CP949)"""
    try:
        raw = open(path, "rb").read()
    except OSError as e:
        raise ValueError(f"{path}: 파일을 열 수 없습니다 ({e.strerror})") from None
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: 문자 인코딩을 알 수 없습니다 (UTF-8 또는 CP949 텍스트 파일이어야 합니다)")


def _split(line: str, sep: str) -> list[str]:
    parts = line.split(None) if sep == " " else line.split(sep)
    return [p.strip().strip('"').strip("'") for p in parts if not (sep == " " and not p)]


def _sep(line: str) -> str:
    for sep in (";", "\t", ","):
        if sep in line:
            return sep
    return " "


def _num(tok: str, sep: str) -> float:
    if "," in tok and sep != ",":
        tok = tok.replace(",", ".")                     # 소수점 쉼표
    return float(tok)


def _header_order(tokens: list[str]) -> str | None:
    """머리글 줄에서 열 순서를 알아냄. x, y, z 를 모두 찾지 못하면 None"""
    order, seen = "", set()
    for tok in tokens:
        t = tok.strip().lower().rstrip(":")
        code = next((c for c, words in _HEADER_WORDS.items() if t in words and c not in seen), "-")
        if code != "-":
            seen.add(code)
        order += code
    return order.rstrip("-") if {"x", "y", "z"} <= seen else None


def _station_like(rows: list[list[float]]) -> bool:
    """4열 자료의 첫 열이 측점(증가하며 인접 좌표 거리와 비슷한 간격)인지"""
    pts = rows[:60]
    ratios = []
    for a, b in zip(pts, pts[1:]):
        chord = math.hypot(b[1] - a[1], b[2] - a[2])
        if chord > 1e-9:
            if b[0] <= a[0]:
                return False
            ratios.append((b[0] - a[0]) / chord)
    if not ratios:
        return False
    median = sorted(ratios)[len(ratios) // 2]
    return 0.8 < median < 1.25


def parse_xyz_text(text: str, options: XYZOptions | None = None, name: str = "") -> SampledAlignment:
    opt = options or XYZOptions()
    if opt.order != "auto" and not re.fullmatch(r"[sxyz-]+", opt.order or ""):
        raise ValueError(f"열 순서 '{opt.order}' 가 올바르지 않습니다 (s, x, y, z, - 문자만 사용)")
    prefix = f"{name}: " if name else ""
    warns = []
    lines = [(no, ln.strip()) for no, ln in enumerate(text.splitlines(), start=1)
             if ln.strip() and not ln.strip().startswith(("#", "//"))]
    if not lines:
        raise ValueError(f"{prefix}좌표 줄이 없습니다")

    # 머리글: 첫 줄이 (지정한 열 범위에서) 숫자로 읽히지 않으면 머리글. 머리글과 데이터의 구분자는 서로 달라도 됨
    sep = _sep(lines[0][1])
    first = _split(lines[0][1], sep)

    def numeric(tok):
        try:
            _num(tok, sep)
            return True
        except ValueError:
            return False
    checked = first[:len(opt.order)] if opt.order != "auto" else first
    is_header = not any(numeric(t) for t in first) if opt.order == "auto" else not all(numeric(t) for t in checked)
    header = None
    if is_header:
        header = first
        lines = lines[1:]
        if not lines:
            raise ValueError(f"{prefix}머리글만 있고 좌표 줄이 없습니다")
        sep = _sep(lines[0][1])
    rows_raw = [(no, _split(ln, sep)) for no, ln in lines]

    order = opt.order
    if order == "auto":
        order = _header_order(header) if header else None
        if order is None:
            n = len(rows_raw[0][1])
            if header:
                raise ValueError(f"{prefix}머리글({', '.join(header)})에서 X, Y, Z 열을 찾지 못했습니다. 열 순서를 직접 지정하세요")
            if n == 3:
                order = "xyz"
            elif n == 4:
                try:
                    probe = [[_num(t, sep) for t in toks[:4]] for _, toks in rows_raw[:60]]
                except ValueError:
                    probe = []
                if probe and _station_like(probe):
                    order = "sxyz"
                else:
                    raise ValueError(f"{prefix}열이 4개인데 첫 열이 측점으로 보이지 않습니다. 첫 열이 점번호면 '-xyz' 계열, 측점이면 'sxyz' 로 열 순서를 직접 지정하세요")
            elif n == 2:
                raise ValueError(f"{prefix}표고(z) 열이 없습니다. x, y, z 3개 열이 필요합니다")
            else:
                raise ValueError(f"{prefix}열이 {n}개입니다. 열 순서를 직접 지정하세요 (예: PENZD 파일은 '-yxz')")
            if order == "xyz":
                warns.append("열 순서를 X Y Z (X=동, Y=북)로 해석했습니다. 북, 동 순서(Northing, Easting) 파일이면 'Y X Z' 를 선택하세요")
            elif order == "sxyz":
                warns.append("열 순서를 측점 X Y Z (X=동, Y=북)로 해석했습니다. 북, 동 순서 파일이면 '측점 Y X Z' 를 선택하세요")
    need = len(order)
    if len(set(order) - {"-"}) != len([c for c in order if c != "-"]):
        raise ValueError(f"{prefix}열 순서 '{order}' 에 같은 열이 두 번 나옵니다")
    cols = {c: order.index(c) for c in "sxyz" if c in order}
    for c in "xyz":
        if c not in cols:
            raise ValueError(f"{prefix}열 순서 '{order}' 에 {c} 가 없습니다")

    xs, ys, zs, ss = [], [], [], []
    for no, toks in rows_raw:
        if len(toks) < need:
            raise ValueError(f"{prefix}{no}번째 줄: 열이 {len(toks)}개입니다 (열 순서 '{order}' 에는 {need}개 이상 필요)")
        try:
            vals = {c: _num(toks[i], sep) for c, i in cols.items()}
        except ValueError:
            raise ValueError(f"{prefix}{no}번째 줄: 숫자로 읽을 수 없는 값이 있습니다 → {' '.join(toks[:need])}") from None
        xs.append(vals["x"]); ys.append(vals["y"]); zs.append(vals["z"])
        if "s" in vals:
            ss.append(vals["s"])

    start = opt.start_station
    if ss:
        if any(b <= a for a, b in zip(ss, ss[1:])):
            raise ValueError(f"{prefix}측점 열이 증가하지 않습니다. 점 순서가 선형 진행 방향이 맞는지 확인하세요")
        start = ss[0]
        chords = [math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(len(xs) - 1)]
        ratio = sorted(abs(ss[i + 1] - ss[i] - c) / c for i, c in enumerate(chords) if c > 1e-9)
        if ratio and ratio[len(ratio) // 2] > 0.01:
            warns.append("측점 열의 간격이 좌표의 평면 거리와 1% 이상 다릅니다. 측점은 좌표 간 평면 거리로 다시 계산하며, "
                         "첫 점의 측점만 파일 값을 사용합니다 (3D 거리나 다른 기준의 측점이면 어긋날 수 있습니다)")
    al = SampledAlignment(xs, ys, zs, start_station=start, smooth_m=opt.smooth_m, warnings=warns, name=name)
    al.order = order
    return al


def load_xyz_alignment(path, options: XYZOptions | None = None) -> SampledAlignment:
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    return parse_xyz_text(read_text(path), options, name=name)


def preview_lines(path, count: int = 8) -> list[str]:
    """GUI 미리보기용: 파일의 앞부분 줄"""
    try:
        return [ln.rstrip() for ln in read_text(path).splitlines()[:count]]
    except ValueError:
        return ["(미리보기를 읽을 수 없습니다)"]
