"""정리된 채널·방송을 DB channels·programs 표에 넣는다.

- channels.number = U+ 채널 번호
- 같은 id 가 있으면 덮어쓴다 (매일 다시 받아도 중복 안 생김)
- genre(대표) = genres 첫 번째. 장르를 모르면 "기타"
"""

from sqlalchemy.orm import Session

from app.models.db import Channel, Program

from .normalize import UNKNOWN_GENRE, ChannelDraft, ProgramDraft


def load(session: Session, channels: list[ChannelDraft], programs: list[ProgramDraft]) -> dict[str, int]:
    """DB에 넣고 표별 줄 수를 돌려준다."""
    for c in channels:
        session.merge(Channel(id=c.id, number=c.number, name=c.name))
    for p in programs:
        genres = p.genres or [UNKNOWN_GENRE]
        session.merge(
            Program(
                id=p.id,
                channel_id=p.channel_id,
                title=p.title,
                series_key=p.series_key,
                genre=genres[0],
                genres=genres,
                start=p.start,
                end=p.end,
                cast=p.cast,
                is_new=p.is_new,
                is_live=p.is_live,
            )
        )
    session.commit()
    return {"channels": len(channels), "programs": len(programs)}
