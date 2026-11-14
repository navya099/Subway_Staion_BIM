"""프로젝트 파일 (*.ssbim, JSON) 저장 / 불러오기 — 화면 비의존 부분.

화면 입력을 **문자열 그대로**(입력칸 텍스트 + 탭별 입력 초안) 저장하므로, 미완성·오류 입력도 그대로 복원된다.
불러온 선형 파일(LandXML · 좌표 목록 · 선형 JSON)은 원본 내용과 읽기 옵션을 프로젝트 안에 포함한다
(원본을 옮기거나 지워도 열림). 선형 JSON 이 다른 파일을 참조하면 그 파일도 함께 포함한다.
"""
import base64
import dataclasses
import hashlib
import json
import os
import tempfile
import zlib
from dataclasses import dataclass, field
from typing import Optional

from config.alignment_io import file_kind, load_alignment
from config.alignment_landxml import LandXMLOptions
from config.alignment_text import XYZOptions
from gui.column_draft import FloorDraft, PatternDraft, RowDraft
from gui.entrance_draft import EntranceDraft, EntranceDrafts
from gui.escalator_draft import EscalatorDraft, EscalatorDrafts
from gui.opening_draft import OpeningDraft, OpeningDrafts
from gui.passage_draft import PassageDraft, PassageDrafts, VertexDraft
from gui.print_draft import PrintDraft
from gui.stair_draft import StairDraft, StairDrafts

FORMAT = "subway_station_bim_project"
VERSION = 1
SUFFIX = ".ssbim"
FILETYPES = [("정거장 BIM 프로젝트", "*" + SUFFIX), ("모든 파일", "*.*")]

# 목록 필드의 원소 형식 (dataclass 필드 형식이 그냥 list 라서 따로 둠)
_NESTED = {(FloorDraft, "rows"): RowDraft, (RowDraft, "patterns"): PatternDraft, (PassageDraft, "vertices"): VertexDraft}
# 목록형 탭: 상태 필드 이름 → (초안 묶음, 원소 형식)
LIST_DRAFTS = {"opening_drafts": (OpeningDrafts, OpeningDraft), "stair_drafts": (StairDrafts, StairDraft),
               "escalator_drafts": (EscalatorDrafts, EscalatorDraft), "passage_drafts": (PassageDrafts, PassageDraft),
               "entrance_drafts": (EntranceDrafts, EntranceDraft)}


# ====================================================================== 초안 dataclass ↔ JSON
def _plain(obj):
    if dataclasses.is_dataclass(obj):
        return {f.name: _plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, (list, tuple)):
        return [_plain(x) for x in obj]
    return obj


def _build(cls, d, where: str):
    """JSON 사전 → 초안 dataclass. 없는 필드는 기본값(옛 파일 호환), 모르는 필드는 무시(새 파일 호환).
    형식은 기본값의 형식에 맞춤 (문자열 입력칸은 str, 층 번호는 int, 체크는 bool, 슬래브 선택은 set)"""
    if not isinstance(d, dict):
        raise ValueError(f"{where}: 항목 형식이 올바르지 않습니다")
    inst = cls()
    for f in dataclasses.fields(cls):
        if f.name not in d:
            continue
        v, default = d[f.name], getattr(inst, f.name)
        elem = _NESTED.get((cls, f.name))
        try:
            if elem is not None:
                if not isinstance(v, list):
                    raise TypeError
                v = [_build(elem, x, f"{where} {f.name}") for x in v]
            elif isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, int):
                v = int(v)
            elif isinstance(default, set):
                v = {int(x) for x in v}
            elif isinstance(default, str):
                v = "" if v is None else str(v)
        except (TypeError, ValueError):
            raise ValueError(f"{where}: '{f.name}' 값이 올바르지 않습니다 ({v!r})") from None
        setattr(inst, f.name, v)
    return inst


