"""U+tv 홈페이지 채널 안내 (기준 편성표).

- 후보 채널·시간표·U+ 채널 번호를 받는다. 오늘 포함 5일치, 방송마다 시작 시각만 있음.
- 요청 방법은 epg2xml LG 코드를 참고만 한다 (코드 복사 금지):
  https://github.com/epg2xml/epg2xml/blob/main/epg2xml/providers/lg.py
- 실제 구현 전에 docs/명세.md 7절에 출처·이용약관을 기록한다 (공통 PR).
"""

from datetime import date
from typing import Any


class UplusSource:
    name = "uplus"

    def fetch(self, day: date) -> dict[str, Any]:
        """그날 U+ 채널 목록(번호 포함)과 채널별 방송 목록 원본을 받는다."""
        raise NotImplementedError("U+ 수집은 아직 구현 전 (이슈 #12 이후)")
