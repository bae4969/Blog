"""외부 연동 설정 — DB `app_setting`(키·값). 관리자 화면 `/admin/integrations` 에서 넣고 바꾼다.

AI 모델·SMTP 인증 정보가 여기 있다(AI 로그인 자체는 codex 의 `auth.json` — app/services/codex_runner.py). 2026-10-10 전에는 `.env.api` 였는데 운영 `.env.api` 는
배포로 안 따라가 손으로 넣어야 했다 — 사용자 결정으로 DB 한 곳으로 옮기고 `.env.api` 대체값은 남기지 않았다.

⚠️ 비밀 값(`SECRETS`)은 평문으로 저장한다. 대신 **화면으로 내보내지 않는다** — 관리자 화면은 끝 4자리만 보이고,
   빈 칸으로 저장하면 그대로 둔다.
"""

import re

from sqlalchemy import text

#: 키 → 기본값. 화면의 입력 칸도 이 순서다.
DEFAULTS: dict[str, str] = {
    "ai_model": "sol",                 # 이름 일부 — 그중 최신 모델을 쓴다(pick_model)
    "ai_effort": "",                   # 추론 강도(low…ultra). 비우거나 모델이 지원하지 않으면 모델 기본값
    "smtp_host": "",
    "smtp_port": "465",
    "smtp_user": "",
    "smtp_password": "",
    "plan_mail_to": "",
    "plan_daily_on": "",               # "1" 이면 매일 점검(plan_v1.daily_tick) — 기본은 꺼짐(테스트 컨테이너도 같은 루프를 돈다)
    "plan_daily_at": "12:00",          # 점검 시각(KST, HH:MM)
}
SECRETS = frozenset({"smtp_password"})
#: 화면의 강도 선택지(모델마다 지원 범위가 다르다 — 지원하지 않으면 모델 기본값을 쓴다).
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")


async def load(db) -> dict[str, str]:
    rows = (await db.execute(text("SELECT setting_key, setting_value FROM app_setting"))).all()
    stored = {k: v for k, v in rows if k in DEFAULTS}
    return {**DEFAULTS, **stored}


async def save(db, values: dict[str, str]) -> None:
    """모르는 키는 버린다. 비밀 값이 빈 문자열이면 건드리지 않는다(화면이 원래 값을 모르므로)."""
    for k, v in values.items():
        if k not in DEFAULTS or (k in SECRETS and not v):
            continue
        await db.execute(text(
            "INSERT INTO app_setting (setting_key, setting_value) VALUES (:k, :v) "
            "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)"), {"k": k, "v": v})
    await db.commit()


def masked(value: str) -> str:
    """화면에 보일 비밀 값 — 끝 4자리만. 비었으면 빈 문자열."""
    return f"…{value[-4:]}" if value else ""


def _version(model_id: str) -> tuple[int, ...]:
    """`codex-gpt-6.1-sol` → (6, 1). 숫자가 없으면 () — 가장 낮게 친다."""
    m = re.search(r"\d+(?:\.\d+)*", model_id)
    return tuple(int(x) for x in m.group().split(".")) if m else ()


def pick_model(ids: list[str], want: str) -> str | None:
    """설정한 모델 이름 → 실제로 부를 모델 id(2026-10-10 사용자 요청: "sol 만 적으면 최신").

    정확히 같은 id 가 있으면 그것, 아니면 `want` 를 이름에 품은 것 중 버전 숫자가 가장 큰 것. 없으면 None.
    """
    if want in ids:
        return want
    hits = [i for i in ids if want.lower() in i.lower()]
    return max(hits, key=_version) if hits else None
