# frontend/ 규칙 (프론트 담당용 · 루트 CLAUDE.md 규칙도 함께 적용)

- 이 폴더 안만 고친다. 브랜치 이름은 `feat/fe-...`, `fix/fe-...`, 커밋은 `feat(fe): ...`
- 백엔드 없이 개발: `pnpm dev:mock` (가짜 서버가 `contracts/scenarios/*.jsonl` 을 재생)
- `src/shared/api/*.ts` 는 **자동 생성 파일 → 직접 수정 금지.** 이벤트 모양이 바뀌어야 하면 코드를 고치지 말고 사용자에게 "백엔드 담당에게 계약 변경 요청(이슈에 `contract` 라벨)" 하라고 안내
- 이벤트 목록과 화면 순서: `docs/onboarding/01_프론트.md`
- 시니어 화면 원칙: 글자 최소 28px, 고대비, 한 번에 메시지 하나, 애니메이션 최소, 색만으로 의미 전달 금지
- 리모컨 없이 쓰는 화면이 기본 (AI 친구는 음성으로만 부름)
- PR 전 확인: `pnpm typecheck && pnpm build`
