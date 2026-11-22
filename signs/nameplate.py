"""역명판·안내사인 이미지 생성 (Pillow, 화면 비의존).

구조는 역명판 생성기(buttaiwan.github.io/eki)와 같은 방식: 스타일 등록부(STYLES) + 공통 입력 항목(NameplateInput) +
스타일별 그리기 함수(render) → 이미지. 좌표·글자 크기는 '기준 단위'로 쓰고 MASTER_SCALE 배로 그린다.
그리기 코드는 이 프로젝트에서 새로 작성했다 (생성기 저장소에 라이선스가 없어 코드를 옮기지 않음).
글꼴은 운영체제 글꼴을 찾아 쓰고(맑은 고딕·Yu Gothic·Arial), 없으면 Pillow 기본 글꼴.
"""
import os
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

MASTER_SCALE = 3
_FONT_DIRS = [os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"), "/usr/share/fonts/truetype",
              "/usr/share/fonts/opentype", "/usr/share/fonts"]
# 글꼴 이름 → 후보 파일 (앞에서부터)
FONTS = {"KR_B": ["malgunbd.ttf", "NanumGothicBold.ttf", "NotoSansCJK-Bold.ttc"],
         "KR": ["malgun.ttf", "NanumGothic.ttf", "NotoSansCJK-Regular.ttc"],
         "JP": ["YuGothM.ttc", "msgothic.ttc", "NotoSansCJK-Regular.ttc", "malgun.ttf"],
         "CN": ["msyh.ttc", "malgun.ttf", "NotoSansCJK-Regular.ttc"],
         "EN_B": ["arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
         "EN": ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]}
_cache: dict = {}


def _find(name: str):
    for f in FONTS[name]:
        for d in _FONT_DIRS:
            p = os.path.join(d, f)
            if os.path.isfile(p):
                return p
            if os.path.isdir(d):                                  # 하위 폴더 (리눅스)
                for root, _, files in os.walk(d):
                    if f in files:
                        return os.path.join(root, f)
    return None


def font(name: str, size: float):
    """기준 단위 크기 → 실제 글꼴 (MASTER_SCALE 배)"""
    key = (name, int(round(size * MASTER_SCALE)))
    if key not in _cache:
        path = _find(name)
        try:
            _cache[key] = ImageFont.truetype(path, key[1]) if path else ImageFont.load_default()
        except OSError:
            _cache[key] = ImageFont.load_default()
    return _cache[key]


def text_width(name: str, size: float, text: str) -> float:
    """글자 폭 (기준 단위)"""
    if not text:
        return 0.0
    l, _, r, _ = font(name, size).getbbox(text)
    return (r - l) / MASTER_SCALE


def hex_rgb(h: str, default=(0, 82, 164)) -> tuple:
    h = (h or "").strip().lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else default
    except ValueError:
        return default


def fg_on(rgb) -> tuple:
    """바탕색 위 글자색 (밝으면 검정, 어두우면 흰색)"""
    return (0, 0, 0) if 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 160 else (255, 255, 255)


class Canvas:
    """기준 단위 좌표로 그리는 캔버스 (MASTER_SCALE 배 이미지)"""

    def __init__(self, width: float, height: float, bg=(255, 255, 255)):
        self.w, self.h = width, height
        self.img = Image.new("RGB", (max(1, round(width * MASTER_SCALE)), max(1, round(height * MASTER_SCALE))), bg)
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def _s(*v):
        return [round(x * MASTER_SCALE) for x in v]

    def rect(self, x, y, w, h, color):
        self.d.rectangle(self._s(x, y, x + w, y + h), fill=color)

    def rounded(self, x, y, w, h, r, color):
        self.d.rounded_rectangle(self._s(x, y, x + w, y + h), radius=round(r * MASTER_SCALE), fill=color)

    def circle(self, cx, cy, r, color):
        self.d.ellipse(self._s(cx - r, cy - r, cx + r, cy + r), fill=color)

    def polygon(self, pts, color):
        self.d.polygon([tuple(self._s(x, y)) for x, y in pts], fill=color)

    def text(self, text, x, y, size, name="KR_B", color=(0, 0, 0), align="left"):
        """(x, y) = 글자 윗부분 기준점 (align: left / center / right)"""
        if not text:
            return
        anchor = {"left": "la", "center": "ma", "right": "ra"}[align]
        self.d.text(tuple(self._s(x, y)), text, font=font(name, size), fill=color, anchor=anchor)


@dataclass
class NameplateInput:
    """공통 입력 항목 (스타일마다 쓰는 항목이 다름 — Style.fields). prev / next = 이전·다음 역 StationRef (없으면 None)"""
    kname: str = ""
    ename: str = ""
    cname: str = ""
    jname: str = ""
    no: str = ""
    rgb: str = "#0052A4"
    prev: object = None
    next: object = None


@dataclass
class Style:
    id: str
    label: str
    fields: list
    render: object = field(repr=False)


