"""고른 이유: 칸 하나 → 어르신께 보여 줄 한 줄 + 그 근거 코드(basis).

근거 코드는 기준표 M5(이유가 실제 근거와 일치) 검사에 쓴다. 예: "cast:송미란" = 송미란 님이 실제로 나오고 좋아함.
여러 근거면 "+" 로 잇는다 (예: "series+new" = 자주 보는 프로그램의 새 회차).
"""

from dataclasses import dataclass

from .plan import NOVELTY, PIN, REPRESENTATIVE, Entry

UNKNOWN_TASTE = "아직 취향을 몰라서 새로 하는 방송 위주로 골랐어요"


@dataclass(frozen=True)
class Reason:
    text: str
    basis: str


def has_batchim(word: str) -> bool:
    last = word[-1] if word else ""
    return "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0


def ieyo(word: str) -> str:
    """받침 있으면 '이에요', 없으면 '예요' (프로그램이에요 / 트로트예요)."""
    return f"{word}이에요" if has_batchim(word) else f"{word}예요"


def wa(word: str) -> str:
    """받침 있으면 '과', 없으면 '와' (교양과 / 트로트와)."""
    return f"{word}과" if has_batchim(word) else f"{word}와"


def explain(e: Entry, knows_taste: bool = True, favorite: str | None = None) -> Reason:
    """칸의 역할·종류·점수 내역에서 이유와 근거를 만든다."""
    genre = getattr(e.source, "genre", "")
    if e.kind == "fill":
        return Reason("채널을 그대로 두고 이어서 봐요", "fill")
    if e.role == NOVELTY:
        what = "콘텐츠" if e.kind == "lg" else "방송"
        return Reason(
            f"새로 추천해 드려요 — 좋아하시는 {wa(favorite or '')} 가까운 {genre} " + ieyo(what),
            f"novelty:{genre}",
        )
    if e.kind == "lg":
        return Reason("빈 시간에 볼 만한 " + ieyo(f"{e.channel_id} {genre}"), f"lg:{genre}")
    if e.role == PIN:
        return Reason("매일 챙겨 드리기로 한 " + ieyo("방송"), "pin")
    if e.role == REPRESENTATIVE:
        return Reason(f"오늘 꼭 챙겨 보실 {e.title} 새 회차예요", "representative")
    if not knows_taste:
        return Reason(UNKNOWN_TASTE, "unknown_taste")
    return _from_score(e)


def _from_score(e: Entry) -> Reason:
    """점수를 가장 많이 올린 항목으로 이유를 고른다 (기여가 0 인 항목은 이유로 안 씀)."""
    p = e.source
    parts = e.scored.parts if e.scored else {}
    positive = {k: v for k, v in parts.items() if v > 0}
    if e.scored and e.scored.top_cast is None:
        positive.pop("cast", None)  # 출연자 정보가 없을 때 넣은 기본값은 "○○ 님이 나와요"의 근거가 아님
    if not positive:
        return Reason("오늘 볼 만한 " + ieyo("방송"), "none")
    top = max(positive, key=lambda k: (positive[k], k))
    if top == "series":
        if getattr(p, "is_new", False):
            return Reason("자주 보시는 " + ieyo("프로그램 새 회차"), "series+new")
        return Reason("자주 보시는 " + ieyo("프로그램"), "series")
    if top == "cast":
        return Reason(f"{e.scored.top_cast} 님이 나와요", f"cast:{e.scored.top_cast}")
    if top == "genre":
        return Reason(f"좋아하시는 {e.scored.top_genre} " + ieyo("방송"), f"genre:{e.scored.top_genre}")
    if top == "timeslot":
        return Reason("이 시간에 자주 보시는 " + ieyo("방송"), "timeslot")
    if top == "fresh":
        if getattr(p, "is_live", False):
            return Reason(ieyo("생방송"), "live")
        return Reason("새로 하는 " + ieyo("회차"), "new")
    return Reason("가족이 추천한 " + ieyo("프로그램"), "family")


def make_reason(e: Entry, knows_taste: bool = True, favorite: str | None = None) -> str:
    return explain(e, knows_taste, favorite).text
