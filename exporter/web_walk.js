// 웹 뷰어 걷기 충돌 (화면·three.js 비의존). 사람 = 연직 원기둥(반지름 R, 키 H), 삼각형 모음과 부딪힘을 검사한다.
// - 벽: 발 + STEP(오를 수 있는 단 높이) ~ 발 + BODY 높이의 삼각형을 그 높이 구간으로 잘라 평면에서 가장 가까운 점이 R 보다 가까우면 밀어냄
// - 바닥: 발 + STEP 아래 가장 높은 면 (가운데 + 둘레 4점). STEP 보다 낮아지면 중력으로 떨어지고, 아래에 바닥이 없으면 못 감
// - 머리: 발 + 1.0 위 첫 면까지의 높이가 H 보다 낮으면 막고 state.head = { clear, tag }
// query(x0, y0, z0, x1, y1, z1, cb) : 상자에 걸칠 수 있는 삼각형마다 cb(ax, ay, az, bx, by, bz, cx, cy, cz, tag)
function WalkCore(query) {
  "use strict";
  const R = 0.25, H = 1.7, STEP = 0.3, BODY = 1.45, G = 9.8, JUMP = 3.4, FOOT = 0.12, SUB = 0.1, BIG = 1e4;

  // 연직선 (x, y) 이 만나는 면 높이들 [[z, tag]] (z0 ~ z1)
  function hits(x, y, z0, z1) {
    const out = [];
    query(x, y, z0, x, y, z1, (ax, ay, az, bx, by, bz, cx, cy, cz, tag) => {
      const d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
      if (Math.abs(d) < 1e-9) return;                       // 연직 면
      const u = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / d, v = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / d, w = 1 - u - v;
      if (u < -1e-7 || v < -1e-7 || w < -1e-7) return;
      const z = u * az + v * bz + w * cz;
      if (z >= z0 && z <= z1) out.push([z, tag]);
    });
    return out;
  }
  const below = (x, y, top) => hits(x, y, top - BIG, top).reduce((m, h) => (m === null || h[0] > m[0] ? h : m), null);
  const above = (x, y, z) => hits(x, y, z, z + BIG).reduce((m, h) => (m === null || h[0] < m[0] ? h : m), null);

  function ground(x, y, top) {                              // 발밑: 가운데 + 둘레 4점 중 가장 높은 면 (틈에 빠지지 않게)
    let best = below(x, y, top);
    for (const [dx, dy] of [[FOOT, 0], [-FOOT, 0], [0, FOOT], [0, -FOOT]]) {
      const h = below(x + dx, y + dy, top);
      if (h && (best === null || h[0] > best[0])) best = h;
    }
    return best;
  }

  const A = new Float64Array(24), B = new Float64Array(24);
  function clipZ(src, n, dst, z, keepAbove) {               // 다각형(xyz 나열)을 높이 z 위/아래로 자름
    let m = 0;
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n, z0 = src[i * 3 + 2], z1 = src[j * 3 + 2];
      const in0 = keepAbove ? z0 >= z : z0 <= z, in1 = keepAbove ? z1 >= z : z1 <= z;
      if (in0) { dst[m * 3] = src[i * 3]; dst[m * 3 + 1] = src[i * 3 + 1]; dst[m * 3 + 2] = z0; m++; }
      if (in0 !== in1) {
        const t = (z - z0) / (z1 - z0);
        dst[m * 3] = src[i * 3] + (src[j * 3] - src[i * 3]) * t; dst[m * 3 + 1] = src[i * 3 + 1] + (src[j * 3 + 1] - src[i * 3 + 1]) * t; dst[m * 3 + 2] = z; m++;
      }
    }
    return m;
  }

  // 원기둥 [zl, zh] 에 가장 깊이 파고든 면: { d(중심까지 거리), px, py(가장 가까운 점), tag } 또는 null
  function deepest(x, y, zl, zh) {
    let best = null;
    query(x - R, y - R, zl, x + R, y + R, zh, (ax, ay, az, bx, by, bz, cx, cy, cz, tag) => {
      if (Math.max(az, bz, cz) <= zl || Math.min(az, bz, cz) >= zh) return;
      A[0] = ax; A[1] = ay; A[2] = az; A[3] = bx; A[4] = by; A[5] = bz; A[6] = cx; A[7] = cy; A[8] = cz;
      let n = clipZ(A, 3, B, zl, true);
      if (n) n = clipZ(B, n, A, zh, false);
      for (let i = 0; i < n; i++) {
        const j = (i + 1) % n, x0 = A[i * 3], y0 = A[i * 3 + 1], ex = A[j * 3] - x0, ey = A[j * 3 + 1] - y0, l2 = ex * ex + ey * ey;
        const t = l2 < 1e-14 ? 0 : Math.max(0, Math.min(1, ((x - x0) * ex + (y - y0) * ey) / l2));
        const px = x0 + ex * t, py = y0 + ey * t, d = Math.hypot(x - px, y - py);
        if (d < R && (best === null || d < best.d)) best = { d, px, py, tag };
      }
    });
    return best;
  }
  function pushOut(x, y, zl, zh, bx, by) {                  // 밀어낸 위치 (모서리는 여러 번). (bx, by) = 온 쪽 (정확히 면 위일 때 방향)
    let stuck = true, tag = null;
    for (let k = 0; k < 6; k++) {
      const c = deepest(x, y, zl, zh);
      if (!c || c.d > R - 1e-4) { stuck = false; break; }
      tag = c.tag;
      let nx = x - c.px, ny = y - c.py, n = Math.hypot(nx, ny);
      if (n < 1e-6) { nx = bx - c.px; ny = by - c.py; n = Math.hypot(nx, ny); }
      if (n < 1e-9) break;
      x = c.px + nx / n * R; y = c.py + ny / n * R;
    }
    return { x, y, stuck, tag };
  }

  // 머리 위 여유: 발 높이 foot 에서 (x, y) 와 앞쪽(dx, dy 방향 0.15) 중 낮은 것
  function clearance(x, y, foot, dx, dy) {
    const l = Math.hypot(dx, dy) || 1;
    let best = null;
    for (const k of [0, 0.15]) {
      const h = above(x + dx / l * k, y + dy / l * k, foot + 1.0);
      if (h && (best === null || h[0] < best[0])) best = h;
    }
    return best ? { clear: best[0] - foot, tag: best[1] } : { clear: Infinity, tag: null };
  }

  // 한 걸음: st = { x, y, foot, vz, grounded, head, blocked }, (dx, dy) 가려는 거리, opt.ride = 움직이는 바닥(에스컬레이터) 위라 높이는 밖에서 정함
  function move(st, dx, dy, dt, opt) {
    const ride = opt && opt.ride;
    st.head = null; st.blocked = null;
    const dist = Math.hypot(dx, dy), n = Math.max(1, Math.ceil(dist / SUB));
    for (let k = 0; k < n; k++) {                           // 서 있어도 한 번: 움직이는 문에 밀림
      const on = st.grounded || ride, zl = st.foot + (on ? STEP : 0.1), zh = st.foot + BODY;
      const tx = st.x + dx / n, ty = st.y + dy / n;
      const p = pushOut(tx, ty, zl, zh, st.x, st.y);
      if (p.tag !== null) st.blocked = p.tag;
      if (p.stuck && deepest(st.x, st.y, zl, zh) === null) break;                      // 좁아서 못 들어감
      if (Math.hypot(p.x - tx, p.y - ty) > 2 * SUB + R) break;                         // 멀리 튕기지 않음
      const g = ground(p.x, p.y, st.foot + (on ? STEP : 0.05));
      if (!g && !ride) break;                                                          // 아래에 바닥이 전혀 없음
      const foot = on && !ride && st.foot - g[0] <= STEP ? g[0] : st.foot;
      const c = clearance(p.x, p.y, foot, dx, dy);
      if (dist > 1e-9 && c.clear < H - 1e-6 && c.clear < clearance(st.x, st.y, st.foot, 0, 0).clear + 1e-6) { st.head = c; break; }
      st.x = p.x; st.y = p.y; st.foot = foot;
    }
    if (ride) { st.grounded = true; st.vz = 0; return st; }
    const g = ground(st.x, st.y, st.foot + (st.grounded ? STEP : 0.05));
    if (st.grounded) {
      if (g && st.foot - g[0] <= STEP && st.vz <= 0) { st.foot = g[0]; st.vz = 0; return st; }
      st.grounded = false; st.vz = Math.max(st.vz, 0);
    }
    if (!g) { st.vz = 0; return st; }                       // 바닥이 없으면 그대로
    st.vz = Math.max(-25, st.vz - G * dt);
    let z = st.foot + st.vz * dt;
    if (st.vz > 0) {
      const h = above(st.x, st.y, st.foot + 1.0);
      if (h && z + H > h[0]) { z = Math.max(st.foot, h[0] - H); st.vz = 0; }
    }
    if (z <= g[0]) { z = g[0]; st.vz = 0; st.grounded = true; }
    st.foot = z;
    return st;
  }
  function jump(st) { if (st.grounded) { st.vz = JUMP; st.grounded = false; } }

  // (x, y) 에 설 수 있는 바닥 높이들 (바로 위부터 키까지 비어 있음 — 슬래브 하면·마감 속 면 제외, 몸이 벽에 걸리지 않음), skip(tag) 이면 제외
  function stands(x, y, z0, z1, skip) {
    const out = [];
    for (const [z, tag] of hits(x, y, z0, z1)) {
      const h = above(x, y, z + 1e-3);
      if (out.some((o) => Math.abs(o[0] - z) < 1e-4) || (skip && skip(tag)) || (h && h[0] - z < H - 1e-6)) continue;
      if (deepest(x, y, z + STEP, z + BODY) === null) out.push([z, tag]);
    }
    return out;
  }
  return { R, H, STEP, hits, ground, above, below, deepest, pushOut, clearance, move, jump, stands };
}
if (typeof module !== "undefined") module.exports = WalkCore;
