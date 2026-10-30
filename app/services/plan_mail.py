"""투자 계획 메일 — 이벤트 시작 메일과 매일 점검 메일의 고르기·내용. **DB 도 SMTP 도 모른다.**

보내는 일(1분마다 훑기·중복 막기·SMTP·codex)은 [plan_v1](../api/plan_v1.py) 의 `mail_loop` 가 한다.
"""

import json
import re
from datetime import date, datetime, timedelta
from email.message import EmailMessage

from app.services.invest_plan import GROUP_LABEL, PlanDoc, _kst, on_dropped_path

#: 시작 시각이 이만큼 지난 이벤트는 보내지 않는다 — 앱이 오래 꺼져 있다 켜졌을 때 옛 알림이 몰려오지 않게.
LATE_LIMIT = timedelta(hours=24)


def due_events(doc: PlanDoc, now: datetime):
    """시작 시각이 지났고(24시간 안) 아직 결과가 정해지지 않은(pending) 이벤트 — 접힌 가지 아래 것은 뺀다."""
    return [n for n in doc.nodes
            if n.kind == "event" and n.status == "pending" and timedelta(0) <= now - _kst(n.at) <= LATE_LIMIT
            and not on_dropped_path(doc, n)]


def _won(v: float) -> str:
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}억"
    return f"{round(v / 1e4):,}만"


def _worth(state: dict) -> str:
    """총액 — 부채가 있으면 순자산(자산 − 부채)으로(2026-10-17, 주거를 전액으로 적게 바꿨다)."""
    net = state.get("net", state["total"])
    return _won(state["total"]) if abs(net - state["total"]) < 1 else f"순자산 {_won(net)}(자산 {_won(state['total'])} − 부채 {_won(state['total'] - net)})"


def _mix(state: dict) -> str:
    total = state["total"] or 0
    if total <= 0:
        return ""
    sums: dict[str, float] = {}
    for r in state["rows"]:
        if r["value"] is not None:
            sums[r["group"]] = sums.get(r["group"], 0) + r["value"]
    return " · ".join(f"{GROUP_LABEL[k]} {v / total * 100:.0f}%" for k, v in sums.items() if v > 0)


def _trade_line(t: dict) -> str:
    """매매표 한 줄 — 화면 `tradeTable` 과 같은 말(현금은 증가·감소, 종목은 매수·매도 + 수량)."""
    acc = t["account"] or "—"
    if t.get("kind") == "cash" or t["qty"] is None:
        return f"{acc} · {t['name']} {'증가' if t['side'] == 'buy' else '감소'} {_won(t['value'] or 0)}"
    code = f"({t['code']})" if t.get("code") and t["code"] != t["name"] else ""
    qty = f"{t['qty']:,.4f}".rstrip("0").rstrip(".")
    value = f" · 약 {_won(t['value'])}" if t["value"] is not None else ""
    unit = t.get("quantity_unit") or "주"
    return f"{acc} · {'매수' if t['side'] == 'buy' else '매도'} {t['name']}{code} {qty}{unit}{value}"


def event_text(doc: PlanDoc, view: dict, event) -> str:
    """이벤트 시작 메일의 본문 — 개요·시장 예상·메모·지금 자산·대응 방법(가지마다 조건·매매표·실행 뒤 자산).
    메일(`compose`)과 상담 기록(보낸 뒤 남겨 상담 AI 가 이어 다룬다)이 같은 글을 쓴다.

    주문은 **서버 매매표**(`view["trades"]`)로 적는다 — 화면과 같은 출처다. AI 가 쓴 `actions` 는 메모로만 붙인다
    (둘이 따로 놀아 메일과 화면의 수량이 다를 수 있었다, 2026-10-14 검토). 잔고가 바뀐 가지는 매매표 대신 경고.
    """
    values, trades, stale = view["values"], view.get("trades", {}), set(view.get("stale", ()))
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
        lines += [f"■ 지금 자산 {_worth(before)} ({_mix(before)})", ""]
    lines.append(f"■ 대응 방법 {len(branches)}가지" if branches else "■ 대응 방법 — 아직 정하지 않았습니다")
    for i, b in enumerate(branches, 1):
        lines += ["", f"{i}. {b.title}"]
        if b.condition:
            lines.append(f"   조건: {b.condition}")
        if b.id in stale:
            lines.append("   ⚠ 잔고가 바뀌어 이 가지의 매매를 다시 짜야 합니다 — 상담에서 정해 주세요")
        elif b.holdings is None:
            lines.append("   - 매매 없이 유지")
        else:
            lines += [f"   - {_trade_line(t)}" for t in trades.get(b.id, [])] or ["   - 매매 없음"]
        if b.actions:
            lines.append(f"   메모: {' / '.join(b.actions)}")
        after = values.get(b.id)
        if after:
            lines.append(f"   실행 뒤: {_worth(after)} ({_mix(after)})")
    return "\n".join(lines)


