"""검증을 마친 설정의 배치 계산 결과 캐시.

엔진·검사가 같은 배치(실·계단·에스컬레이터·통로 …)를 여러 번 다시 계산하던 것을 한 번으로 줄인다 (실무 샘플: 실 배치
한 번 갱신에 약 1.5만 번 반복, 모델 갱신 약 30초 → 2초). `StationProjectConfig.validate` 가 처음에 캐시를 끄고, 입력
정규화(실 붙임) 뒤에 빈 캐시를 켠다 (오류로 끝나면 꺼진 채).

무효화: 캐시는 설정의 입력 필드(dataclass 필드) 객체 identity 를 기억해, 필드를 **바꿔 끼우면**(cfg.passages = [...],
cfg.finish_settings = ...) 다음 조회에서 비운다. 리스트·입력 객체를 **제자리에서 고치면**(append, spec.x = …) 알 수 없으므로
그 뒤에는 validate 를 다시 부를 것 (엔진 생성자는 항상 부름, GUI 는 갱신마다 새 설정을 만듦).
"""
import dataclasses
import functools

ATTR = "_layout_cache"
_IDS = "__field_ids__"


def _field_ids(cfg) -> tuple:
    return tuple(id(getattr(cfg, f.name, None)) for f in dataclasses.fields(cfg)) if dataclasses.is_dataclass(cfg) else ()


def cached_layout(name: str):
    """cfg 를 첫 인자로 받는 배치 함수 결과를 cfg 의 캐시에 둔다 (나머지 인자는 해시 가능해야 함, 아니면 캐시 안 함)"""
    def deco(fn):
        @functools.wraps(fn)
        def wrap(cfg, *args, **kw):
            cache = getattr(cfg, ATTR, None)
            if cache is None or kw:
                return fn(cfg, *args, **kw)
            ids = _field_ids(cfg)
            if cache.get(_IDS) != ids:                 # 입력 필드를 바꿔 끼움 → 비움
                cache.clear()
                cache[_IDS] = ids
            key = (name, args)
            try:
                hit = key in cache
            except TypeError:                          # 해시할 수 없는 인자
                return fn(cfg, *args, **kw)
            if not hit:
                cache[key] = fn(cfg, *args, **kw)
            return cache[key]
        return wrap
    return deco
