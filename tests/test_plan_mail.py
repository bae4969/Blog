"""이벤트 시작 메일(`app/services/plan_mail.py`) — 고르기·내용. DB·SMTP 없이 본다."""

from datetime import datetime, timedelta, timezone

from app.services import invest_plan as ip
from app.services import plan_mail

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 29, 3, 1, tzinfo=KST)


def _doc():
    return ip.PlanDoc.model_validate({"holdings": [{"kind": "cash", "name": "예금", "amount": 10_000_000}], "nodes": [
        {"id": "fomc", "kind": "event", "title": "10월 FOMC", "at": "2026-10-29T03:00:00+09:00",
         "about": "연준이 기준금리를 정한다.", "expect": "동결 우세.", "links": [{"title": "연준", "url": "https://fed.gov"}]},
        {"id": "cut", "parent": "fomc", "kind": "branch", "title": "인하", "condition": "0.25%p 이상 인하",
         "actions": ["QQQ 10주 매수"]},
        {"id": "hold", "parent": "fomc", "kind": "branch", "title": "동결"},
        {"id": "later", "parent": "cut", "kind": "event", "title": "12월 FOMC", "at": "2026-12-10T04:00:00+09:00"},
        {"id": "old", "kind": "event", "title": "지난 이벤트", "at": "2026-10-27T03:00:00+09:00"},
        {"id": "done", "kind": "event", "title": "끝난 이벤트", "at": "2026-10-29T02:00:00+09:00", "status": "realized"},
    ]})


def test_시작했고_24시간_안의_대기_이벤트만():
    assert [e.id for e in plan_mail.due_events(_doc(), NOW)] == ["fomc"]


def test_시작_전에는_안_보낸다():
    assert plan_mail.due_events(_doc(), NOW - timedelta(minutes=2)) == []


def test_내용에_개요_예상_대응_출처():
    doc = _doc()
    values = ip.valuate(doc, {}, {}, None)
    msg = plan_mail.compose(doc, values, doc.nodes[0], "me@x", "me@x", "https://blog.x/stocks/plan")
    body = msg.get_content()
    assert msg["Subject"] == "[투자 계획] 10월 FOMC 시작 — 대응 2가지"
    for part in ("2026-10-29 03:00", "연준이 기준금리를 정한다.", "동결 우세.", "조건: 0.25%p 이상 인하",
                 "- QQQ 10주 매수", "- 매매 없이 유지", "https://fed.gov", "https://blog.x/stocks/plan"):
        assert part in body, part
