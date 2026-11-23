"""승강장 호출 버튼 판 · 층 표시기 (내부 · 외부 엘리베이터 공통).

문마다: 호출 버튼 판(`CALLP`) + 버튼(`CALLU` 위 / `CALLD` 아래 — 최하 정지층은 위만, 최상 정지층은 아래만) + 문 위 층 표시기(`IND`).
버튼·표시기 앞면에는 그린 이미지 한 장 (DAE·웹 뷰어). 표시기 이미지는 층 이름 × 방향(정지·위·아래)마다 미리 그려 두고
웹 뷰어가 카 위치에 따라 바꿈 — 그 밖의 출력은 카가 서 있는 층 이름.
좌표: 문 면의 법선 축 n (바깥 = sign 쪽), 접선 축 v, 표고 z. 코드의 면 = PS/NS/PT/NT (s = 정거장 s 또는 EV 좌표 u).
"""
from elevators.elevator_type import ElevatorPartKind as K

PANEL_H, PANEL_T, PANEL_Z = 0.28, 0.015, 1.05        # 호출 버튼 판 높이·두께·중심 높이 (정지 바닥 위)
BTN, BTN_T, BTN_DZ = 0.05, 0.006, 0.055              # 버튼 크기·두께, 위·아래 버튼 중심 ± 간격
IND_W, IND_H, IND_T = 0.36, 0.16, 0.025              # 층 표시기 폭·높이·두께
DIR_NONE, DIR_UP, DIR_DOWN = "", "up", "down"


def face_code(axis: str, sign: int) -> str:
    return ("P" if sign > 0 else "N") + {"u": "S"}.get(axis, axis.upper())


def right_sign(axis: str, sign: int) -> int:
    """문을 마주 보는 사람의 오른쪽이 접선 축의 + 인가 (법선 = sign · axis)"""
    return sign if axis in ("s", "u") else -sign


def hall_fixtures(axis: str, sign: int, o: float, mid: float, zf: float, level: str, stop: int, *, panel_at: float, panel_w: float,
                  ind_z: float, up: bool, down: bool):
    """(코드, 종류, 법선 구간, 접선 구간, z 구간) 목록. o = 붙는 면의 법선 좌표, zf = 정지 바닥, panel_at = 판 중심 접선 좌표,
    ind_z = 표시기 중심 높이 (정지 바닥 위)"""
    f = face_code(axis, sign)
    n = lambda a, b: tuple(sorted((o + sign * a, o + sign * b)))
    out = [(f"CALLP_{f}_{level}", K.CALL_PANEL, n(0.0, PANEL_T), (panel_at - panel_w / 2.0, panel_at + panel_w / 2.0),
            (zf + PANEL_Z - PANEL_H / 2.0, zf + PANEL_Z + PANEL_H / 2.0))]
    both = up and down
    for on, tag, dz in ((up, "CALLU", BTN_DZ), (down, "CALLD", -BTN_DZ)):
        if on:
            zc = zf + PANEL_Z + (dz if both else 0.0)
            out.append((f"{tag}_{f}_{level}", K.CALL_BUTTON, n(PANEL_T, PANEL_T + BTN_T), (panel_at - BTN / 2.0, panel_at + BTN / 2.0),
                        (zc - BTN / 2.0, zc + BTN / 2.0)))
    out.append((f"IND_{f}_{level}", K.INDICATOR, n(0.0, IND_T), (mid - IND_W / 2.0, mid + IND_W / 2.0),
                (zf + ind_z - IND_H / 2.0, zf + ind_z + IND_H / 2.0)))
    return out


def parse_code(code: str):
    """버튼·표시기·문짝 코드 → (앞말, 축 's'|'t', 부호) — 예 IND_PT_B1F → ('IND', 't', 1), CAR_DOOR_NS_P → ('CAR_DOOR', 's', -1)"""
    for head in ("CAR_DOOR", "LDOOR", "CALLP", "CALLU", "CALLD", "IND"):
        if code.startswith(head + "_"):
            f = code[len(head) + 1:len(head) + 3]
            return head, f[1].lower(), 1 if f[0] == "P" else -1
    return None


# ====================================================================== 이미지
def _font(size: int):
    from signs.nameplate import MASTER_SCALE, font
    return font("EN_B", size / MASTER_SCALE)                        # nameplate 글꼴 크기는 기준 단위 (× MASTER_SCALE)


def render_button(direction: str, px: int = 128):
    """호출 버튼 (둥근 금속 버튼 + 위·아래 세모, 주황 불빛 테두리)"""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (px, px), (150, 153, 157))
    d = ImageDraw.Draw(im)
    m = px * 0.05
    d.ellipse((m, m, px - m, px - m), fill=(70, 73, 78), outline=(255, 160, 40), width=max(2, px // 24))
    c, r = px / 2.0, px * 0.22
    k = -1 if direction == DIR_UP else 1
    d.polygon([(c, c + k * r), (c - r, c - k * r * 0.7), (c + r, c - k * r * 0.7)], fill=(245, 245, 245))
    return im


def render_indicator(label: str, direction: str = DIR_NONE, w: int = 288, h: int = 128):
    """층 표시기 (검정 바탕에 주황 층 이름 + 방향 화살표)"""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), (12, 13, 15))
    d = ImageDraw.Draw(im)
    amber = (255, 150, 30)
    d.rectangle((2, 2, w - 3, h - 3), outline=(70, 73, 78), width=3)
    font = _font(int(h * 0.62))
    box = d.textbbox((0, 0), label, font=font)
    x0 = w * 0.62 - (box[2] - box[0]) / 2.0 if direction else (w - (box[2] - box[0])) / 2.0
    d.text((x0 - box[0], (h - (box[3] - box[1])) / 2.0 - box[1]), label, font=font, fill=amber)
    if direction:
        c, r, cy = w * 0.17, h * 0.24, h / 2.0
        k = -1 if direction == DIR_UP else 1
        d.polygon([(c, cy + k * r), (c - r, cy - k * r), (c + r, cy - k * r)], fill=amber)
    return im


def front_frame(to_world, axis: str, sign: int, nrm: tuple, tan: tuple, z: tuple) -> tuple:
    """상자 앞면의 uv 틀: (왼쪽 아래 세계 좌표, 오른쪽 단위 벡터, 위, 폭, 높이, 0). to_world(s, t) → (x, y)"""
    nf = nrm[1] if sign > 0 else nrm[0]
    rs = right_sign(axis, sign)
    a, b = (tan[0], tan[1]) if rs > 0 else (tan[1], tan[0])                  # 왼쪽 끝 → 오른쪽 끝
    p0 = to_world(nf, a) if axis in ("s", "u") else to_world(a, nf)
    p1 = to_world(nf, b) if axis in ("s", "u") else to_world(b, nf)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    w = (dx * dx + dy * dy) ** 0.5
    return ((p0[0], p0[1], z[0]), (dx / w, dy / w, 0.0), (0.0, 0.0, 1.0), w, z[1] - z[0], 0.0)


def fixture_image(code: str, label: str):
    """버튼·표시기 코드 → 이미지 (판이면 None). label = 카가 서 있는 층 이름"""
    if code.startswith("CALLU"):
        return render_button(DIR_UP)
    if code.startswith("CALLD"):
        return render_button(DIR_DOWN)
    return render_indicator(label) if code.startswith("IND") else None


def indicator_key(label: str, direction: str = DIR_NONE) -> str:
    """웹 뷰어 표시기 이미지 키 ('사인 ' 으로 시작 = 반복 없이 한 장)"""
    return f"사인 IND|{label}|{direction}"
