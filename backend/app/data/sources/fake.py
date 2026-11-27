"""테스트용 가짜 출처. 네트워크를 쓰지 않고, 채널·방송·출연자 이름은 전부 가상이다.

응답 모양은 지금은 이 파일이 정한 단순한 모양이다.
진짜 U+·스카이라이프 응답을 받아 보면 그 모양에 맞춰 이 파일과 normalize.py 를 같이 고친다.
"""

from datetime import date
from typing import Any

from . import SourceError


class FakeUplusSource:
    """U+ 흉내: 채널 번호 있음, 방송은 시작 시각만."""

    name = "uplus"

    def __init__(self, fail: bool = False):
        self.fail = fail  # True 면 실패해서 pipeline 의 대체 경로를 시험할 수 있다

    def fetch(self, day: date) -> dict[str, Any]:
        if self.fail:
            raise SourceError("가짜 U+ 실패")
        d = day.isoformat()
        return {
            "date": d,
            "channels": [
                {
                    "id": "VCH1",
                    "number": 101,
                    "name": "가상채널1",
                    "programs": [
                        {"title": "가상 아침 뉴스", "start": f"{d}T06:00:00", "genre": "보도"},
                        {"title": "가상 마을 이야기 3회", "start": f"{d}T07:00:00", "genre": "드라마"},
                        {"title": "가상 노래 교실", "start": f"{d}T08:00:00", "genre": "음악"},
                    ],
                },
                {
                    "id": "VCH2",
                    "number": 102,
                    "name": "가상채널2",
                    "programs": [
                        {"title": "가상 건강 상담", "start": f"{d}T06:30:00", "genre": "교양"},
                        {"title": "가상 사극 별빛궁", "start": f"{d}T07:30:00", "genre": "드라마"},
                    ],
                },
            ],
            # U+ 는 그날 마지막 방송의 끝을 모르므로, 다음 날 첫 방송 시각(가상)을 함께 둔다
            "day_end": f"{d}T09:00:00",
        }


class FakeSkylifeSource:
    """스카이라이프 흉내: 출연진·생방송 여부가 있음."""

    name = "skylife"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def fetch(self, day: date) -> dict[str, Any]:
        if self.fail:
            raise SourceError("가짜 스카이라이프 실패")
        d = day.isoformat()
        return {
            "date": d,
            "programs": [
                {
                    "channel": "VCH1",
                    "title": "가상 아침 뉴스",
                    "start": f"{d}T06:00:00",
                    "end": f"{d}T07:00:00",
                    "live": True,
                    "cast": [],
                },
                {
                    "channel": "VCH1",
                    "title": "가상 마을 이야기(3)",
                    "start": f"{d}T07:00:00",
                    "end": f"{d}T08:00:00",
                    "live": False,
                    "cast": ["가상배우가", "가상배우나"],
                },
            ],
        }


class FakeJudgeLLM:
    """가짜 LLM: 질문을 받으면 정해 둔 JSON 문자열을 돌려준다. 몇 번 불렸는지 센다."""

    def __init__(self, answer: str = '{"value": "가상답", "confidence": 1.0}'):
        self.answer = answer
        self.calls = 0

    def ask_json(self, prompt: str) -> str:
        self.calls += 1
        return self.answer
