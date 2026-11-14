"""프로젝트 파일(*.ssbim) 저장 / 불러오기 — 화면 비의존 부분 (상태 직렬화, 포함된 선형, 최근 목록)"""
import json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from config.alignment_io import load_alignment
from config.alignment_landxml import LandXMLOptions
from config.alignment_text import XYZOptions
from gui.column_draft import CIRCLE, FloorDraft, PatternDraft, RowDraft
from gui.entrance_draft import SIDE_RIGHT, EntranceDraft
from gui.opening_draft import OpeningDraft
from gui.passage_draft import MODE_WORLD, PassageDraft, VertexDraft
from gui.project_file import (FORMAT, VERSION, ProjectState, RecentProjects, embed_alignment, open_project,
                              save_project)
from gui.stair_draft import StairDraft

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


def full_state():
    st = ProjectState()
    st.fields = {"length": "213.2", "floors": "3", "floor_height_1": "6.1", "wall_t_3": "0.9", "start_station": "abc"}
    st.platform_type = 0
    st.sync_all = False
    st.column_floors = {1: FloorDraft(rows=[RowDraft(t_offset="-2", patterns=[PatternDraft(), PatternDraft(shape=CIRCLE, diameter="0.9")])]),
                        2: FloorDraft(rows=[])}
    st.opening_drafts = [OpeningDraft(name="O1", slabs={1, 2})]
    st.stair_drafts = [StairDraft(name="S", lower_floor=2, tread="0.28")]
    st.passage_drafts = [PassageDraft(name="P", floor=3, mode=MODE_WORLD, vertices=[VertexDraft("1", "2", ""), VertexDraft("3", "4", "0.5")])]
    st.entrance_drafts = [EntranceDraft(name="EN", escalator=False, side=SIDE_RIGHT, stair_offset="")]
    return st


def test_round_trip_keeps_every_input_exactly(tmp_path):
    st = full_state()
    save_project(tmp_path / "a.ssbim", st)
    back = open_project(tmp_path / "a.ssbim")
    assert back == st                                                  # 잘못된 입력('abc')·빈 목록·집합까지 그대로
    assert isinstance(back.opening_drafts[0].slabs, set) and back.column_floors[2].rows == []
    raw = json.loads((tmp_path / "a.ssbim").read_text(encoding="utf-8"))
    assert raw["format"] == FORMAT and raw["version"] == VERSION and "213.2" in (tmp_path / "a.ssbim").read_text(encoding="utf-8")


def test_old_file_missing_fields_get_defaults_and_unknown_fields_ignored():
    d = ProjectState().to_dict()
    d["stair_drafts"] = [{"name": "S", "future_field": 1}]
    d["something_new"] = {"x": 1}
    del d["entrance_drafts"]
    st = ProjectState.from_dict(d)
    assert st.stair_drafts == [StairDraft(name="S")] and st.entrance_drafts == []


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.update(format="other"), "프로젝트 파일이 아닙니다"),
    (lambda d: d.update(version=VERSION + 1), "새 버전"),
    (lambda d: d.update(stair_drafts={"a": 1}), "목록"),
    (lambda d: d.update(stair_drafts=[{"lower_floor": "x"}]), "lower_floor"),
    (lambda d: d.update(column_floors={"1": {"rows": "no"}}), "rows"),
    (lambda d: d.update(column_floors={"a": {}}), "기둥"),
    (lambda d: d.update(alignment={"main": "a.xml", "files": {"a.xml": "!!"}}), "손상"),
    (lambda d: d.update(alignment={"main": "a.xml", "files": {}}), "목록"),
])
def test_bad_project_rejected(mutate, msg):
    d = ProjectState().to_dict()
    mutate(d)
    with pytest.raises(ValueError, match=msg):
        ProjectState.from_dict(d)


def test_not_json_or_missing_file(tmp_path):
    (tmp_path / "x.ssbim").write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 형식"):
        open_project(tmp_path / "x.ssbim")
    with pytest.raises(ValueError, match="열 수 없습니다"):
        open_project(tmp_path / "none.ssbim")


