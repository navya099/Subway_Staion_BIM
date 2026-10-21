import math


class CommonHelper:
    # --- [공통 헬퍼 메서드] ---
    @staticmethod
    def draw_polygons_with_hatch(msp, polygons, poly_layer, hatch_layer):
        for poly_pts in polygons:
            msp.add_lwpolyline(poly_pts, close=True, dxfattribs={'layer': poly_layer})
            hatch = msp.add_hatch(color=8, dxfattribs={'layer': hatch_layer})
            hatch.set_pattern_fill('ANSI31', scale=0.5)
            path = hatch.paths.add_polyline_path(poly_pts)
            path.closed = True

    @staticmethod
    def prism_corners(pos_x, pos_y, pos_z, length, width, rise):
        """중심 기준 (s, t, 중심 s 하단 z) 부재 → (s0, s1, t0, t1, z(s0), z(s1)). 벽체·슬래브 공통"""
        s0, t0 = pos_x - length / 2.0, pos_y - width / 2.0
        z0 = pos_z - rise / 2.0
        return s0, s0 + length, t0, t0 + width, z0, z0 + rise

    @staticmethod
    def cut_by_s(sta, s0, s1, length, tol=1e-9):
        """측점 sta 의 횡단면이 [s0, s1) 구간 부재를 자르는가 (마지막 부재는 끝점 포함)"""
        return (s0 - tol <= sta < s1 - tol) or (s1 >= length - tol and s0 - tol <= sta <= s1 + tol)

    @staticmethod
    def cut_by_t(t0, t1, t_cut=0.0, tol=1e-9):
        """종단면(t = t_cut)이 [t0, t1) 구간 부재를 자르는가"""
        return t0 - tol <= t_cut < t1 - tol

    @staticmethod
    def circle_polygon(cs, ct, r, n=24):
        return [(cs + r * math.cos(2 * math.pi * i / n), ct + r * math.sin(2 * math.pi * i / n)) for i in range(n)]

    @staticmethod
    def create_prism_faces_global(poly, z_bot, z_top, world):
        """로컬 (s,t) 다각형 단면을 z_bot~z_top으로 압출한 3DFACE 목록 (사각형은 6면)
        world: (s, t) → WCS (x, y) 변환 함수 (StationProjectConfig.to_world)"""
        g = [world(s, t) for s, t in poly]
        bot = [(x, y, z_bot) for x, y in g]
        top = [(x, y, z_top) for x, y in g]
        n = len(g)
        faces = [(bot[i], bot[(i + 1) % n], top[(i + 1) % n], top[i]) for i in range(n)]
        for ring in (bot, top):
            if n == 4:
                faces.append(tuple(ring))
            else:
                c = (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n, ring[0][2])
                faces.extend((c, ring[i], ring[(i + 1) % n], ring[(i + 1) % n]) for i in range(n))
        return faces

    @staticmethod
    def create_sloped_faces(x1, x2, y1, y2, zb1, zb2, zt1, zt2):
        p = [(x1, y1, zb1), (x2, y1, zb2), (x2, y2, zb2), (x1, y2, zb1),
             (x1, y1, zt1), (x2, y1, zt2), (x2, y2, zt2), (x1, y2, zt1)]
        return [(p[0], p[1], p[2], p[3]), (p[4], p[7], p[6], p[5]),
                (p[0], p[4], p[5], p[1]), (p[1], p[5], p[6], p[2]),
                (p[2], p[6], p[7], p[3]), (p[3], p[7], p[4], p[0])]

    @staticmethod
    def create_flat_faces(x1, x2, y1, y2, z1, z2):
        p = [(x1, y1, z1), (x2, y1, z1), (x2, y2, z1), (x1, y2, z1),
             (x1, y1, z2), (x2, y1, z2), (x2, y2, z2), (x1, y2, z2)]
        return [(p[0], p[1], p[2], p[3]), (p[4], p[7], p[6], p[5]),
                (p[0], p[4], p[5], p[1]), (p[1], p[5], p[6], p[2]),
                (p[2], p[6], p[7], p[3]), (p[3], p[7], p[4], p[0])]

    @staticmethod
    def create_sloped_box_faces_global(s1, s2, t1, t2, zb1, zb2, zt1, zt2, world):
        """
        s: 정거장 로컬 길이 (0 ~ L)
        t: 정거장 로컬 폭 (-W/2 ~ +W/2)
        z: 표고
        world: (s, t) → WCS (x, y) 변환 함수 (StationProjectConfig.to_world)
        """
        # 1. 로컬 8개 꼭짓점
        p_local = [
            (s1, t1, zb1), (s2, t1, zb2), (s2, t2, zb2), (s1, t2, zb1),
            (s1, t1, zt1), (s2, t1, zt2), (s2, t2, zt2), (s1, t2, zt1)
        ]

        # 2. 절대 좌표계(WCS)로 변환 (선형 위 측점 s 의 위치/방향을 따름)
        p_global = []
        for s, t, z in p_local:
            xg, yg = world(s, t)
            p_global.append((xg, yg, z))

        # 3. 변환된 3D Face 6개 면 반환
        return [
            (p_global[0], p_global[1], p_global[2], p_global[3]),
            (p_global[4], p_global[7], p_global[6], p_global[5]),
            (p_global[0], p_global[4], p_global[5], p_global[1]),
            (p_global[1], p_global[5], p_global[6], p_global[2]),
            (p_global[2], p_global[6], p_global[7], p_global[3]),
            (p_global[3], p_global[7], p_global[4], p_global[0])
        ]