STYLES: dict = {}


def define_style(id: str, label: str, fields: list):
    def deco(fn):
        STYLES[id] = Style(id, label, fields, fn)
        return fn
    return deco


def render_nameplate(style: str, inp: NameplateInput) -> Image.Image:
    if style not in STYLES:
        raise ValueError(f"역명판 스타일 '{style}' 이(가) 없습니다 (가능: {', '.join(STYLES)})")
    return STYLES[style].render(inp).img


def _has(ref) -> bool:
    return ref is not None and bool(ref.kname or ref.ename)


# ================================================================== 스타일
@define_style("seoul", "서울 지하철형", ["kname", "ename", "cname", "jname", "no", "rgb", "prev", "next"])
def _seoul(inp: NameplateInput) -> Canvas:
    """흰 바탕 + 노선색 둥근 테두리, 왼쪽 역번호 원, 큰 한글 역명 + 영문·한자·일문, 아래 띠에 이전 ◀ · ▶ 다음 역"""
    rgb = hex_rgb(inp.rgb)
    kw = text_width("KR_B", 46, inp.kname)
    sub = max(text_width("EN_B", 22, inp.ename),
              text_width("CN", 18, inp.cname) + (text_width("JP", 18, inp.jname) + 12 if inp.jname and inp.jname != inp.cname else 0))
    has_nb = _has(inp.prev) or _has(inp.next)
    top_h, nb_h = 150, (60 if has_nb else 0)
    width = max(200 + kw + 24 + sub + 60, 560)
    height = top_h + nb_h
    c = Canvas(width, height)
    c.rounded(2, 2, width - 4, height - 4, 40, rgb)
    c.rounded(16, 16, width - 32, top_h - 26, 30, (255, 255, 255))
    c.circle(100, top_h / 2 + 3, 38, rgb)
    c.text(inp.no, 100, top_h / 2 - 14, 28, "EN_B", fg_on(rgb), "center")
    c.text(inp.kname, 160, top_h / 2 - 34, 46, "KR_B")
    c.text(inp.ename, 160 + kw + 24, top_h / 2 - 30, 22, "EN_B")
    c.text(inp.cname, 160 + kw + 24, top_h / 2 + 2, 18, "CN")
    if inp.jname and inp.jname != inp.cname:
        c.text(inp.jname, 160 + kw + 24 + text_width("CN", 18, inp.cname) + 12, top_h / 2 + 2, 18, "JP")
    if has_nb:
        fg, y = fg_on(rgb), top_h - 2
        if _has(inp.prev):
            c.polygon([(30, y + 25), (48, y + 12), (48, y + 38)], fg)
            c.text(f"{inp.prev.kname}  {inp.prev.ename}".strip(), 60, y + 10, 20, "KR_B", fg)
        if _has(inp.next):
            c.polygon([(width - 30, y + 25), (width - 48, y + 12), (width - 48, y + 38)], fg)
            c.text(f"{inp.next.kname}  {inp.next.ename}".strip(), width - 60, y + 10, 20, "KR_B", fg, "right")
    return c


@define_style("korail", "코레일형", ["kname", "ename", "cname", "prev", "next"])
def _korail(inp: NameplateInput) -> Canvas:
    """짙은 녹색 바탕 흰 글자: 가운데 큰 한글 역명, 그 아래 가로줄 + 영문(왼쪽)·한자(오른쪽), 아래에 이전·다음 역"""
    bg, fg = (24, 62, 44), (255, 255, 255)
    kw = text_width("KR_B", 56, inp.kname)
    ew, cw = text_width("EN_B", 22, inp.ename), text_width("CN", 20, inp.cname)
    bar = max(kw, ew + cw + 30, 320)
    nb = [r for r in (inp.prev, inp.next) if _has(r)]
    width = max(bar + 120, 640)
    height = 300 if nb else 220
    c = Canvas(width, height, bg)
    cx, x0 = width / 2, (width - bar) / 2
    c.text(inp.kname, cx, 30, 56, "KR_B", fg, "center")
    c.rect(x0, 112, bar, 4, fg)
    c.text(inp.ename, x0, 126, 22, "EN_B", fg)
    c.text(inp.cname, x0 + bar, 126, 20, "CN", fg, "right")
    if nb:
        c.rect(30, 196, width - 60, 2, (150, 180, 160))
        if _has(inp.prev):
            c.polygon([(40, 245), (60, 230), (60, 260)], fg)
            c.text(inp.prev.kname, 72, 218, 28, "KR_B", fg)
            c.text(inp.prev.ename, 72, 254, 14, "EN", fg)
        if _has(inp.next):
            c.polygon([(width - 40, 245), (width - 60, 230), (width - 60, 260)], fg)
            c.text(inp.next.kname, width - 72, 218, 28, "KR_B", fg, "right")
            c.text(inp.next.ename, width - 72, 254, 14, "EN", fg, "right")
    return c


