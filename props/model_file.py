"""외부 3D 모델 파일 읽기 (GLB · glTF · OBJ+MTL) → 재질마다 삼각형 묶음 (numpy, Pillow 만 사용).

좌표는 파일 그대로(단위·위쪽 축은 model_spec 에서 바꿈), 텍스처 좌표는 왼쪽 아래 원점. 애니메이션·스킨·점·선은 무시한다.
"""
import base64
import io
import json
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import numpy as np

SUFFIXES = (".glb", ".gltf", ".obj")
MAX_TRIANGLES = 1_000_000
_DTYPE = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_UNSUPPORTED = {"KHR_draco_mesh_compression": "Draco 압축", "EXT_meshopt_compression": "meshopt 압축", "KHR_texture_basisu": "Basis 텍스처"}


class ModelError(ValueError):
    """사용자에게 보일 모델 파일 오류"""


@dataclass
class MeshPart:
    """재질 하나의 삼각형: pos (N, 3), idx (M, 3), uv (N, 2) 또는 None, 색(sRGB 0~1)·불투명도·이미지(PIL)·cut = 투명한 픽셀을 잘라 냄"""
    name: str
    pos: np.ndarray
    idx: np.ndarray
    uv: object = None
    color: tuple = (0.8, 0.8, 0.8)
    alpha: float = 1.0
    image: object = None
    cut: bool = False


_cache = {}


def load_model(path) -> list:
    """모델 파일 → [MeshPart]. 읽지 못하면 ValueError (같은 파일은 다시 읽지 않음)"""
    p = Path(path)
    if p.suffix.lower() not in SUFFIXES:
        raise ModelError(f"지원하지 않는 모델 파일 형식입니다 ({p.suffix or p.name}) — GLB·glTF·OBJ")
    try:
        st = p.stat()
        key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
    except OSError:
        raise ModelError(f"모델 파일이 없습니다 ({p})") from None
    if key not in _cache:
        try:
            parts = _load_obj(p) if p.suffix.lower() == ".obj" else _load_gltf(p)
        except ModelError:
            raise
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, struct.error, OSError) as e:
            raise ModelError(f"모델 파일 형식이 올바르지 않습니다 ({p.name}: {type(e).__name__} {e})") from None
        parts = [q for q in parts if len(q.idx)]
        if not parts:
            raise ModelError(f"모델 파일에 면이 없습니다 ({p.name})")
        for q in parts:
            if q.idx.min() < 0 or q.idx.max() >= len(q.pos) or not np.isfinite(q.pos).all():
                raise ModelError(f"모델 파일의 면·좌표가 올바르지 않습니다 ({p.name})")
        n = sum(len(q.idx) for q in parts)
        if n > MAX_TRIANGLES:
            raise ModelError(f"모델의 면이 너무 많습니다 ({p.name}: {n:,}개, 한도 {MAX_TRIANGLES:,}개)")
        for k in [k for k in _cache if k[0] == key[0]]:              # 옛 내용은 버림
            del _cache[k]
        _cache[key] = parts
    return _cache[key]


def _image(data: bytes):
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        return im
    except Exception:                                                  # 읽지 못하는 이미지 = 색만
        return None


def _sibling(base: Path, uri: str):
    """모델 파일 옆의 파일 (없으면 같은 폴더의 같은 이름, 그래도 없으면 None). 인터넷 주소는 읽지 않음"""
    name = unquote(uri).replace("\\", "/")
    if "://" in name:
        return None
    for q in (base.parent / name, base.parent / os.path.basename(name)):
        if q.is_file():
            return q
    return None


def _srgb(c) -> tuple:
    return tuple(min(1.0, max(0.0, 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055)) for x in (max(0.0, float(v)) for v in c))


