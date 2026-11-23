"""웹 뷰어 자료 줄이기: 다른 부재 면에 딱 붙어 완전히 가려진 면 찾기 (형상 자체는 바꾸지 않음 — 3D DXF·IFC·DAE 는 그대로).

같은 평면에서 서로 반대를 보는 두 면 중, 한 면이 다른 면 안에 완전히 들어가면(볼록 다각형 포함) 안쪽 면은 어디서도 보이지 않음.
똑같은 크기로 맞닿은 면은 둘 다 보이지 않음. 움직이는 부재·유리(투명)·다른 표시 묶음 사이의 맞닿음은 보지 않는다(호출하는 쪽이 key 로 나눔).
"""
import numpy as np

TOL_N, TOL_D, EPS = 1e-4, 5e-4, 5e-4       # 법선·평면 거리·포함 판정 허용 (m)


def hidden_faces(faces: list, keys: list) -> np.ndarray:
    """faces: 꼭짓점 목록(3·4각 볼록, 원점 기준 상대 좌표), keys: 면마다 묶음 번호(−1 = 판정하지 않음, 같은 번호끼리만 가림).
    가려진 면 = True 인 배열"""
    n = len(faces)
    out = np.zeros(n, dtype=bool)
    use = np.array([k >= 0 for k in keys])
    if n == 0 or not use.any():
        return out
    quad = np.array([(f[0], f[1], f[2], f[3] if len(f) > 3 else f[2]) for f in faces], dtype=float)      # (n, 4, 3)
    nrm = np.cross(quad[:, 2] - quad[:, 0], quad[:, 3] - quad[:, 1])                                     # 사각 = 대각선 외적
    tri = np.array([len(f) == 3 for f in faces])
    nrm[tri] = np.cross(quad[tri, 1] - quad[tri, 0], quad[tri, 2] - quad[tri, 0])
    ln = np.linalg.norm(nrm, axis=1)
    use &= ln > 1e-9
    nrm = nrm / np.maximum(ln, 1e-12)[:, None]
    cen = quad[:, :3].mean(axis=1)
    flat = np.abs(np.einsum("nkj,nj->nk", quad - quad[:, :1], nrm)).max(axis=1) < TOL_D                  # 평면인 면만
    use &= flat
    big = np.abs(nrm).argmax(axis=1)
    pos = nrm[np.arange(n), big] > 0                                                                      # 가장 큰 성분이 + 인 면 / − 인 면
    can = np.where(pos[:, None], nrm, -nrm)
    d = np.einsum("nj,nj->n", can, cen)
    key = np.concatenate([np.asarray(keys)[:, None], np.round(can / (TOL_N * 10)).astype(np.int64),
                          np.round(d / TOL_D).astype(np.int64)[:, None]], axis=1)
    idx = np.nonzero(use)[0]
    order = idx[np.lexsort(key[idx].T[::-1])]
    k = key[order]
    start = np.concatenate([[0], np.nonzero(np.any(k[1:] != k[:-1], axis=1))[0] + 1, [len(order)]])
    gid = np.repeat(np.arange(len(start) - 1), np.diff(start))
    np_, nm = np.bincount(gid, pos[order], len(start) - 1), np.bincount(gid, ~pos[order], len(start) - 1)
    keep = (np_ > 0) & (nm > 0)                                                                            # 양쪽을 보는 면이 다 있는 평면만
    sel = keep[gid]
    order, gid = order[sel], gid[sel]
    if len(order) == 0:
        return out
    # 평면 좌표 (묶음마다 같은 축: 묶음 첫 면의 법선으로)
    first = np.nonzero(np.concatenate([[True], gid[1:] != gid[:-1]]))[0]
    rep = can[order[first]][np.cumsum(np.concatenate([[True], gid[1:] != gid[:-1]])) - 1]
    t = np.where(np.abs(rep[:, :1]) < 0.9, [[1.0, 0.0, 0.0]], [[0.0, 1.0, 0.0]])
    e1 = np.cross(rep, t)
    e1 /= np.linalg.norm(e1, axis=1)[:, None]
    e2 = np.cross(rep, e1)
    q = np.stack([np.einsum("nkj,nj->nk", quad[order], e1), np.einsum("nkj,nj->nk", quad[order], e2)], axis=2)   # (m, 4, 2)
    lo, hi = q.min(axis=1), q.max(axis=1)
    side = pos[order]
    m = len(order)
    hid = np.zeros(m, dtype=bool)
    ends = np.concatenate([first[1:], [m]])
    size = ends - first
    end_of = np.repeat(ends, size)
    # 묶음 안 쌍을 '거리'(정렬 순서 차이)별로 한꺼번에: 묶음 안을 왼쪽 끝(lo x) 순으로 정렬해 겹치지 않는 먼 쌍은 건너뜀
    o2 = np.lexsort((lo[:, 0], gid))
    q, lo, hi, side, tr = q[o2], lo[o2], hi[o2], side[o2], tri[order][o2]
    alive = np.arange(m)
    step = 1
    while len(alive):
        j = alive + step
        ok = j < end_of[alive]
        i_, j_ = alive[ok], j[ok]
        near = lo[j_, 0] <= hi[i_, 0] + EPS                                                                # 정렬돼 있어 이보다 먼 것은 더 겹치지 않음
        i_, j_ = i_[near], j_[near]
        alive = i_
        pair = (side[i_] != side[j_]) & (lo[j_, 1] <= hi[i_, 1]) & (lo[i_, 1] <= hi[j_, 1])
        a, b = i_[pair], j_[pair]
        for x, y in ((a, b), (b, a)):                                                                      # x 가 y 안에
            c = ~hid[x] & np.all(lo[y] <= lo[x] + EPS, axis=1) & np.all(hi[y] >= hi[x] - EPS, axis=1)
            if c.any():
                xx, yy = x[c], y[c]
                hid[xx[_inside(q[xx], q[yy], tr[yy])]] = True
        step += 1
    out[order[o2[hid]]] = True
    return out


def _inside(pts, poly, tri) -> np.ndarray:
    """쌍마다 점 4개가 볼록 다각형(3·4각) 안에 있는가 (EPS 여유)"""
    e = np.roll(poly, -1, axis=1) - poly                                                                   # 삼각형은 넷째 = 셋째 (변 길이 0)
    nx = np.roll(poly, -1, axis=1)
    area = np.sum(poly[:, :, 0] * nx[:, :, 1] - nx[:, :, 0] * poly[:, :, 1], axis=1)
    s = np.where(area > 0, 1.0, -1.0)
    ln = np.hypot(e[:, :, 0], e[:, :, 1])
    dx = pts[:, :, None, 0] - poly[:, None, :, 0]
    dy = pts[:, :, None, 1] - poly[:, None, :, 1]
    d = s[:, None, None] * (e[:, None, :, 0] * dy - e[:, None, :, 1] * dx)
    return np.all((d >= -EPS * ln[:, None, :]) | (ln[:, None, :] < 1e-9), axis=(1, 2))
