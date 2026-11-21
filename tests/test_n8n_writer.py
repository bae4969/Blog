"""n8n 웹훅 글쓰기(`app/services/n8n_writer.py`) 단위 테스트."""

import asyncio
import json

import httpx
import pytest

from app.services import n8n_writer


def test_웹훅_주소_검사():
    assert n8n_writer.valid_url("https://n8n.onulkit.com/webhook/blog-writer")
    assert n8n_writer.valid_url("http://ix-n8n-n8n-1:5678/webhook/test")
    assert not n8n_writer.valid_url("")
    assert not n8n_writer.valid_url("ftp://example.com/hook")
    assert not n8n_writer.valid_url("/relative/path")


def _patch_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_초안_응답과_HTML_정화_및_토큰_헤더(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={
            "title": "  <b>완성 제목</b>  ",
            "content": '<h2>소제목</h2><p>본문</p><script>alert(1)</script>',
            "summary": "요약입니다",
            "thumbnail": "data:image/webp;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA=",
        })

    _patch_client(monkeypatch, handler)
    res = asyncio.run(n8n_writer.request_draft(
        "https://n8n.onulkit.com/webhook/blog",
        "my-secret-token",
        {"title": "초안", "content_text": "대충 메모"},
    ))
    assert seen["auth"] == "Bearer my-secret-token"
    assert seen["body"]["title"] == "초안"
    assert res["mode"] == "draft"
    assert res["title"] == "완성 제목"
    assert "<h2>소제목</h2>" in res["content"]
    assert "<script>" not in res["content"]
    assert res["summary"] == "요약입니다"
    assert res["thumbnail"].startswith("UklGR")


def test_배열_응답도_첫_항목에서_초안_추출(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"title": "배열 제목", "html": "<p>배열 본문</p>"}])

    _patch_client(monkeypatch, handler)
    res = asyncio.run(n8n_writer.request_draft("https://n8n.onulkit.com/webhook/blog", "", {"title": "a"}))
    assert res["mode"] == "draft"
    assert res["title"] == "배열 제목"
    assert res["content"] == "<p>배열 본문</p>"


def test_비동기_트리거_응답(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"ok": True, "post_id": 321, "message": "게시 완료"})

    _patch_client(monkeypatch, handler)
    res = asyncio.run(n8n_writer.request_draft("https://n8n.onulkit.com/webhook/blog", "", {"title": "a"}))
    assert res == {"mode": "triggered", "post_id": 321, "message": "게시 완료"}


def test_웹훅_오류는_N8nWriterError(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="workflow failed")

    _patch_client(monkeypatch, handler)
    with pytest.raises(n8n_writer.N8nWriterError) as exc:
        asyncio.run(n8n_writer.request_draft("https://n8n.onulkit.com/webhook/blog", "", {"title": "a"}))
    assert "500" in str(exc.value)
