# ml/ 규칙 (AI 학습 담당용 · 루트 CLAUDE.md 규칙도 함께 적용)

- 이 폴더 안만 고친다. 브랜치 `ml/<모델>-<내용>` (예: `ml/wakeword-v1`), 커밋 `ml(wakeword): ...`
- **데이터·체크포인트·녹음 파일은 Git에 올리지 않는다** (팀 구글 드라이브). 저장소엔 스크립트·노트북·`MODEL_CARD.md` 만
- 백엔드와의 입출력 약속은 `docs/onboarding/02_AI.md` 의 "백엔드와의 약속". 이 모양을 바꾸려면 사람에게 먼저 확인
- 완성 모델(`.onnx`)은 GitHub Releases 에 올리고 `models/manifest.json` 에 버전·sha256 기록
- 외부 데이터·코드·사전학습 모델은 `docs/THIRD_PARTY.md` 에 출처·라이선스 기록. AI Hub 데이터는 학습에만, 재배포 금지
- 평가셋은 처음에 고정하고 바꾸지 않는다 (버전 간 비교를 위해)