# ====================================================================== 포함된 선형 파일
@dataclass
class EmbeddedAlignment:
    """프로젝트에 포함한 선형 파일. files: 파일 이름 → 원본 바이트 (main 이 선형 파일, 나머지는 선형 JSON 이 참조하는 파일)"""
    main: str
    files: dict
    options: Optional[object] = None          # LandXMLOptions | XYZOptions | None
    source_path: str = ""                     # 처음 불러온 위치 (표시용)

    def digest(self) -> str:
        """내용 지문 (변경 감지용, 한 번만 계산 — 포함 후 내용은 바뀌지 않음)"""
        cached = getattr(self, "_digest", None)
        if cached is not None:
            return cached
        h = hashlib.sha1()
        for name in sorted(self.files):
            h.update(name.encode("utf-8")); h.update(self.files[name])
        h.update(repr(_options_plain(self.options)).encode("utf-8"))
        self._digest = h.hexdigest()
        return self._digest

    def load(self):
        """포함된 파일을 임시 폴더에 풀어 읽음 → Alignment. 실패하면 ValueError"""
        with tempfile.TemporaryDirectory(prefix="ssbim_") as d:
            for name, data in self.files.items():
                with open(os.path.join(d, name), "wb") as f:
                    f.write(data)
            try:
                return load_alignment(os.path.join(d, self.main), self.options)
            except ValueError as e:
                raise ValueError(str(e).replace(d + os.sep, "").replace(d, "")) from None


def embed_alignment(path: str, options=None) -> EmbeddedAlignment:
    """선형 파일(과 선형 JSON 이 참조하는 points/landxml 파일)을 읽어 포함 형식으로"""
    main = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    files = {main: data}
    if file_kind(path) == "json":
        try:
            d = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            d = None
        if isinstance(d, dict) and str(d.get("type", "")).strip().lower() in ("points", "landxml") and d.get("file"):
            ref = str(d["file"])
            ref_path = ref if os.path.isabs(ref) else os.path.join(os.path.dirname(os.path.abspath(path)), ref)
            name = os.path.basename(ref_path)
            if name == main:
                name = "ref_" + name
            with open(ref_path, "rb") as f:
                files[name] = f.read()
            d["file"] = name                                  # 참조를 같은 폴더의 포함 파일로 바꿈
            files[main] = json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8")
    return EmbeddedAlignment(main=main, files=files, options=options, source_path=str(path))


def _options_plain(opt):
    if isinstance(opt, LandXMLOptions):
        return {"type": "landxml", **dataclasses.asdict(opt)}
    if isinstance(opt, XYZOptions):
        return {"type": "xyz", **dataclasses.asdict(opt)}
    return None


def _options_build(d):
    if not d:
        return None
    kind = d.get("type")
    cls = {"landxml": LandXMLOptions, "xyz": XYZOptions}.get(kind)
    if cls is None:
        raise ValueError(f"선형 읽기 옵션 형식을 알 수 없습니다 ({kind!r})")
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def _alignment_plain(e: Optional[EmbeddedAlignment]):
    if e is None:
        return None
    return {"main": e.main, "source_path": e.source_path, "options": _options_plain(e.options),
            "files": {n: base64.b64encode(zlib.compress(b, 9)).decode("ascii") for n, b in e.files.items()}}


def _alignment_build(d) -> Optional[EmbeddedAlignment]:
    if not d:
        return None
    try:
        files = {str(n): zlib.decompress(base64.b64decode(s)) for n, s in d["files"].items()}
        main = str(d["main"])
    except (KeyError, TypeError, ValueError, zlib.error, AttributeError):
        raise ValueError("포함된 선형 파일이 손상되었습니다") from None
    if main not in files or any(os.path.basename(n) != n or n in ("", ".", "..") for n in files):
        raise ValueError("포함된 선형 파일 목록이 올바르지 않습니다")
    return EmbeddedAlignment(main=main, files=files, options=_options_build(d.get("options")),
                             source_path=str(d.get("source_path", "")))


