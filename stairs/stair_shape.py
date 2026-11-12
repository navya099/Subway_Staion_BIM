"""계단 형상: 공통 띠 부재(helper.strip_member)를 그대로 쓴다.

StairStrip  = 띠 1개 (계단은 상면이 항상 수평: zt1 없음)
StairPartShape = 띠들을 이은 런 / 계단참 형상
"""
from helper.strip_member import Strip, StripShape

StairStrip = Strip
StairPartShape = StripShape
