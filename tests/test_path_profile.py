"""통로 경로 종단 (경로를 따라 펼친 종단: 출구통로 + 끝 출입구) — 미리보기 종단 축 '통로 EX1 경로', 출력 '통로 종단면도'"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import pytest

from engine.cad_engine import StationCADEngine
from engine.path_profile import parse_path_axis, passage_profile_items, path_axis_choices, profile_bounds
from test_entrances import bent_passage, cfg_with


def _eng(**kw):
    return StationCADEngine(cfg_with(kw or {}, passages=[bent_passage()]))


def test_developed_profile_cuts_passage_and_entrance():
    eng = _eng()
    lay = eng.cfg.passage_layouts()[0]
    ent = eng.entrances.entrances[0]
    items = passage_profile_items(eng, "EX1", 0.0)
    L = lay.plan_length
    # 통로 바닥 슬래브: 구간마다 잘린 다각형, 두께 = 바닥 두께, 펼친 거리 0 ~ L
    fl = [it for it in items if it.name.startswith("EX1_S") and it.name.endswith("_FLOOR") and it.layer == "PROF_CONCRETE"]
    assert fl and min(it.u0 for it in fl) == pytest.approx(0.0, abs=1e-6)
    assert max(it.u1 for it in fl) == pytest.approx(L, abs=lay.spec.half_out)            # 꺾임부 연귀 끝까지
    first = min(fl, key=lambda it: it.u0)
    zs = sorted({round(z, 6) for _, z in first.pts})
    assert zs[-1] - zs[0] == pytest.approx(lay.spec.floor_t) and zs[-1] == pytest.approx(lay.z_floor)
    assert all(it.hatch_layer == "PROF_HATCH" for it in fl)
    # 출입구: 펼친 거리 L 부터 (이음면 = 통로 끝), 끝 = L + u_end, 지표선
    en = [it for it in items if it.name.startswith("EN1_") and it.pts and len(it.pts) > 2]
    assert min(it.u0 for it in en) == pytest.approx(L, abs=1e-6)
    x0, x1, z0, z1 = profile_bounds(items)
    assert x1 >= L + ent.layout.u["end"] - 1e-6 and z1 >= ent.layout.ground
    assert any(it.layer == "PROF_CENTER" and it.name == "EN1_GL" for it in items)
    # 중심선(0)은 에스컬레이터 구역 밖 → 에스컬레이터는 너머(왼쪽이면) 또는 없음, 에스컬레이터 중심으로 옮기면 절단
    esc_t = sum(ent.escalator.t_range) / 2
    cut = passage_profile_items(eng, "EX1", esc_t)
    assert any(it.layer == "PROF_ESCALATOR" for it in cut) and not any(it.layer == "PROF_ESCALATOR" for it in items)


def test_profile_doc_stacks_passages_and_output(tmp_path):
    from engine.bim_engine import BIMEngine
    from config.output_config import OutputOptions
    from passages.passage_spec import PassageSpec, station_path
    cfg = cfg_with(passages=[bent_passage(),
                             PassageSpec(floor=3, path=station_path([(120, -10, None), (120, -25, 0)]), name="EX2")])
    eng = StationCADEngine(cfg)
    doc = eng.build_path_profile_doc()
    texts = [t.dxf.text for t in doc.modelspace().query("TEXT")]
    assert sum("PASSAGE PROFILE VIEW" in t for t in texts) == 2 and any("EN1 ENTRANCE" in t for t in texts)
    opt = OutputOptions(dxf3d=False, ifc=False, plan=False, profile=False, section=False, path_profile=True)
    paths = BIMEngine.build(cfg, tmp_path / "out", opt)
    assert [os.path.basename(p) for p in paths] == ["통로종단면도.dxf"]
    assert ezdxf.readfile(paths[0]).modelspace().query("LWPOLYLINE")


def test_axis_choices_and_parse():
    eng = _eng()
    cfg = eng.cfg
    assert path_axis_choices(cfg) == [("통로 EX1 경로", "EX1")]
    assert parse_path_axis("통로 EX1 경로", cfg) == ("EX1", 0.0)
    assert parse_path_axis("통로 EX1 경로 +0.98", cfg) == ("EX1", pytest.approx(0.98))
    assert parse_path_axis("선형 중심 (C.L.)", cfg) is None
    with pytest.raises(ValueError, match="중심선에서의 거리"):
        parse_path_axis("통로 EX1 경로 abc", cfg)


def test_print_draft_option():
    from gui.print_draft import PrintDraft, preview
    d = PrintDraft(path_profile=True)
    assert d.to_options(4.4).path_profile and "통로 종단면도" in preview(d, None, None, None)


def test_preview_profile_tab_path_axis(tmp_path, monkeypatch):
    import tkinter as tk
    from gui.gui_app import StationBIMApp
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("디스플레이가 없어 GUI 테스트를 건너뜀")
    app = StationBIMApp(root, recent_file=str(tmp_path / "recent.json"), watch=False)
    try:
        class _Box:
            def __getattr__(self, name):
                return lambda *a, **k: None
        monkeypatch.setattr("gui.preview_window.messagebox", _Box())
        app.passage_tab.add_passage()
        app.on_preview()
        pv = app.preview
        name = app.passage_tab.drafts.items[0].name or "EX1"
        label = f"통로 {name} 경로"
        assert label in pv.profile_axis["values"]
        pv.profile_axis.set(label + " +0.5")
        pv.draw_profile()
        assert "경로 종단" in pv.status.cget("text") and pv.profile.key == ("path", name)
        pv.close()
    finally:
        root.destroy()