# ====================================================================== 프로젝트 상태
@dataclass
class ProjectState:
    """GUI 전체 입력 상태
    fields: 입력칸 키 → 텍스트 (선형 BP/EP, 본체 제원, 층별 높이·외벽 두께 floor_height_n / wall_t_n, 승강장 제원)
    """
    fields: dict = field(default_factory=dict)
    platform_type: Optional[int] = None
    sync_all: bool = True
    column_floors: dict = field(default_factory=dict)          # 층 번호 → FloorDraft
    opening_drafts: list = field(default_factory=list)
    stair_drafts: list = field(default_factory=list)
    escalator_drafts: list = field(default_factory=list)
    passage_drafts: list = field(default_factory=list)
    entrance_drafts: list = field(default_factory=list)
    print_draft: PrintDraft = field(default_factory=PrintDraft)     # 출력 탭 옵션
    alignment: Optional[EmbeddedAlignment] = None

    def to_dict(self) -> dict:
        d = {"format": FORMAT, "version": VERSION, "fields": dict(self.fields), "platform_type": self.platform_type,
             "sync_all": self.sync_all, "column_floors": {str(n): _plain(f) for n, f in sorted(self.column_floors.items())}}
        for name in LIST_DRAFTS:
            d[name] = _plain(getattr(self, name))
        d["print_draft"] = _plain(self.print_draft)
        d["alignment"] = _alignment_plain(self.alignment)
        return d

    @classmethod
    def from_dict(cls, d) -> "ProjectState":
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            raise ValueError("정거장 BIM 프로젝트 파일이 아닙니다")
        ver = d.get("version")
        if not isinstance(ver, int) or ver > VERSION:
            raise ValueError(f"이 프로그램보다 새 버전의 프로젝트 파일입니다 (파일 v{ver}, 지원 v{VERSION})")
        st = cls()
        st.fields = {str(k): "" if v is None else str(v) for k, v in (d.get("fields") or {}).items()}
        pt = d.get("platform_type")
        st.platform_type = None if pt is None else int(pt)
        st.sync_all = bool(d.get("sync_all", True))
        floors = d.get("column_floors") or {}
        if not isinstance(floors, dict) or not all(str(n).isdigit() for n in floors):
            raise ValueError("기둥 입력 형식이 올바르지 않습니다")
        st.column_floors = {int(n): _build(FloorDraft, f, f"기둥 {n}층") for n, f in floors.items()}
        for name, (_, elem) in LIST_DRAFTS.items():
            items = d.get(name) or []
            if not isinstance(items, list):
                raise ValueError(f"{name}: 목록이어야 합니다")
            setattr(st, name, [_build(elem, x, f"{name} {i + 1}") for i, x in enumerate(items)])
        if d.get("print_draft") is not None:
            st.print_draft = _build(PrintDraft, d["print_draft"], "출력 옵션")
        st.alignment = _alignment_build(d.get("alignment"))
        return st

    def key(self) -> str:
        """변경 여부 비교용 (포함된 선형은 내용 대신 지문)"""
        d = self.to_dict()
        d["alignment"] = None if self.alignment is None else self.alignment.digest()
        return json.dumps(d, sort_keys=True, ensure_ascii=False)


def save_project(path, state: ProjectState):
    """안전 저장: 같은 폴더의 임시 파일에 쓴 뒤 바꿔치기 (도중 실패해도 기존 파일 보존)"""
    path = os.fspath(path)
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".ssbim_", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def open_project(path) -> ProjectState:
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 형식 오류 (줄 {e.lineno}, 열 {e.colno}): {e.msg}") from None
    except UnicodeDecodeError:
        raise ValueError("정거장 BIM 프로젝트 파일이 아닙니다 (텍스트가 아님)") from None
    except OSError as e:
        raise ValueError(f"파일을 열 수 없습니다 ({e.strerror})") from None
    return ProjectState.from_dict(d)


# ====================================================================== 최근 프로젝트
def default_recent_file() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "subway_station_bim", "recent.json")


class RecentProjects:
    """최근 연 프로젝트 경로 목록 (최신 먼저, 최대 limit 개). 파일 읽기·쓰기 실패는 조용히 무시 (편의 기능)"""

    def __init__(self, path: Optional[str] = None, limit: int = 5):
        self.path = path or default_recent_file()
        self.limit = limit
        self.items: list[str] = []
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.items = [str(p) for p in data if isinstance(p, str)][:limit]
        except (OSError, ValueError, TypeError):
            self.items = []

    @staticmethod
    def _same(a: str, b: str) -> bool:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

    def add(self, path: str):
        path = os.path.abspath(path)
        self.items = [path] + [p for p in self.items if not self._same(p, path)]
        del self.items[self.limit:]
        self._save()

    def remove(self, path: str):
        self.items = [p for p in self.items if not self._same(p, path)]
        self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