def compose(doc: PlanDoc, view: dict, event, sender: str, to: str, page_url: str) -> EmailMessage:
    """이벤트 시작 메일 — 본문(`event_text`) + 출처·안내, HTML 판(`event_html`)을 함께."""
    branches = [n for n in doc.nodes if n.kind == "branch" and n.parent == event.id]
    lines = [event_text(doc, view, event)]
    if event.links:
        lines += ["", "■ 출처"] + [f"- {l.title}: {l.url}" for l in event.links]
    lines += ["", "결과가 나오면 상담에서 알려 주세요 — 실현된 가지를 표시하고 다음 계획을 이어 갑니다.",
              f"투자 계획: {page_url}", "", "※ 금액은 오늘 시세로 환산한 값입니다."]

    msg = EmailMessage()
    msg["Subject"] = f"[투자 계획] {event.title} 시작 — 대응 {len(branches)}가지"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content("\n".join(lines))
    msg.add_alternative(event_html(doc, view, event, page_url), subtype="html")
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


#: 점검 글의 링크 — 마크다운 `[이름](url)` 과 맨 URL. 매일 점검 메일엔 출처를 넣지 않는데(사용자 지시) AI 가 상담 답처럼
#: 본문에 링크를 섞어, 메일에 `[로이터](https://…)` 가 날 글자로 찍혔다(2026-10-15·16 운영).
_LINK = re.compile(r"\s*(\[[^\]]*\]\(\s*https?://[^)]*\)|https?://\S+)")


def _unlink(v):
    if isinstance(v, list):
        return [_unlink(x) for x in v]
    return re.sub(r" {2,}", " ", _LINK.sub("", v)).strip() if isinstance(v, str) else v