# ================================================================== 안내사인
def _fit(text, name, size, max_w):
    """글자가 max_w 를 넘으면 크기를 줄임"""
    w = text_width(name, size, text)
    return size if w <= max_w or w == 0 else max(8.0, size * max_w / w)


def render_boarding(w_m: float, h_m: float, dest: str, rgb: str = "#0052A4") -> Image.Image:
    """'타는 곳' 사인: 짙은 남색 바탕, 왼쪽 노선색 띠 + 아래 화살표, '타는 곳 Platform' + 'OO 방면'"""
    H = 120.0
    W = H * w_m / h_m
    c = Canvas(W, H, (20, 32, 64))
    col = hex_rgb(rgb)
    c.rect(0, 0, 14, H, col)
    ax = 70
    c.polygon([(ax - 26, 40), (ax + 26, 40), (ax, 86)], (255, 255, 255))
    c.rect(ax - 9, 14, 18, 30, (255, 255, 255))
    x = 120
    c.text("타는 곳", x, 16, _fit("타는 곳", "KR_B", 40, W - x - 20), "KR_B", (255, 255, 255))
    c.text("Platform", x + text_width("KR_B", 40, "타는 곳") + 16, 30, 22, "EN_B", (200, 210, 230))
    if dest:
        c.text(dest, x, 70, _fit(dest, "KR_B", 30, W - x - 20), "KR_B", (255, 214, 0))
    return c.img


def render_exit(w_m: float, h_m: float, number: str, destinations: str) -> Image.Image:
    """'출구' 사인: 노란 바탕 검정 글자, 왼쪽 검정 상자에 출구 번호, 오른쪽 목적지 (줄바꿈 = 여러 줄)"""
    H = 120.0
    W = H * w_m / h_m
    c = Canvas(W, H, (255, 205, 0))
    c.rect(14, 14, 92, 92, (0, 0, 0))
    c.text(number or "?", 60, 22, _fit(number or "?", "EN_B", 56, 80), "EN_B", (255, 205, 0), "center")
    c.text("출구", 124, 12, 30, "KR_B", (0, 0, 0))
    c.text("Exit", 124 + text_width("KR_B", 30, "출구") + 10, 22, 18, "EN_B", (0, 0, 0))
    lines = [s.strip() for s in (destinations or "").splitlines() if s.strip()][:3]
    for k, ln in enumerate(lines):
        c.text(ln, 124, 54 + k * 22, _fit(ln, "KR", 18, W - 140), "KR", (0, 0, 0))
    return c.img


def render_entrance_sign(w_m: float, h_m: float, line: str, kname: str, ename: str, cname: str, jname: str, number: str,
                         bg: str = "#3C3F45", rgb: str = "#0052A4") -> Image.Image:
    """출입구 캐노피 앞 사인 (실무 사진 양식): 왼쪽 노선 배지(노선색 원 + 노선명), 역명(한글 크게 + 영문·한자·일문 작게),
    오른쪽 '출입구 Entrance' + 노란 번호 상자. 배경색 bg (글자색은 배경 밝기로 자동)"""
    H = 100.0
    W = H * w_m / h_m
    bgc = hex_rgb(bg, (60, 63, 69))
    fg = fg_on(bgc)
    c = Canvas(W, H, bgc)
    x = 16.0
    if line:                                       # 노선 배지
        lc = hex_rgb(rgb)
        c.circle(x + 32, 50, 32, (255, 255, 255))
        c.circle(x + 32, 50, 28, lc)
        size = _fit(line, "EN_B", 18, 48)
        c.text(line, x + 32, 50 - size * 0.62, size, "EN_B", fg_on(lc), "center")
        x += 84
    bx = W - 16 - 70                               # 번호 상자
    c.rect(bx, 15, 70, 70, (255, 200, 0))
    ns = _fit(number or "?", "EN_B", 52, 60)
    c.text(number or "?", bx + 35, 50 - ns * 0.62, ns, "EN_B", (0, 0, 0), "center")
    c.text("출입구", bx - 12, 26, 22, "KR_B", fg, "right")
    c.text("Entrance", bx - 12, 56, 14, "EN", fg, "right")
    lw = max(text_width("KR_B", 22, "출입구"), text_width("EN", 14, "Entrance"))
    room = bx - 12 - lw - 24 - x                   # 역명 자리
    small = [s for s in (ename, " ".join(v for v in (cname, jname if jname != cname else "") if v)) if s]
    sw = max([text_width("EN", 16, s) for s in small] + [0.0])
    ks = _fit(kname, "KR_B", 48, max(room - sw - 16, 40))
    c.text(kname, x, 50 - ks * 0.66, ks, "KR_B", fg)
    sx = x + text_width("KR_B", ks, kname) + 16
    for k, s_ in enumerate(small):
        name = "EN" if k == 0 else "CN"
        c.text(s_, sx, 30 + k * 24, _fit(s_, name, 16, max(bx - 12 - lw - 16 - sx, 20)), name, fg)
    return c.img
