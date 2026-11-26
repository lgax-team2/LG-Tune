"""실행 설정. 값은 backend/.env 또는 환경 변수에서 읽는다.

PROFILE: dev(일상 개발) / test(자동 테스트, 전부 가짜) / demo(시연, 전부 진짜)
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    profile: Literal["dev", "test", "demo"] = "dev"
    llm_provider: Literal["fake", "claude"] = "fake"
    llm_fallback: Literal["none", "qwen_local", "exaone"] = "none"
    judge_provider: Literal["fake", "local", "jev", "claude"] = "fake"  # 응/아니·명령·관련성 판단
    stt_provider: Literal["fake", "whisper"] = "fake"
    tts_provider: Literal["fake", "supertonic", "custom"] = "fake"
    chat_enabled: bool = True  # 대화 기능 켜기/끄기 (편성만 쓸 때 false)
    llm_timeout_s: float = 3.0  # 이 시간 넘으면 고정 멘트로 답
    clock_speed: float = 1.0
    demo_mode: bool = False

    anthropic_api_key: str = ""
    jev_api_key: str = ""
    claude_realtime_model: str = "claude-haiku-5-5"
    claude_batch_model: str = "claude-sonnet-5-5"

    db_path: str = "data/tune.db"


settings = Settings()
