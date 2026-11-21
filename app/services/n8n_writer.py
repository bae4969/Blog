"""n8n 웹훅을 통한 글 초안 작성 — 에디터(`/writer.php`)에서 대충 적은 제목·내용을 n8n 에 보내고 응답을 정리한다.

블로그 → n8n 요청 JSON:
    {
      "category_id": int | None,
      "category_name": str,
      "title": str,
      "content_html": str,
      "content_text": str,
      "is_edit": bool,
      "post_id": int | None,
      "author": str
    }

n8n → 블로그 응답 처리:
- JSON 객체(또는 1개 이상 원소를 가진 배열의 첫 객체)에 `title` 이나 `content`/`html`/`body` 가 있으면
  `clean_title` · `sanitize_for_save` 로 정화해 초안(`mode="draft"`)으로 돌려준다.
- 그 외 2xx 응답이면 백그라운드 실행/게시 요청(`mode="triggered"`)으로 알린다(`post_id`·`message` 선택).
"""

import logging
import re
from urllib.parse import urlparse

import httpx

from app.core.sanitize import clean_title, sanitize_for_save, validate_thumbnail

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 240.0
_CONNECT_TIMEOUT = 10.0


class N8nWriterError(RuntimeError):
    """n8n 웹훅 호출 실패. 화면 토스트에 그대로 보여도 되는 한국어 메시지를 담는다."""


def valid_url(url: str) -> bool:
    """http/https 스킴과 호스트가 있는 주소만 허용한다."""
    u = (url or "").strip()
    if not u:
        return False
    parsed = urlparse(u)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _strip_data_prefix(raw: str) -> str:
    """`data:image/webp;base64,...` 또는 접두사 없는 base64 를 validate_thumbnail 입력 형식으로 맞춘다."""
    val = (raw or "").strip()
    if not val:
        return ""
    m = re.match(r"^data:image/[^;]+;base64,(.+)$", val, re.S | re.I)
    return m.group(1).strip() if m else val


def _extract_object(data) -> dict | None:
    if isinstance(data, dict):
        # n8n 래핑 형태(`{"data": {...}}` 등)가 아니면 그대로, 내용 키가 없으면 내부 dict 탐색
        if any(k in data for k in ("title", "content", "html", "body", "post_id", "message", "summary", "thumbnail", "post_img")):
            return data
        for key in ("data", "result", "output", "post"):
            inner = data.get(key)
            if isinstance(inner, dict):
                return inner
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _extract_object(data[0])
    return None


async def request_draft(webhook_url: str, token: str, payload: dict) -> dict:
    """n8n 웹훅으로 글 작성을 요청하고 정화된 초안 또는 트리거 결과를 돌려준다."""
    url = (webhook_url or "").strip()
    if not valid_url(url):
        raise N8nWriterError("n8n 웹훅 주소가 설정되지 않았습니다 — 관리자 › 외부 연동에서 설정해 주세요")

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if (token or "").strip():
        headers["Authorization"] = f"Bearer {token.strip()}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT)) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        raise N8nWriterError(f"n8n 웹훅 응답이 {int(TIMEOUT_SECONDS)}초를 넘겼습니다") from None
    except httpx.HTTPError as e:
        logger.warning("n8n 웹훅 연결 실패(%s): %s", url, e)
        raise N8nWriterError(f"n8n 웹훅에 연결하지 못했습니다({type(e).__name__})") from None

    if resp.status_code >= 400:
        snippet = (resp.text or "").strip().replace("\n", " ")[:160]
        logger.warning("n8n 웹훅 오류(status=%s): %s", resp.status_code, snippet)
        raise N8nWriterError(f"n8n 웹훅이 오류({resp.status_code})를 돌려주었습니다" + (f": {snippet}" if snippet else ""))

    try:
        raw_json = resp.json()
    except ValueError:
        text_body = (resp.text or "").strip()
        if text_body:
            # 순수 텍스트/HTML 을 바로 돌려주는 단순 워크플로도 초안으로 받아 준다
            return {
                "mode": "draft",
                "title": "",
                "content": sanitize_for_save(text_body),
                "summary": "",
                "thumbnail": "",
            }
        return {"mode": "triggered", "post_id": None, "message": "n8n 에 글 작성을 요청했습니다"}

    obj = _extract_object(raw_json)
    if not obj:
        return {"mode": "triggered", "post_id": None, "message": "n8n 에 글 작성을 요청했습니다"}

    raw_title = obj.get("title")
    raw_content = obj.get("content")
    if raw_content is None:
        raw_content = obj.get("html") if obj.get("html") is not None else obj.get("body")

    if raw_title is not None or raw_content is not None:
        title = clean_title(str(raw_title or ""))
        content = sanitize_for_save(str(raw_content or ""))
        thumb_raw = obj.get("thumbnail") if obj.get("thumbnail") is not None else obj.get("post_img")
        thumbnail = validate_thumbnail(_strip_data_prefix(str(thumb_raw or "")))
        summary = str(obj.get("summary") or "").strip()[:300]
        return {
            "mode": "draft",
            "title": title,
            "content": content,
            "summary": summary,
            "thumbnail": thumbnail,
        }

    post_id = obj.get("post_id") or obj.get("id")
    try:
        post_id = int(post_id) if post_id is not None else None
    except (TypeError, ValueError):
        post_id = None
    message = str(obj.get("message") or "").strip()[:200] or "n8n 에 글 작성을 요청했습니다"
    return {"mode": "triggered", "post_id": post_id, "message": message}
