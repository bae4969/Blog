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
    view = {"values": values, "trades": ip.trades(doc, values), "stale": []}
    msg = plan_mail.compose(doc, view, doc.nodes[0], "me@x", "me@x", "https://blog.x/stocks/plan")
    body = msg.get_body(("plain",)).get_content()
    assert msg["Subject"] == "[투자 계획] 10월 FOMC 시작 — 대응 2가지"
    for part in ("2026-10-29 03:00", "연준이 기준금리를 정한다.", "동결 우세.", "조건: 0.25%p 이상 인하",
                 "메모: QQQ 10주 매수", "- 매매 없이 유지", "https://fed.gov", "https://blog.x/stocks/plan"):
        assert part in body, part


# --- 매일 점검 ---

def _cfg(on="1", at="12:00"):
    return {"plan_daily_on": on, "plan_daily_at": at}


def test_점검은_켜져_있고_시각부터_6시간_안에만():
    noon = datetime(2026, 10, 14, 12, 0, tzinfo=KST)
    assert plan_mail.daily_due(_cfg(), noon).isoformat() == "2026-10-14"
    assert plan_mail.daily_due(_cfg(), noon + timedelta(hours=6)) is not None
    assert plan_mail.daily_due(_cfg(), noon - timedelta(minutes=1)) is None
    assert plan_mail.daily_due(_cfg(), noon + timedelta(hours=6, minutes=1)) is None
    assert plan_mail.daily_due(_cfg(on=""), noon) is None
    assert plan_mail.daily_due(_cfg(at="깨짐"), noon) is None


def test_무난한_하루와_깨진_답을_가른다():
    assert plan_mail.parse_check('{"level": "none", "title": ""}')["level"] == "none"
    for broken in ("오늘은 특별한 일이 없습니다.", '{"level": "notice", "title": "x"', '{"level": "notice", "title": ""}',
                   '{"level": "모름", "title": "x"}'):
        assert plan_mail.parse_check(broken) is None, broken


def test_점검_실패_메일():
    msg = plan_mail.compose_daily_failure(NOW.date(), "Codex 로그인이 필요합니다", "me@x", "me@x", "https://blog.x/stocks/plan")
    assert msg["Subject"] == "[투자 계획·점검 실패] 2026-10-29" and "Codex 로그인이 필요합니다" in msg.get_content()


def test_접힌_가지_아래_이벤트는_시작_메일을_안_보낸다():
    doc = ip.PlanDoc.model_validate({"nodes": [
        {"id": "e1", "kind": "event", "title": "A", "at": "2026-10-20T03:00:00+09:00"},
        {"id": "b1", "parent": "e1", "kind": "branch", "title": "접힘", "status": "dropped"},
        {"id": "b2", "parent": "e1", "kind": "branch", "title": "실현", "status": "realized"},
        {"id": "e2", "parent": "b1", "kind": "event", "title": "접힌 쪽", "at": "2026-10-29T03:00:00+09:00"},
        {"id": "e3", "parent": "b2", "kind": "event", "title": "실현 쪽", "at": "2026-10-29T03:00:00+09:00"}]})
    assert [e.id for e in plan_mail.due_events(doc, NOW)] == ["e3"]


def test_알릴_답은_코드블록이든_맨_JSON이든_읽는다():
    fenced = '점검 결과:\n```json\n{"level": "urgent", "title": "FOMC 앞당김"}\n```'
    assert plan_mail.parse_check(fenced)["level"] == "urgent"
    assert plan_mail.parse_check('{"level": "notice", "title": "실적 경고"}')["title"] == "실적 경고"


def test_점검_메일_제목과_섹션_셋_출처_없음():
    check = {"level": "urgent", "title": "FOMC 임시 회의", "summary": "연준이 <임시> 회의를 열었다.",
             "impacts": ["10월 FOMC — 전제가 바뀜"], "actions": ["상담에서 가지 다시 짜기"],
             "links": [{"title": "연준", "url": "https://fed.gov"}]}
    msg = plan_mail.compose_daily(check, NOW.date(), "me@x", "me@x", "https://blog.x/stocks/plan")
    assert msg["Subject"] == "[투자 계획·긴급] FOMC 임시 회의"
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    for part in ("■ 무슨 일", "■ 예상 영향", "- 10월 FOMC — 전제가 바뀜", "■ 할 일", "- 상담에서 가지 다시 짜기",
                 "계획은 바꾸지 않았습니다", "https://blog.x/stocks/plan"):
        assert part in text
    for part in ("무슨 일", "예상 영향", "할 일", "연준이 &lt;임시&gt; 회의를 열었다.", "#FF99A4",
                 'href="https://blog.x/stocks/plan"'):
        assert part in html
    assert "fed.gov" not in text + html and "출처" not in text + html


def test_빈_섹션은_뺀다():
    text = plan_mail.daily_text({"level": "notice", "title": "x", "summary": "요지"}, NOW.date())
    assert "■ 무슨 일" in text and "예상 영향" not in text and "할 일" not in text


