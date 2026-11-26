"""⑤ 고른 이유: 점수를 가장 많이 올린 항목 → 어르신께 보여 줄 한 줄."""

from .planner import Entry


def ieyo(word: str) -> str:
    """받침 있으면 '이에요', 없으면 '예요' (프로그램이에요 / 트로트예요)."""
    last = word[-1] if word else ""
    has_batchim = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return f"{word}이에요" if has_batchim else f"{word}예요"


def make_reason(e: Entry) -> str:
    if e.kind == "fill":
        return "채널을 그대로 두고 이어서 봐요"
    if e.kind == "lg":
        genre = getattr(e.source, "genre", "")
        return "빈 시간에 볼 만한 " + ieyo(f"{e.channel_id} {genre}")
    if e.pinned:
        return "매일 챙겨 드리기로 한 " + ieyo("방송")
    if not e.scored:
        return "오늘 볼 만한 " + ieyo("방송")

    p = e.source
    top = max(e.scored.parts, key=e.scored.parts.get)
    if top == "series":
        return "자주 보시는 " + ieyo("프로그램 새 회차" if getattr(p, "is_new", False) else "프로그램")
    if top == "cast":
        return f"{e.scored.top_cast} 님이 나와요"
    if top == "genre":
        return f"좋아하시는 {getattr(p, 'genre', '')} " + ieyo("방송")
    if top == "timeslot":
        return "이 시간에 자주 보시는 " + ieyo("방송")
    if top == "fresh":
        return ieyo("생방송") if getattr(p, "is_live", False) else "새로 하는 " + ieyo("회차")
    return "가족이 추천한 " + ieyo("프로그램")
