"""스카이라이프 편성표 (보강 1).

- 주소: https://www.skylife.co.kr/api/api/public/tv/schedule/YYYYMMDD
- 출연진·세부 장르·생방송 여부를 얻는다. U+ 방송과의 짝짓기는 merge.py 에서.
- U+ 가 실패한 날에는 이 출처만으로 하루표를 만든다 (pipeline.py).
- 실제 구현 전에 docs/명세.md 7절에 출처·이용약관을 기록한다 (공통 PR).
"""

from datetime import date
from typing import Any


class SkylifeSource:
    name = "skylife"

    def fetch(self, day: date) -> dict[str, Any]:
        """그날 스카이라이프 편성표 원본을 받는다."""
        raise NotImplementedError("스카이라이프 수집은 아직 구현 전 (이슈 #12 이후)")
