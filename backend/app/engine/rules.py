"""④ 음성 명령 규칙 모음. 점수가 아니라 규칙이라 반드시 지켜진다.

| kind | 어르신 말 | 기간 |
| exclude | "이거 이제 안 볼래" | 항상 (취소 전까지) |
| pin | "이거 매일 챙겨 줘" | 항상 |
| skip_today | "다른 거 틀어 줘" | 그날만 |
| rest_day | "오늘은 그만 볼래" | 그날 from_time 이후 |
"""

from datetime import date, datetime, time, timedelta

from ..models.db import UserRule


class RuleSet:
    def __init__(self, rules: list[UserRule], day: date, wake_time: str | None = None) -> None:
        """wake_time: 그날 기상 시각(HH:MM). '그만 볼래' 시각이 이보다 이르면 다음 날 그 시각 (wake_and_sleep 과 같은 규칙)."""
        today = day.isoformat()
        self.rows = list(rules)  # 원래 규칙 행 (기준표 판정이 엔진 함수 없이 직접 계산할 때 씀)
        on = [r for r in rules if r.active]
        blocking = [r for r in on if r.kind == "exclude" or (r.kind == "skip_today" and r.date == today)]
        self._blocked_series = {r.target for r in blocking if r.target_type == "series"}
        self._blocked_genres = {r.target for r in blocking if r.target_type == "genre"}
        self._pinned = {r.target for r in on if r.kind == "pin" and r.target_type == "series"}
        rest = [r.from_time for r in on if r.kind == "rest_day" and r.date == today and r.from_time]
        self._rest_from = min((rest_moment(day, t, wake_time) for t in rest), default=None)

    def blocks(self, series_key: str | None, genres: list[str]) -> bool:
        """뺀 시리즈이거나, 장르 목록 중 하나라도 뺀 장르면 막는다."""
        return (series_key in self._blocked_series) or any(g in self._blocked_genres for g in genres)

    def is_pinned(self, series_key: str) -> bool:
        return series_key in self._pinned and series_key not in self._blocked_series

    def allows_start(self, start: datetime) -> bool:
        """'오늘은 그만 볼래' 이후 시작하는 건 안 넣음. 날짜+시각으로 비교 (취침이 다음 날이면 자정 넘은 방송도 막음)."""
        return self._rest_from is None or start < self._rest_from


def rest_moment(day: date, from_time: str, wake_time: str | None = None) -> datetime:
    """'그만 볼래' 시각 → 날짜+시각. 기상 시각보다 이르면 다음 날 (예: 기상 06:00, 00:30 → 다음 날 00:30)."""
    at = datetime.combine(day, time.fromisoformat(from_time))
    if wake_time and at.time() < time.fromisoformat(wake_time):
        at += timedelta(days=1)
    return at
