"""SessionStart hook — current.json을 모델 컨텍스트에 주입.

세션 시작 시 워크플로우 상태(.claude/state/current.json)를 자동 노출해
CLAUDE.md의 "절대 진입 절차"가 실제로 발동되도록 강제한다. 자연어 강제
(CLAUDE.md)와 시스템 강제(본 훅)는 서로 보완하는 이중 안전망이다 —
어느 한쪽이 누락되더라도 나머지가 방어선이 된다.

빈 객체이면 주입 생략(의미 있는 상태가 없음). 파일이 없거나 읽기 실패해도
조용히 종료해 어떤 입력에도 훅이 워크플로우를 막지 않는다.
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

CURRENT_PATH = ".claude/state/current.json"

current_content = None
if os.path.exists(CURRENT_PATH):
    try:
        with open(CURRENT_PATH, encoding="utf-8") as f:
            raw = f.read().strip()
        if raw and raw != "{}":
            current_content = raw
    except Exception:
        pass  # 읽기 실패 — 무음 처리

# 주입할 내용이 없으면 출력 없이 종료
if current_content is None:
    sys.exit(0)

context = (
    "===== .claude/state/current.json (워크플로우 상태) =====\n"
    + current_content
    + "\n===== END =====\n\n"
    "위 상태가 searching/planning/awaiting_approval/approved/implementing/verifying/blocked 이면 "
    "신규 요청 처리 전에 워크플로우 재개 옵션(재개/재계획/취소)을 사용자에게 먼저 질의할 것."
)

output = {
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context,
    }
}
print(json.dumps(output, ensure_ascii=False))
