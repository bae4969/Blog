"""저장용 정화 — 출력이 보여 주는 서식은 저장에서도 지우지 않는다.

2026-09-25 에 자동 포스팅(n8n)을 쓰기 API 로 옮기려다 걸렸다. 저장 목록이 출력 목록보다 좁아
소제목(`h2`·`h3`)·강조(`b`·`span style`)가 전부 지워지고, 소제목 글자가 문단에 붙었다.
"""

from app.core.sanitize import make_summary, sanitize_for_save

#: 자동 포스팅 본문과 같은 모양(238번에서 줄였다).
N8N_POST = (
    '<h2>[분석] ECB의 매파적 선회</h2>'
    '<p>기준금리를 <span style="color: #d32f2f;"><b>2.5%</b></span>로 인상했습니다.</p>'
    '<h3>에너지 쇼크</h3>'
    '<blockquote>인용</blockquote>'
    '<ul><li>첫째</li><li>둘째</li></ul>'
)


def test_자동_포스팅_서식이_그대로_남는다():
    assert sanitize_for_save(N8N_POST) == N8N_POST


def test_위험한_것은_여전히_지운다():
    out = sanitize_for_save(
        '<p style="position:fixed" onclick="x()">a</p><script>alert(1)</script>'
        '<a href="data:text/html,x">b</a><iframe src="https://x"></iframe>'
    )
    assert "style" not in out            # span 이 아닌 곳의 style
    assert "onclick" not in out
    assert "<script" not in out and "alert" not in out
    assert "<iframe" not in out
    assert 'href="#' in out              # href 의 data: 는 `#` 으로


def test_요약은_태그를_지우고_200자로_자른다():
    """쓰기 API 가 받은 요약도 본문 요약과 같은 손질을 거친다."""
    assert make_summary("<b>금리</b>  인상\n발표") == "금리 인상 발표"
    assert len(make_summary("가" * 300)) == 200
