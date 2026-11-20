"""3D 웹 뷰어 (three.js HTML) 테스트: 자료가 3D DXF 의 3DFACE 와 일치, 압축 자료 풀기, 출력 옵션"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import base64
import gzip
import json
import re

import numpy as np
import pytest

from config.output_config import OutputOptions
from engine.bim_engine import BIMEngine
from engine.cad_engine import StationCADEngine
from exporter.web_viewer import build_web_data
from test_patch import make_cfg


def _cfg():
    cfg = make_cfg()
    cfg.finish_settings.enabled = True
    return cfg


def test_data_matches_3d_faces():
    eng = StationCADEngine(_cfg())
    data, packed = build_web_data(eng)
    buf = gzip.decompress(packed)
    faces = [e for e in eng.build_3d_doc().modelspace().query("3DFACE") if e.dxf.layer != "FIN_FRAME"]
    n_tri = sum(1 if tuple(e.dxf.vtx3) == tuple(e.dxf.vtx2) else 2 for e in faces)
    assert data["triangles"] == n_tri == sum(c["nt"] for c in data["chunks"])
    L = data["length"]
    for c in data["chunks"]:
        pos = np.frombuffer(buf, np.float32, c["nv"] * 3, c["pos"]).reshape(-1, 3)
        sh = np.frombuffer(buf, np.float32, c["nv"] * 2, c["sh"]).reshape(-1, 2)
        idx = np.frombuffer(buf, np.uint32, c["nt"] * 3, c["idx"])
        el = np.frombuffer(buf, np.uint32, c["nt"], c["elem"])
        assert idx.max() < c["nv"] and el.max() < len(data["elements"])
        assert np.all(np.abs(pos) < 1e4)                                   # 원점 기준 상대 좌표
        assert sh[:, 0].min() > -50 and sh[:, 0].max() < L + 50           # s
        if c["layer"] == "STRUCT_SLAB":
            assert sh[:, 1].min() == pytest.approx(-eng.cfg.station.floor_t, abs=1e-3)   # 바닥 슬래브 하면 = FL − 두께
    names = {e["name"] for e in data["elements"]}
    assert any(n.startswith("WALL_") for n in names) and any(n.startswith("FIN_") for n in names)
    assert all(not n.startswith("(") for n in names)                       # 모든 면이 부재 이름을 앎
    assert [f["name"] for f in data["floors"]] == ["B3F", "B2F", "B1F"]


def test_html_is_self_contained(tmp_path):
    eng = StationCADEngine(_cfg())
    path = eng.generate_web(tmp_path / "v.html")
    html = open(path, encoding="utf-8").read()
    assert "/*__THREE__*/" not in html and "/*__DATA__*/" not in html and "/*__BLOB__*/" not in html
    assert "Three.js Authors" in html and "http://" not in html.split("<script>", 1)[0]
    data = json.loads(re.search(r"const DATA = (\{.*?\});\nconst BLOB", html, re.S).group(1))
    blob = re.search(r'const BLOB = "([A-Za-z0-9+/=]+)";', html).group(1)
    assert len(gzip.decompress(base64.b64decode(blob))) > 0
    assert data["triangles"] == eng.web_result.triangles
    assert html.count("</script>") == html.count("<script>")              # 넣은 자료가 script 를 끊지 않음


def test_output_option(tmp_path):
    notes = []
    paths = BIMEngine.build(_cfg(), tmp_path, OutputOptions(dxf3d=False, ifc=False, plan=False, profile=False,
                                                            section=False, web=True), notes)
    assert [os.path.basename(p) for p in paths] == ["정거장3d뷰어.html"]
    assert any("3D 웹 뷰어" in n for n in notes)
    from gui.print_draft import PrintDraft, preview
    d = PrintDraft(dxf3d=False, ifc=False, plan=False, profile=False, section=False, web=True)
    assert d.to_options(5.0).web and "3D 웹 뷰어" in preview(d, None, None, None)
