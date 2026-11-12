from enum import Enum


class StairPartKind(Enum):
    """계단 구성 부재"""
    FLIGHT = "FLIGHT"      # 계단 런 (디딤판 + 허리 슬래브)
    LANDING = "LANDING"    # 중간 계단참