def parse_check(reply: str) -> dict | None:
    """AI 답 → 점검 결과(`level` 이 none·notice·urgent). **형식이 깨졌으면 None** — 무난한 하루(none)와 구분해
    점검 실패로 알린다(둘이 같으면 며칠째 실패해도 "조용한 날"로 보였다, 2026-10-14 검토)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", reply, re.S)
    raw = m.group(1) if m else reply[reply.find("{"):reply.rfind("}") + 1]
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("level") not in ("none", *LEVEL_LABEL):
        return None
    if data["level"] != "none" and not data.get("title"):
        return None
    return {k: _unlink(v) for k, v in data.items()}


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


# ── 마크다운 → 메일 HTML (2026-10-17 사용자: "md 표가 날것으로 보여서 보기 힘들어") ─────────────
#: 메일 앱은 <style> 을 버리는 일이 많아 태그마다 인라인 스타일을 붙인다.
_MD_STYLE = {
    "p": "margin:0 0 8px",
    "ul": "margin:0 0 8px;padding-left:20px", "ol": "margin:0 0 8px;padding-left:20px", "li": "margin:2px 0",
    "table": "border-collapse:collapse;margin:0 0 8px;font-size:13px",
    "th": f"padding:5px 9px;border:1px solid {_C['border']};background:#323232;text-align:left;white-space:nowrap",
    "td": f"padding:5px 9px;border:1px solid {_C['border']};text-align:left;vertical-align:top",
    "code": "padding:1px 4px;border-radius:4px;background:#323232;font-family:Consolas,Menlo,monospace;font-size:13px",
    "pre": "margin:0 0 8px;padding:8px 10px;border-radius:6px;background:#1C1C1C;white-space:pre-wrap",
    "blockquote": f"margin:0 0 8px;padding-left:10px;border-left:3px solid #4A4A4A;color:{_C['muted']}",
    "h1": "margin:12px 0 6px;font-size:15px", "h2": "margin:12px 0 6px;font-size:15px",
    "h3": "margin:12px 0 6px;font-size:15px", "h4": "margin:12px 0 6px;font-size:15px",
    "a": f"color:{_C['accent']}", "hr": f"border:0;border-top:1px solid {_C['border']}",
}
_MD_TAGS = set(_MD_STYLE) | {"strong", "em", "b", "i", "del", "br", "thead", "tbody", "tr"}
_MD_OPEN = re.compile(r"<(%s)\b" % "|".join(sorted(_MD_STYLE, key=len, reverse=True)))


def md_html(text: str) -> str:
    """AI 글(마크다운) → 메일용 HTML. **nh3 로 정화한 뒤** 스타일만 붙인다 — 웹 검색이 섞인 글이라 태그·속성은 허용 목록만.
    문단 하나뿐이면 <p> 를 벗긴다 — 목록 칸·"조건 …" 줄처럼 앞 글자와 한 줄로 이어지는 자리라서."""
    import markdown
    import nh3
    raw = markdown.markdown(str(text), extensions=["tables", "sane_lists", "nl2br"])
    html = nh3.clean(raw, tags=_MD_TAGS, attributes={"a": {"href"}}, url_schemes={"http", "https"})
    html = _MD_OPEN.sub(lambda m: f'<{m[1]} style="{_MD_STYLE[m[1]]}"', html).strip()
    head = f'<p style="{_MD_STYLE["p"]}">'
    if html.startswith(head) and html.count("<p ") == 1 and html.endswith("</p>"):
        html = html[len(head):-4]
    return html


def _card(title: str, body: str) -> str:
    return (f'<tr><td style="padding:16px 20px;background:{_C["surface"]};border-radius:8px">'
            f'<div style="margin:0 0 8px;font-size:12px;font-weight:600;color:{_C["muted"]}">{title}</div>'
            f'<div style="line-height:1.7;color:{_C["text"]}">{body}</div></td></tr>'
            f'<tr><td style="height:10px;line-height:10px;font-size:0">&nbsp;</td></tr>')


def _bullets(rows: list[str], tone: str) -> str:
    """• 줄들 — 각 줄은 이미 HTML 이다."""
    body = "".join(
        f'<tr><td valign="top" style="width:14px;padding:3px 0;color:{tone}">•</td>'
        f'<td style="padding:3px 0;line-height:1.6;color:{_C["text"]}">{x}</td></tr>' for x in rows)
    return f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">{body}</table>'


def _frame(badge: str, tone: str, kicker: str, title: str, cards: str, page_url: str, foot: str) -> str:
    """메일 한 통의 틀 — 블로그 어두운 테마(배지·작은 머리말·제목 → 카드들 → [투자 계획 열기] · 꼬리말)."""
    from html import escape
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
        f'font-size:12px;font-weight:600;color:{tone}">{escape(badge)}</span>'
        f'<span style="margin-left:8px;font-size:12px;color:{_C["dim"]}">{escape(kicker)}</span>'
        f'<h1 style="margin:10px 0 0;font-size:20px;line-height:1.4;font-weight:700;color:{_C["text"]}">'
        f'{escape(title)}</h1></td></tr>'
        + cards +
        f'<tr><td style="padding:10px 4px 0">'
        f'<a href="{escape(page_url)}" style="display:inline-block;padding:10px 18px;border-radius:8px;background:{_C["accent"]};'
        f'color:{_C["accent_text"]};font-weight:600;text-decoration:none">투자 계획 열기</a>'
        f'<p style="margin:14px 0 0;font-size:12px;line-height:1.6;color:{_C["dim"]}">{foot}</p></td></tr>'
        f'</table></td></tr></table></body></html>')


def daily_html(check: dict, day: date, page_url: str) -> str:
    tone = _C[check["level"]]
    cards = "".join(_card(title, md_html(rows[0]) if i == 0 else _bullets([md_html(x) for x in rows], tone))
                    for i, (title, rows) in enumerate(_sections(check)))
    return _frame(LEVEL_LABEL[check["level"]], tone, f"투자 계획 · {day:%Y-%m-%d} 점검", str(check["title"]), cards,
                  page_url, "계획은 바꾸지 않았습니다 — 반영하려면 상담에서 말씀해 주세요.")


def event_html(doc: PlanDoc, view: dict, event, page_url: str) -> str:
    """이벤트 시작 메일의 HTML — 글 버전(`compose`)과 같은 내용을 카드로. AI 가 쓴 칸은 마크다운으로 그린다."""
    from html import escape
    values, trades, stale = view["values"], view.get("trades", {}), set(view.get("stale", ()))
    branches = [n for n in doc.nodes if n.kind == "branch" and n.parent == event.id]
    tone = _C["accent"]
    cards = ""
    for title, text in (("개요", event.about), ("시장 예상", event.expect), ("메모", event.note)):
        if text:
            cards += _card(title, md_html(text))
    before = values.get(event.id)
    if before:
        cards += _card("지금 자산", f'<b>{escape(_worth(before))}</b> <span style="color:{_C["muted"]}">{escape(_mix(before))}</span>')
    for i, b in enumerate(branches, 1):
        rows = []
        if b.condition:
            rows.append(f'<span style="color:{_C["muted"]}">조건</span> {md_html(b.condition)}')
        if b.id in stale:
            rows.append(f'<span style="color:{_C["urgent"]}">⚠ 잔고가 바뀌어 이 가지의 매매를 다시 짜야 합니다 — 상담에서 정해 주세요</span>')
        elif b.holdings is None:
            rows.append("매매 없이 유지")
        else:
            rows += [escape(_trade_line(t)) for t in trades.get(b.id, [])] or ["매매 없음"]
        if b.actions:
            rows.append(f'<span style="color:{_C["muted"]}">메모</span> ' + " / ".join(md_html(a) for a in b.actions))
        after = values.get(b.id)
        if after:
            rows.append(f'<span style="color:{_C["muted"]}">실행 뒤</span> {escape(_worth(after))} · {escape(_mix(after))}')
        cards += _card(f"대응 {i} · {escape(b.title)}", _bullets(rows, tone))
    if not branches:
        cards += _card("대응 방법", "아직 정하지 않았습니다")
    if event.links:
        cards += _card("출처", _bullets([f'<a href="{escape(l.url)}" style="color:{tone}">{escape(l.title)}</a>'
                                        for l in event.links if l.url.startswith(("http://", "https://"))], tone))
    at = _kst(event.at).strftime("%Y-%m-%d %H:%M")
    return _frame("시작", tone, f"투자 계획 · {at} (KST)", event.title, cards, page_url,
                  "결과가 나오면 상담에서 알려 주세요 — 실현된 가지를 표시하고 다음 계획을 이어 갑니다.<br>"
                  "※ 금액은 오늘 시세로 환산한 값입니다.")


def compose_daily(check: dict, day: date, sender: str, to: str, page_url: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"[투자 계획·{LEVEL_LABEL[check['level']]}] {check['title']}"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(daily_text(check, day) + "\n\n계획은 바꾸지 않았습니다 — 반영하려면 상담에서 말씀해 주세요.\n"
                    + f"투자 계획: {page_url}")
    msg.add_alternative(daily_html(check, day, page_url), subtype="html")
    return msg


def compose_daily_failure(day: date, reason: str, sender: str, to: str, page_url: str) -> EmailMessage:
    """점검을 못 한 날 — 하루 한 번(차지한 그날 몫)만 간다. 조용한 날과 헷갈리지 않게 따로 알린다."""
    msg = EmailMessage()
    msg["Subject"] = f"[투자 계획·점검 실패] {day:%Y-%m-%d}"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(f"{day:%Y-%m-%d} 매일 점검을 하지 못했습니다.\n\n사유: {reason}\n\n"
                    f"Codex 로그인(관리자 › 외부 연동)을 확인해 주세요. 내일 같은 시각에 다시 합니다.\n투자 계획: {page_url}")
    return msg
