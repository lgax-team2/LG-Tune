"""대화 에이전트 1단계 테스트 (API 키·네트워크 없이 통과해야 함).

흐름: 글자로 말 걸기 → 기억(SQLite) 참고 → LLM 어댑터로 답 → 대화 저장.
LLM 이 3초 안에 답 못 하거나 오류 나면 고정 멘트로 답한다.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.chat.service import FALLBACK_LINE, ChatService, get_chat_service
from app.llm.base import Message
from app.llm.fake import FakeLLM
from app.main import app
from app.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "test.db")


def run(coro):
    return asyncio.run(coro)


# ───────── 기억 저장소 ─────────


def test_store_saves_and_reads_messages_in_order(store):
    store.add_message("user", "안녕")
    store.add_message("assistant", "안녕하세요")
    msgs = store.recent_messages(limit=10)
    assert [(m.role, m.text) for m in msgs] == [("user", "안녕"), ("assistant", "안녕하세요")]


def test_store_recent_messages_keeps_only_latest(store):
    for i in range(5):
        store.add_message("user", f"말{i}")
    assert [m.text for m in store.recent_messages(limit=2)] == ["말3", "말4"]


def test_store_keeps_data_after_reopen(tmp_path):
    MemoryStore(tmp_path / "a.db").add_card("딸 이름은 지은")
    assert MemoryStore(tmp_path / "a.db").cards() == ["딸 이름은 지은"]


# ───────── 대화 서비스 ─────────


def test_reply_uses_llm_and_saves_both_turns(store):
    llm = FakeLLM()
    result = run(ChatService(store, llm).reply("오늘 날씨 좋네"))

    assert result.fallback is False
    assert result.reply == llm.last_reply
    saved = [(m.role, m.text) for m in store.recent_messages(limit=10)]
    assert saved == [("user", "오늘 날씨 좋네"), ("assistant", result.reply)]


def test_memory_cards_are_given_to_llm(store):
    store.add_card("딸 이름은 지은, 서울 산다")
    llm = FakeLLM()
    run(ChatService(store, llm).reply("심심하다"))
    assert "딸 이름은 지은, 서울 산다" in llm.last_system


def test_previous_conversation_is_given_to_llm(store):
    llm = FakeLLM()
    service = ChatService(store, llm)
    run(service.reply("어제 가요무대 봤어"))
    run(service.reply("그거 재밌었지?"))

    sent = llm.last_messages
    assert sent[0] == Message("user", "어제 가요무대 봤어")
    assert sent[-1] == Message("user", "그거 재밌었지?")
    assert [m.role for m in sent] == ["user", "assistant", "user"]


def test_slow_llm_gives_fixed_line_after_timeout(store):
    llm = FakeLLM(delay_s=1.0)
    result = run(ChatService(store, llm, timeout_s=0.05).reply("여보세요"))

    assert result.fallback is True
    assert result.reply == FALLBACK_LINE
    saved = [(m.role, m.text) for m in store.recent_messages(limit=10)]
    assert saved == [("user", "여보세요"), ("assistant", FALLBACK_LINE)]


def test_llm_error_gives_fixed_line(store):
    result = run(ChatService(store, FakeLLM(fail=True)).reply("여보세요"))
    assert result.fallback is True
    assert result.reply == FALLBACK_LINE


def test_default_timeout_is_3_seconds(store):
    assert ChatService(store, FakeLLM()).timeout_s == 3.0


# ───────── API ─────────


@pytest.fixture
def client(store):
    app.dependency_overrides[get_chat_service] = lambda: ChatService(store, FakeLLM())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_chat_api_replies(client, store):
    r = client.post("/api/chat", json={"text": "안녕"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"]
    assert body["fallback"] is False
    assert store.recent_messages(limit=10)[0].text == "안녕"


def test_chat_api_rejects_empty_text(client):
    assert client.post("/api/chat", json={"text": ""}).status_code == 422


def test_chat_api_can_be_turned_off(client, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "chat_enabled", False)
    assert client.post("/api/chat", json={"text": "안녕"}).status_code == 403


def test_test_profile_never_uses_real_llm(monkeypatch):
    from app.llm import make_llm
    from app.settings import Settings

    s = Settings(profile="test", llm_provider="claude", anthropic_api_key="x")
    assert isinstance(make_llm(s), FakeLLM)
