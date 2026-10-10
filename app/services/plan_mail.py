"""투자 계획 이벤트 시작 메일 — 보낼 이벤트 고르기와 메일 내용. **DB 도 SMTP 도 모른다.**

보내는 일(1분마다 훑기·중복 막기·SMTP)은 [plan_v1](../api/plan_v1.py) 의 `mail_loop` 가 한다.
"""

from datetime import datetime, timedelta
from email.message import EmailMessage

from app.services.invest_plan import CLASS_LABEL, PlanDoc, _kst

#: 시작 시각이 이만큼 지난 이벤트는 보내지 않는다 — 앱이 오래 꺼져 있다 켜졌을 때 옛 알림이 몰려오지 않게.
LATE_LIMIT = timedelta(hours=24)


def due_events(doc: PlanDoc, now: datetime):
    """시작 시각이 지났고(24시간 안) 아직 결과가 정해지지 않은(pending) 이벤트."""
    return [n for n in doc.nodes
            if n.kind == "event" and n.status == "pending" and timedelta(0) <= now - _kst(n.at) <= LATE_LIMIT]


def _won(v: float) -> str:
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}억"
    return f"{round(v / 1e4):,}만"


def _mix(state: dict) -> str:
    total = state["total"] or 0
    if total <= 0:
        return ""
    sums: dict[str, float] = {}
    for r in state["rows"]:
        if r["value"] is not None:
            sums[r["kind"]] = sums.get(r["kind"], 0) + r["value"]
    return " · ".join(f"{CLASS_LABEL[k]} {v / total * 100:.0f}%" for k, v in sums.items() if v > 0)


def compose(doc: PlanDoc, values: dict, event, sender: str, to: str, page_url: str) -> EmailMessage:
    """이벤트 개요·시장 예상, 그리고 대응 방법(가지마다 조건·실행할 일·실행 뒤 자산)을 글로 적은 메일."""
    branches = [n for n in doc.nodes if n.kind == "branch" and n.parent == event.id]
    at = _kst(event.at).strftime("%Y-%m-%d %H:%M")
    lines = [f"{event.title} — {at} (KST) 시작", ""]
    if event.about:
        lines += ["■ 개요", event.about, ""]
    if event.expect:
        lines += ["■ 시장 예상", event.expect, ""]
    if event.note:
        lines += ["■ 메모", event.note, ""]
    before = values.get(event.id)
    if before:
        lines += [f"■ 지금 자산 {_won(before['total'])} ({_mix(before)})", ""]
    lines.append(f"■ 대응 방법 {len(branches)}가지" if branches else "■ 대응 방법 — 아직 정하지 않았습니다")
    for i, b in enumerate(branches, 1):
        lines += ["", f"{i}. {b.title}"]
        if b.condition:
            lines.append(f"   조건: {b.condition}")
        for a in b.actions or (["매매 없이 유지"] if b.holdings is None else []):
            lines.append(f"   - {a}")
        after = values.get(b.id)
        if after:
            lines.append(f"   실행 뒤: {_won(after['total'])} ({_mix(after)})")
    if event.links:
        lines += ["", "■ 출처"] + [f"- {l.title}: {l.url}" for l in event.links]
    lines += ["", "결과가 나오면 상담에서 알려 주세요 — 실현된 가지를 표시하고 다음 계획을 이어 갑니다.",
              f"투자 계획: {page_url}", "", "※ 금액은 오늘 시세로 환산한 값입니다."]

    msg = EmailMessage()
    msg["Subject"] = f"[투자 계획] {event.title} 시작 — 대응 {len(branches)}가지"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content("\n".join(lines))
    return msg