# ====================================================================== glTF
def _load_gltf(p: Path) -> list:
    raw = p.read_bytes()
    blob = None
    if raw[:4] == b"glTF":
        if struct.unpack_from("<I", raw, 4)[0] != 2:
            raise ModelError(f"glTF 2.0 이 아닙니다 ({p.name})")
        pos, js = 12, None
        while pos + 8 <= len(raw):
            n, kind = struct.unpack_from("<II", raw, pos)
            chunk = raw[pos + 8:pos + 8 + n]
            if kind == 0x4E4F534A:
                js = chunk
            elif kind == 0x004E4942 and blob is None:
                blob = chunk
            pos += 8 + n
        if js is None:
            raise ModelError(f"GLB 파일이 잘못되었습니다 ({p.name})")
    else:
        js = raw
    try:
        g = json.loads(js.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ModelError(f"glTF 파일을 읽을 수 없습니다 ({p.name})") from None
    for e in g.get("extensionsRequired", []):
        if e in _UNSUPPORTED:
            raise ModelError(f"{_UNSUPPORTED[e]}을(를) 쓴 모델은 지원하지 않습니다 ({p.name}) — 압축 없이 다시 저장하세요")
    buffers = {}

    def buffer(i):
        if i not in buffers:
            uri = g["buffers"][i].get("uri")
            if uri is None:
                buffers[i] = blob or b""
            elif uri.startswith("data:"):
                buffers[i] = base64.b64decode(uri.split(",", 1)[1])
            else:
                q = _sibling(p, uri)
                if q is None:
                    raise ModelError(f"glTF 자료 파일이 없습니다 ({uri})")
                buffers[i] = q.read_bytes()
        return buffers[i]

    def view(i) -> bytes:
        v = g["bufferViews"][i]
        o = v.get("byteOffset", 0)
        return buffer(v["buffer"])[o:o + v["byteLength"]]

    def accessor(i) -> np.ndarray:
        a = g["accessors"][i]
        if "sparse" in a:
            raise ModelError(f"sparse 자료를 쓴 모델은 지원하지 않습니다 ({p.name})")
        dt, n, k = np.dtype(_DTYPE[a["componentType"]]).newbyteorder("<"), a["count"], _COUNT[a["type"]]
        if "bufferView" not in a:
            return np.zeros((n, k))
        data, o = view(a["bufferView"]), a.get("byteOffset", 0)
        stride = g["bufferViews"][a["bufferView"]].get("byteStride") or dt.itemsize * k
        out = np.ndarray((n, k), dt, data, o, (stride, dt.itemsize)) if n else np.zeros((0, k))
        if a.get("normalized"):
            return np.maximum(out.astype(float) / np.iinfo(out.dtype).max, -1.0)
        return out
    images = {}

    def texture(ref):
        """텍스처 참조 → PIL 이미지 또는 None"""
        if ref is None:
            return None
        src = g["textures"][ref["index"]].get("source")
        if src is None:
            return None
        if src not in images:
            im = g["images"][src]
            uri = im.get("uri")
            if uri is None:
                images[src] = _image(view(im["bufferView"]))
            elif uri.startswith("data:"):
                images[src] = _image(base64.b64decode(uri.split(",", 1)[1]))
            else:
                q = _sibling(p, uri)
                images[src] = _image(q.read_bytes()) if q is not None else None
        return images[src]

    def material(i) -> dict:
        if i is None:
            return {"name": "기본", "color": (0.8, 0.8, 0.8), "alpha": 1.0, "image": None, "cut": False, "set": 0}
        m = g["materials"][i]
        pbr, old = m.get("pbrMetallicRoughness", {}), m.get("extensions", {}).get("KHR_materials_pbrSpecularGlossiness")
        f, ref = pbr.get("baseColorFactor", [1, 1, 1, 1]), pbr.get("baseColorTexture")
        if old is not None and ref is None:
            f, ref = old.get("diffuseFactor", f), old.get("diffuseTexture")
        mode = m.get("alphaMode", "OPAQUE")
        img = texture(ref)
        return {"name": m.get("name") or f"재질 {i + 1}", "color": _srgb(f[:3]), "alpha": float(f[3]) if mode == "BLEND" and f[3] > 0.02 else 1.0,
                "image": img, "cut": img is not None and mode != "OPAQUE", "set": (ref or {}).get("texCoord", 0)}
    acc = {}                                                        # 재질 번호 → [(pos, uv, idx)]

    def add(mesh, M):
        for pr in g["meshes"][mesh]["primitives"]:
            mode = pr.get("mode", 4)
            if mode not in (4, 5, 6) or "POSITION" not in pr["attributes"]:
                continue
            pos = accessor(pr["attributes"]["POSITION"]).astype(float)
            ix = accessor(pr["indices"]).ravel().astype(np.int64) if "indices" in pr else np.arange(len(pos))
            if mode == 5:
                ix = np.array([(ix[j], ix[j + 1], ix[j + 2]) if j % 2 == 0 else (ix[j + 1], ix[j], ix[j + 2]) for j in range(len(ix) - 2)]).reshape(-1, 3)
            elif mode == 6:
                ix = np.array([(ix[0], ix[j], ix[j + 1]) for j in range(1, len(ix) - 1)]).reshape(-1, 3)
            else:
                ix = ix[:len(ix) // 3 * 3].reshape(-1, 3)
            if np.linalg.det(M[:3, :3]) < 0:                        # 뒤집힌 변환 = 면 방향도 뒤집음
                ix = ix[:, ::-1]
            mi = pr.get("material")
            key = f"TEXCOORD_{material(mi)['set']}"
            uv = None
            if key in pr["attributes"]:
                uv = accessor(pr["attributes"][key]).astype(float).copy()
                uv[:, 1] = 1.0 - uv[:, 1]
            acc.setdefault(mi, []).append((pos @ M[:3, :3].T + M[:3, 3], uv, ix))

    def walk(i, M, depth=0):
        if depth > 200:
            raise ModelError(f"모델의 노드가 너무 깊습니다 ({p.name})")
        n = g["nodes"][i]
        M = M @ _node_matrix(n)
        if "mesh" in n:
            add(n["mesh"], M)
        for c in n.get("children", []):
            walk(c, M, depth + 1)
    if g.get("scenes"):
        roots = g["scenes"][g.get("scene", 0)].get("nodes", [])
    else:
        kids = {c for n in g.get("nodes", []) for c in n.get("children", [])}
        roots = [i for i in range(len(g.get("nodes", []))) if i not in kids]
    for r in roots:
        walk(r, np.eye(4))
    out = []
    for mi, items in acc.items():
        m = material(mi)
        has_uv = m["image"] is not None and all(uv is not None for _, uv, _ in items)
        off = np.cumsum([0] + [len(pos) for pos, _, _ in items])
        out.append(MeshPart(m["name"], np.concatenate([x[0] for x in items]), np.concatenate([x[2] + o for x, o in zip(items, off)]),
                            np.concatenate([x[1] for x in items]) if has_uv else None, m["color"], m["alpha"], m["image"] if has_uv else None,
                            m["cut"] and has_uv))
    return out


def _node_matrix(n) -> np.ndarray:
    if "matrix" in n:
        return np.array(n["matrix"], dtype=float).reshape(4, 4).T
    M = np.eye(4)
    x, y, z, w = n.get("rotation", (0, 0, 0, 1))
    ln = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / ln, y / ln, z / ln, w / ln
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M[:3, :3] = R * np.array(n.get("scale", (1, 1, 1)), dtype=float)
    M[:3, 3] = n.get("translation", (0, 0, 0))
    return M


# ====================================================================== OBJ
def _text(p: Path) -> str:
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


def _load_mtl(p: Path) -> dict:
    out, cur = {}, None
    for line in _text(p).splitlines():
        w = line.split()
        if not w or w[0].startswith("#"):
            continue
        k = w[0].lower()
        if k == "newmtl":
            cur = out.setdefault(line.split(None, 1)[1].strip() if len(w) > 1 else "", {"color": (0.8, 0.8, 0.8), "alpha": 1.0, "image": None})
        elif cur is None:
            continue
        elif k == "kd" and len(w) >= 4:
            cur["color"] = tuple(min(1.0, max(0.0, float(x))) for x in w[1:4])
        elif k == "d" and len(w) >= 2:
            cur["alpha"] = float(w[-1])
        elif k == "tr" and len(w) >= 2:
            cur["alpha"] = 1.0 - float(w[-1])
        elif k == "map_kd" and len(w) >= 2:
            rest = line.split(None, 1)[1].strip()
            q = _sibling(p, rest) or _sibling(p, w[-1])             # 옵션(-s 등)이 앞에 있으면 마지막 낱말
            cur["image"] = _image(q.read_bytes()) if q is not None else None
    for m in out.values():
        if not 0.02 < m["alpha"] <= 1.0:                            # 0 으로 잘못 저장된 파일이 흔함
            m["alpha"] = 1.0
    return out


def _load_obj(p: Path) -> list:
    v, vt, mats, faces, cur = [], [], {}, {}, ""
    for line in _text(p).replace("\\\n", " ").splitlines():
        w = line.split()
        if not w:
            continue
        k = w[0]
        if k == "v":
            v.append((float(w[1]), float(w[2]), float(w[3])))
        elif k == "vt":
            vt.append((float(w[1]), float(w[2]) if len(w) > 2 else 0.0))
        elif k == "f":
            ids = []
            for q in w[1:]:
                a = q.split("/")
                i = int(a[0])
                j = int(a[1]) if len(a) > 1 and a[1] else 0
                ids.append((i - 1 if i > 0 else len(v) + i, (j - 1 if j > 0 else len(vt) + j) if j else -1))
            fs = faces.setdefault(cur, [])
            fs.extend((ids[0], ids[m], ids[m + 1]) for m in range(1, len(ids) - 1))
        elif k == "usemtl":
            cur = line.split(None, 1)[1].strip() if len(w) > 1 else ""
        elif k == "mtllib" and len(w) > 1:
            q = _sibling(p, line.split(None, 1)[1].strip())
            if q is not None:
                mats.update(_load_mtl(q))
    out = []
    for name, fs in faces.items():
        m = mats.get(name, {"color": (0.8, 0.8, 0.8), "alpha": 1.0, "image": None})
        use = m["image"] is not None and all(c[1] >= 0 for f in fs for c in f)
        index, pos, uv, idx = {}, [], [], []
        for f in fs:
            tri = []
            for i, j in f:
                key = (i, j if use else -1)
                if key not in index:
                    if not 0 <= i < len(v):
                        raise ModelError(f"OBJ 파일의 면 번호가 잘못되었습니다 ({p.name})")
                    index[key] = len(pos)
                    pos.append(v[i])
                    if use:
                        uv.append(vt[j])
                tri.append(index[key])
            idx.append(tri)
        im = m["image"] if use else None
        out.append(MeshPart(name or "기본", np.array(pos, dtype=float).reshape(-1, 3), np.array(idx, dtype=np.int64).reshape(-1, 3),
                            np.array(uv, dtype=float) if use else None, m["color"], m["alpha"], im,
                            im is not None and (im.mode in ("RGBA", "LA") or "transparency" in im.info)))
    return out
