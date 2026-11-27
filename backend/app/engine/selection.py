"""배치 DP: 겹치지 않고, 총 시간이 예산 안이면서, 배치 무게 합이 최대인 방송 조합을 고른다.

배치 무게 = (점수 − 기준점) × min(길이, 60분) × 감점(다양성 때문에 깎인 비율, 기본 1).
기준점을 겨우 넘은 방송은 무게가 0 에 가까워서, 여러 개를 합쳐도 겹치는 최애를 밀어내지 못한다.
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import config


@dataclass
class Candidate:
    key: str  # program_id
    start: datetime
    end: datetime
    score: float
    floor: float = 0.0  # 기준점. 무게는 기준점을 넘은 만큼으로만 잰다
    factor: float = 1.0  # 다양성 감점 (넘친 장르·3연속이면 0.7 씩 곱해짐)
    genre: str = ""  # 대표 장르
    series_key: str = ""
    channel_id: str = ""
    payload: Any = None  # (Program, Scored)

    @property
    def minutes(self) -> int:
        return round((self.end - self.start).total_seconds() / 60)

    @property
    def base_weight(self) -> float:
        """감점 전 무게 = (점수 − 기준점) × min(길이, 60분)."""
        return (self.score - self.floor) * min(self.minutes, config.LENGTH_CAP_MIN)

    @property
    def weight(self) -> float:
        return self.base_weight * self.factor


def overlaps(a: Any, b: Any) -> bool:
    """start·end 가 있는 두 칸이 겹치는가 (끝 = 다음 시작이면 안 겹침)."""
    return a.start < b.end and b.start < a.end


def select_best(cands: list[Candidate], budget_min: float | None = None) -> list[Candidate]:
    """겹치지 않으면서 무게 합이 최대인 조합 (시작 순). budget_min 을 주면 총 시간(분)도 그 안으로.

    쉬운 설명 (DP = 작은 문제의 답을 표에 적어 두고 키워 가기):
    끝나는 시각 순으로 줄 세운 뒤, "앞에서 j 개만 보고 시간을 t 분까지 쓸 때 얻는 최대 무게"를 표 best[j][t] 에 채운다.
    j 번째 방송은 (안 넣기) best[j-1][t] 와 (넣기) 무게 + best[그 방송 전에 끝나는 개수][t − 길이] 중 큰 쪽.
    표를 다 채운 뒤 거꾸로 따라가며 "넣기"를 고른 방송을 모은다. 같은 입력이면 항상 같은 답(동점은 정렬 순서로).
    """
    cands = sorted(cands, key=lambda c: (c.end, c.start, c.key))
    limit = sum(c.minutes for c in cands) if budget_min is None else max(0, int(budget_min))
    ends = [c.end for c in cands]
    before = [bisect_right(ends, c.start, 0, j) for j, c in enumerate(cands)]  # c 시작 전에 끝나는 후보 수
    best = [[0.0] * (limit + 1)]
    for j, c in enumerate(cands):
        prev, row = best[j], [0.0] * (limit + 1)
        for t in range(limit + 1):
            take = c.weight + best[before[j]][t - c.minutes] if c.minutes <= t else float("-inf")
            row[t] = max(prev[t], take)
        best.append(row)
    chosen, j, t = [], len(cands), limit
    while j > 0:
        c = cands[j - 1]
        if (
            c.minutes <= t
            and c.weight >= 0
            and c.weight + best[before[j - 1]][t - c.minutes] >= best[j - 1][t]
        ):
            chosen.append(c)  # 무게 0 은 손해가 없을 때만 들어감
            t -= c.minutes
            j = before[j - 1]
        else:
            j -= 1
    return sorted(chosen, key=lambda c: c.start)
