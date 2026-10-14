"""투자 계획 메일 — 이벤트 시작 메일과 매일 점검 메일의 고르기·내용. **DB 도 SMTP 도 모른다.**

보내는 일(1분마다 훑기·중복 막기·SMTP·codex)은 [plan_v1](../api/plan_v1.py) 의 `mail_loop` 가 한다.
"""

import json
import re
from datetime import date, datetime, timedelta
from email.message import EmailMessage

from app.services.invest_plan import GROUP_LABEL, PlanDoc, _kst

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
            sums[r["group"]] = sums.get(r["group"], 0) + r["value"]
    return " · ".join(f"{GROUP_LABEL[k]} {v / total * 100:.0f}%" for k, v in sums.items() if v > 0)


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


# ---------------------------------------------------------------------------
# 매일 점검(2026-10-14) — 정해진 시각에 AI 가 계획에 영향을 줄 이슈를 찾고, 있을 때만 메일을 보낸다.
# ---------------------------------------------------------------------------

#: 점검 시각이 이만큼 지나면 그날은 건너뛴다 — 그 시각에 재배포 중이었으면 켜진 뒤 따라잡되, 한밤에 옛 점검을 돌리지 않게.
DAILY_LATE = timedelta(hours=6)
LEVEL_LABEL = {"notice": "점검", "urgent": "긴급"}


def daily_due(cfg: dict, now: datetime) -> date | None:
    """오늘 점검할 때면 오늘 날짜(KST). 꺼져 있거나 시각 전·6시간 넘게 지났으면 None."""
    if cfg["plan_daily_on"] != "1":
        return None
    try:
        h, m = (int(x) for x in cfg["plan_daily_at"].split(":"))
    except ValueError:
        return None
    slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return now.date() if timedelta(0) <= now - slot <= DAILY_LATE else None


def parse_check(reply: str) -> dict | None:
    """AI 답 → 알릴 점검 결과. 무난한 하루(none)거나 형식이 깨졌으면 None — 메일을 보내지 않는다."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", reply, re.S)
    raw = m.group(1) if m else reply[reply.find("{"):reply.rfind("}") + 1]
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("level") not in LEVEL_LABEL or not data.get("title"):
        return None
    return data


def _sections(check: dict) -> list[tuple[str, list[str]]]:
    """(제목, 줄들) — 무슨 일 · 예상 영향 · 할 일. 빈 섹션은 뺀다."""
    out = [("무슨 일", [str(check["summary"])] if check.get("summary") else []),
           ("예상 영향", [str(x) for x in check.get("impacts") or []]),
           ("할 일", [str(x) for x in check.get("actions") or []])]
    return [(t, rows) for t, rows in out if rows]


def daily_text(check: dict, day: date) -> str:
    """글 본문 — HTML 을 못 그리는 메일 앱용이자 상담 기록에 남기는 글(다음 상담에서 AI 가 이어 다루게)."""
    lines = [f"{day:%Y-%m-%d} 점검 — {check['title']}"]
    for i, (title, rows) in enumerate(_sections(check)):
        lines += ["", f"■ {title}"] + (rows if i == 0 else [f"- {x}" for x in rows])
    return "\n".join(lines)


#: 블로그 테마(public/css/common.css 의 --bae-*) — 메일 앱이 <style> 을 버리는 일이 많아 값을 인라인으로 넣는다.
_C = {"bg": "#202020", "surface": "#2B2B2B", "border": "#3A3A3A", "text": "#FFFFFF", "muted": "#C7C7C7",
      "dim": "#9A9A9A", "accent": "#C4B5FD", "accent_text": "#000000", "notice": "#93C5FD", "urgent": "#FF99A4"}
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Apple SD Gothic Neo','Malgun Gothic',sans-serif"


def daily_html(check: dict, day: date, page_url: str) -> str:
    from html import escape
    tone = _C[check["level"]]
    blocks = []
    for i, (title, rows) in enumerate(_sections(check)):
        if i == 0:
            body = f'<p style="margin:0;line-height:1.7;color:{_C["text"]}">{escape(rows[0])}</p>'
        else:
            body = "".join(
                f'<tr><td valign="top" style="width:14px;padding:3px 0;color:{tone}">•</td>'
                f'<td style="padding:3px 0;line-height:1.6;color:{_C["text"]}">{escape(x)}</td></tr>' for x in rows)
            body = f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">{body}</table>'
        blocks.append(
            f'<tr><td style="padding:16px 20px;background:{_C["surface"]};border-radius:8px">'
            f'<div style="margin:0 0 8px;font-size:12px;font-weight:600;color:{_C["muted"]}">{title}</div>{body}</td></tr>'
            f'<tr><td style="height:10px;line-height:10px;font-size:0">&nbsp;</td></tr>')
    return (
        f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"></head>'
        f'<body style="margin:0;padding:0;background:{_C["bg"]}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{_C["bg"]}" style="background:{_C["bg"]}">'
        f'<tr><td align="center" style="padding:24px 12px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="max-width:600px;font-family:{_FONT};font-size:14px;color:{_C["text"]};word-break:keep-all">'
        f'<tr><td style="padding:0 4px 16px">'
        f'<span style="display:inline-block;padding:2px 10px;border:1px solid {tone};border-radius:999px;'
        f'font-size:12px;font-weight:600;color:{tone}">{LEVEL_LABEL[check["level"]]}</span>'
        f'<span style="margin-left:8px;font-size:12px;color:{_C["dim"]}">투자 계획 · {day:%Y-%m-%d} 점검</span>'
        f'<h1 style="margin:10px 0 0;font-size:20px;line-height:1.4;font-weight:700;color:{_C["text"]}">'
        f'{escape(str(check["title"]))}</h1></td></tr>'
        + "".join(blocks) +
        f'<tr><td style="padding:10px 4px 0">'
        f'<a href="{escape(page_url)}" style="display:inline-block;padding:10px 18px;border-radius:8px;background:{_C["accent"]};'
        f'color:{_C["accent_text"]};font-weight:600;text-decoration:none">투자 계획 열기</a>'
        f'<p style="margin:14px 0 0;font-size:12px;line-height:1.6;color:{_C["dim"]}">'
        f'계획은 바꾸지 않았습니다 — 반영하려면 상담에서 말씀해 주세요.</p></td></tr>'
        f'</table></td></tr></table></body></html>')


def compose_daily(check: dict, day: date, sender: str, to: str, page_url: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"[투자 계획·{LEVEL_LABEL[check['level']]}] {check['title']}"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(daily_text(check, day) + "\n\n계획은 바꾸지 않았습니다 — 반영하려면 상담에서 말씀해 주세요.\n"
                    + f"투자 계획: {page_url}")
    msg.add_alternative(daily_html(check, day, page_url), subtype="html")
    return msg
