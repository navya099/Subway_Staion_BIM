"""비품 앞면 그림 (Pillow, 같은 입력이면 다시 그리지 않음): 발매기 화면, 옥내소화전 문, 매달림 안내사인"""
from functools import lru_cache

from signs.nameplate import Canvas, _fit, fg_on, hex_rgb

ARROWS = "←→↑↓"


@lru_cache(maxsize=None)
def ticket_machine(w: float, h: float, text: str):
    c = Canvas(90 * w / 0.9, 190 * h / 1.9, (210, 213, 216))
    W, H = 90 * w / 0.9, 190 * h / 1.9
    c.rect(0, 0, W, H * 0.12, (0, 82, 164))
    c.text(text or "승차권 발매기", W / 2, H * 0.035, _fit(text or "승차권 발매기", "KR_B", 10, W - 8), "KR_B", (255, 255, 255), "center")
    c.rect(W * 0.1, H * 0.17, W * 0.8, H * 0.27, (25, 30, 38))                       # 화면
    c.rect(W * 0.12, H * 0.185, W * 0.76, H * 0.24, (70, 140, 210))
    for k in range(3):
        c.rect(W * (0.16 + 0.24 * k), H * 0.22, W * 0.2, H * 0.08, (240, 245, 250))
    c.rect(W * 0.1, H * 0.5, W * 0.36, H * 0.05, (60, 64, 70))                        # 지폐·카드 투입구
    c.rect(W * 0.56, H * 0.5, W * 0.34, H * 0.1, (90, 95, 102))
    c.rect(W * 0.25, H * 0.7, W * 0.5, H * 0.08, (50, 53, 58))                        # 배출구
    return c.img


@lru_cache(maxsize=None)
def hydrant(w: float, h: float):
    W, H = 70 * w / 0.7, 120 * h / 1.2
    c = Canvas(W, H, (196, 199, 202))
    c.rect(2, 2, W - 4, H - 4, (214, 217, 220))
    c.rect(W / 2 - 0.3, 2, 0.6, H - 4, (150, 154, 158))                               # 문 가운데 줄
    c.text("소 화 전", W / 2, H * 0.3, _fit("소 화 전", "KR_B", 15, W - 10), "KR_B", (200, 20, 20), "center")
    c.text("HYDRANT", W / 2, H * 0.46, _fit("HYDRANT", "EN_B", 8, W - 12), "EN_B", (200, 20, 20), "center")
    c.rect(W / 2 - 4, H * 0.6, 8, 3, (70, 74, 78))                                    # 손잡이
    return c.img


@lru_cache(maxsize=None)
def hanging_sign(w: float, h: float, text: str, arrow: str, bg: str):
    H = 100.0
    W = H * w / h
    bgc = hex_rgb(bg, (20, 32, 63))
    fg = fg_on(bgc)
    c = Canvas(W, H, bgc)
    x = 16.0
    a = (arrow or "").strip()[:1]
    if a in ARROWS and a:
        cx, cy, s = x + 30, 50.0, 26.0
        d = {"←": (-1, 0), "→": (1, 0), "↑": (0, -1), "↓": (0, 1)}[a]
        p = (-d[1], d[0])
        c.polygon([(cx + d[0] * s, cy + d[1] * s), (cx + p[0] * s * 0.8, cy + p[1] * s * 0.8), (cx - p[0] * s * 0.8, cy - p[1] * s * 0.8)], fg)
        x0, x1 = sorted((cx, cx - d[0] * s)), sorted((cy, cy - d[1] * s))
        if d[0]:
            c.rect(x0[0], cy - 8, x0[1] - x0[0], 16, fg)
        else:
            c.rect(cx - 8, x1[0], 16, x1[1] - x1[0], fg)
        x += 76
    lines = [s.strip() for s in (text or "").split("/") if s.strip()][:3]
    sizes = {1: [46], 2: [38, 22], 3: [28, 18, 18]}.get(len(lines), [])
    y = 50 - sum(sizes) * 0.62
    for ln, sz in zip(lines, sizes):
        c.text(ln, x, y, _fit(ln, "KR_B", sz, W - x - 16), "KR_B", fg)
        y += sz * 1.24
    return c.img