def test_시작_메일의_주문은_서버_매매표_잔고가_바뀐_가지는_경고():
    doc = ip.PlanDoc.model_validate({"holdings": [
        {"kind": "cash", "name": "예수금", "amount": 1_000_000, "account": "ISA"},
        {"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 10, "account": "ISA"}], "nodes": [
        {"id": "e", "kind": "event", "title": "FOMC", "at": "2026-10-29T03:00:00+09:00"},
        {"id": "a", "parent": "e", "kind": "branch", "title": "인하", "actions": ["TIGER 200 1주 매수"], "holdings": [
            {"kind": "cash", "name": "예수금", "amount": 0, "account": "ISA"},
            {"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 20, "account": "ISA"}]},
        {"id": "b", "parent": "e", "kind": "branch", "title": "동결", "holdings": []}]})
    values = ip.valuate(doc, {"102110": 100_000}, {}, None)
    body = plan_mail.compose(doc, {"values": values, "trades": ip.trades(doc, values), "stale": ["b"]}, doc.nodes[0],
                             "me@x", "me@x", "u").get_body(("plain",)).get_content()
    assert "- ISA · 매수 TIGER 200(102110) 10주 · 약 100만" in body      # 메모의 "1주"가 아니라 매매표의 10주
    assert "- ISA · 예수금 감소 100만" in body and "메모: TIGER 200 1주 매수" in body
    assert "잔고가 바뀌어 이 가지의 매매를 다시 짜야 합니다" in body


def test_점검_글의_링크는_지운다():
    # AI 가 본문에 섞은 링크가 메일에 `[로이터](https://…)` 날 글자로 찍혔다(2026-10-15·16 운영)
    reply = ('{"level": "urgent", "title": "코스피 급락", "summary": "사이드카가 발동했습니다. '
             '[연합뉴스](https://www.yna.co.kr/view/AKR1) 미국 물가가 높았습니다 https://x.com/a",'
             ' "impacts": ["TIGER 200 — 손실 [로이터](https://r.com/1)"], "actions": ["상담에서 점검"]}')
    check = plan_mail.parse_check(reply)
    assert check["summary"] == "사이드카가 발동했습니다. 미국 물가가 높았습니다"
    assert check["impacts"] == ["TIGER 200 — 손실"] and check["actions"] == ["상담에서 점검"]


def test_보내는_메일에_날짜와_메시지_ID():
    from app.api import plan_v1
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): pass
        def send_message(self, msg): sent.append(msg)

    import smtplib
    orig, smtplib.SMTP_SSL = smtplib.SMTP_SSL, FakeSMTP
    try:
        msg = plan_mail.compose_daily_failure(NOW.date(), "x", "me@naver.com", "me@naver.com", "https://blog.x")
        plan_v1._send({"smtp_host": "h", "smtp_port": "465", "smtp_user": "me@naver.com", "smtp_password": "p"}, msg)
    finally:
        smtplib.SMTP_SSL = orig
    assert sent[0]["Date"].endswith("+0900") and sent[0]["Message-ID"].endswith("@naver.com>")


def test_AI_글의_마크다운은_정화한_HTML_로():
    # 표·목록이 날 글자로 보였다(2026-10-17 사용자) — 그리되 웹 검색이 섞인 글이라 스크립트·이벤트 속성은 지운다
    html = plan_mail.md_html("**굵게**\n\n| 종목 | 수량 |\n|---|---|\n| TIGER 200 | 3주 |\n\n- 하나\n- 둘\n\n"
                             '<script>alert(1)</script><img src=x onerror=alert(1)> [x](javascript:alert(1))')
    assert "<strong>굵게</strong>" in html and "<table style=" in html and "<td style=" in html and ">TIGER 200</td>" in html
    assert "<ul style=" in html and "<li style=" in html
    assert "<script" not in html and "onerror" not in html and "javascript:" not in html and "<img" not in html
    assert plan_mail.md_html("한 **줄**") == "한 <strong>줄</strong>"


def test_이벤트_시작_메일도_HTML_을_함께_보낸다():
    msg = plan_mail.compose(_doc(), {"values": {}}, _doc().nodes[0], "me@x", "me@x", "https://blog.x/stocks/plan")
    html = msg.get_body(("html",)).get_content()
    for part in ("10월 FOMC", "개요", "연준이 기준금리를 정한다.", "대응 1 · 인하", "0.25%p 이상 인하", "대응 2 · 동결",
                 'href="https://fed.gov"', 'href="https://blog.x/stocks/plan"'):
        assert part in html, part


def test_이벤트_메일_본문은_상담_기록에도_같은_글로():
    # 보낸 뒤 상담 기록에 남겨 상담 AI 가 이어 다룬다(2026-10-17 사용자: 연속성) — 메일 글 본문과 같고, 출처·안내 꼬리는 뺀다
    doc = _doc()
    body = plan_mail.event_text(doc, {"values": {}}, doc.nodes[0])
    mail = plan_mail.compose(doc, {"values": {}}, doc.nodes[0], "me@x", "me@x", "u").get_body(("plain",)).get_content()
    assert body.startswith("10월 FOMC — 2026-10-29 03:00 (KST) 시작") and "1. 인하" in body and "조건: 0.25%p 이상 인하" in body
    assert mail.startswith(body) and "■ 출처" in mail and "■ 출처" not in body and "fed.gov" not in body


def test_부채가_있으면_메일_총액은_순자산():
    doc = ip.PlanDoc.model_validate({
        "holdings": [{"kind": "other", "name": "전세보증금", "amount": 150_000_000, "account": "주거"}],
        "debts": [{"name": "전세대출", "balance": 100_000_000}],
        "nodes": [{"id": "e", "kind": "event", "title": "갱신", "at": "2026-10-29T03:00:00+09:00"}]})
    values = ip.valuate(doc, {}, {}, None)
    body = plan_mail.event_text(doc, {"values": values}, doc.nodes[0])
    assert "■ 지금 자산 순자산 5,000만(자산 1.50억 − 부채 1.00억)" in body