def test_save_is_atomic_and_keeps_old_file_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "a.ssbim"
    save_project(path, full_state())
    before = path.read_bytes()
    import gui.project_file as PF
    monkeypatch.setattr(PF.json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        save_project(path, ProjectState())
    assert path.read_bytes() == before and os.listdir(tmp_path) == ["a.ssbim"]      # 임시 파일도 남지 않음


# ===================================================== 포함된 선형 파일
@pytest.mark.parametrize("name,opt", [
    ("civil3d_korea_cubic_spiral.xml", LandXMLOptions()),
    ("alignment_xyz_example.txt", XYZOptions(smooth_m=8.0)),
    ("curve_alignment.json", None),
])
def test_embedded_alignment_survives_source_deletion(tmp_path, name, opt):
    src = tmp_path / "src" / name
    src.parent.mkdir()
    shutil.copy(os.path.join(SAMPLES, name), src)
    expect = load_alignment(str(src), opt)
    st = ProjectState(alignment=embed_alignment(str(src), opt))
    save_project(tmp_path / "p.ssbim", st)
    shutil.rmtree(src.parent)                                           # 원본 삭제
    back = open_project(tmp_path / "p.ssbim")
    assert back.alignment.options == opt and back.alignment.source_path == str(src)
    a = back.alignment.load()
    assert (a.start_station, a.end_station) == pytest.approx((expect.start_station, expect.end_station))
    s = (a.start_station + a.end_station) / 2
    assert a.point_at(s) == pytest.approx(expect.point_at(s)) and a.elevation_at(s) == pytest.approx(expect.elevation_at(s))
    assert a.azimuth_at(s) == pytest.approx(expect.azimuth_at(s))
    assert back.key() == st.key()


def test_alignment_json_referencing_points_file_embeds_both(tmp_path):
    d = tmp_path / "src"
    (d / "data").mkdir(parents=True)
    shutil.copy(os.path.join(SAMPLES, "alignment_xyz_example.txt"), d / "data" / "pts.txt")
    (d / "al.json").write_text(json.dumps({"type": "points", "file": "data/pts.txt", "smooth_m": 6}), encoding="utf-8")
    expect = load_alignment(str(d / "al.json"))
    e = embed_alignment(str(d / "al.json"))
    assert set(e.files) == {"al.json", "pts.txt"} and json.loads(e.files["al.json"])["file"] == "pts.txt"
    save_project(tmp_path / "p.ssbim", ProjectState(alignment=e))
    shutil.rmtree(d)
    a = open_project(tmp_path / "p.ssbim").alignment.load()
    assert a.end_station == pytest.approx(expect.end_station)


def test_broken_embedded_alignment_reports_without_temp_path(tmp_path):
    src = tmp_path / "bad.json"
    src.write_text('{"type": "nope"}', encoding="utf-8")
    e = embed_alignment(str(src))
    with pytest.raises(ValueError, match="bad.json") as ei:
        e.load()
    assert "ssbim_" not in str(ei.value)


def test_digest_changes_with_options():
    path = os.path.join(SAMPLES, "alignment_xyz_example.txt")
    assert embed_alignment(path, XYZOptions()).digest() != embed_alignment(path, XYZOptions(smooth_m=9)).digest()


# ===================================================== 최근 프로젝트
def test_recent_projects_order_limit_and_persistence(tmp_path):
    f = str(tmp_path / "cfg" / "recent.json")
    r = RecentProjects(f, limit=3)
    for n in "abcd":
        r.add(str(tmp_path / f"{n}.ssbim"))
    r.add(str(tmp_path / "b.ssbim"))
    names = [os.path.basename(p) for p in RecentProjects(f, limit=3).items]
    assert names == ["b.ssbim", "d.ssbim", "c.ssbim"]
    r.remove(str(tmp_path / "d.ssbim"))
    assert [os.path.basename(p) for p in RecentProjects(f).items] == ["b.ssbim", "c.ssbim"]


def test_recent_projects_ignores_broken_file(tmp_path):
    f = tmp_path / "recent.json"
    f.write_text("garbage", encoding="utf-8")
    assert RecentProjects(str(f)).items == []
