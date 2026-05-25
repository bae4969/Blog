# .claude/scripts/ — hook·자동화 스크립트

[settings.local.json](../settings.local.json)의 hook이 호출하는 실행 스크립트를 모아둔다. 한 줄로 끝나지 않거나, 인코딩·이스케이프·예외 처리가 필요한 명령은 settings.json에 인라인하지 말고 여기로 분리.

## 현재 스크립트

| 파일 | 호출 시점 | 역할 | 의존성 |
|---|---|---|---|
| [session_start_hook.py](session_start_hook.py) | `SessionStart` hook | `.claude/state/current.json`을 모델 컨텍스트(`hookSpecificOutput.additionalContext`)로 자동 주입. CLAUDE.md "절대 진입 절차"의 시스템 강제 측 — 자연어 강제와의 이중 안전망 | Python 표준 라이브러리만 |

## 작성 규칙

1. **한 파일 한 hook**: 파일명은 `<event>_<purpose>.{py,sh}` (예: `pretooluse_log.sh`).
2. **Windows 호환**:
   - Python 스크립트는 첫머리에 `sys.stdout.reconfigure(encoding="utf-8")` 필수. cp949로 출력되어 한글이 깨짐 (실제 사고 1회).
   - 셸 스크립트는 bash 가정 (Git Bash). PowerShell이 필요하면 `.ps1`로 별도 분리.
3. **무음 실패 원칙**: hook은 워크플로우를 막으면 안 된다. 입력 파일 부재·예외는 `sys.exit(0)`으로 조용히 종료. 에러 출력 금지.
4. **출력 규약**:
   - 모델 컨텍스트에 정보를 주입하려면 `hookSpecificOutput.additionalContext` JSON으로 출력.
   - 사용자 UI에 메시지를 띄우려면 `systemMessage`.
   - 단순 stdout은 transcript에 보일 수는 있으나 모델 컨텍스트 주입은 보장되지 않음 — JSON 방식 권장.
5. **의존성 명시**: 외부 도구(python, jq 등)에 의존하면 README 표에 표기. 다른 프로젝트로 복사 시 누락 사고 방지.
6. **테스트**: 새 hook은 settings.json에 등록하기 전에 직접 실행해 출력 형태와 exit code를 확인.

## 호출되지 않는 스크립트는 두지 않음

`settings.local.json` 어디에서도 참조하지 않는 스크립트는 삭제하거나, 임시 보관이라면 `.claude/scripts/_unused/`로 옮긴다 — hook 시스템과 일반 유틸이 섞이면 신뢰성이 떨어진다.
