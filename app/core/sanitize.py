"""본문 HTML 정화 — PHP 정책을 옮긴 것. **저장용과 출력용이 다르다.**

PHP 는 두 곳에서 정화한다:
  · 저장할 때 — `Models/Post.php::create` (좁은 목록)
  · 보여줄 때 — `Core/HtmlSanitizer.php` (넓은 목록)

저장 목록에는 `h1~h6`·`span`·`u`·`hr` 이 없는데 기존 글에는 헤딩이 들어 있다. 즉 지금
DB 의 글 중 일부는 **현재 저장 정책보다 넓은 HTML** 을 갖고 있다(정책이 바뀌었거나 다른
경로로 들어왔다). 그래서 출력 시 정화를 없애면 안 된다 — 저장 때 걸렀다고 믿을 수 없다.

정책이 PHP 와 다르면 같은 글이 두 스택에서 다르게 보인다 — 목록을 바꿀 때는 PHP 쪽도
함께 고칠 것.
"""

import re
from base64 import b64decode
from binascii import Error as BinasciiError
from html import escape, unescape

import nh3
from app.core import thumbnail

#: PHP `HTML.Allowed` 와 같은 목록.
_TAGS: set[str] = {
    "p", "br", "strong", "b", "em", "i", "u", "span",
    "a", "ul", "ol", "li", "blockquote", "pre", "code",
    "h1", "h2", "h3", "h4", "h5", "h6", "img", "hr",
}

#: 태그별 허용 속성. PHP 의 `span[style]`·`a[href|title|target]`·`img[...]` 와 같다.
_ATTRS: dict[str, set[str]] = {
    "span": {"style"},
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
}

#: 허용 URL 스킴. `data:` 는 본문에 base64 이미지가 들어 있어 필요하다(썸네일 규약).
_SCHEMES: set[str] = {"http", "https", "data"}


def sanitize(html: str | None) -> str:
    """허용 목록 밖의 태그·속성·스킴을 제거한다.

    nh3(Rust ammonia)는 허용 목록 방식이라 새로운 우회 기법이 나와도 기본이 안전하다.
    `link_rel` 로 외부 링크에 noopener 를 붙인다 — `target=_blank` 를 허용하고 있어
    탭 탈취(reverse tabnabbing)를 막아야 한다. PHP 쪽에는 없는 보강이다.
    """
    if not html:
        return ""
    return nh3.clean(
        html,
        tags=_TAGS,
        attributes=_ATTRS,
        url_schemes=_SCHEMES,
        link_rel="noopener noreferrer",
    )


def has_image(html: str | None) -> bool:
    """본문에 이미지가 있나 — 없을 때만 썸네일을 끼워 넣는다(PHP 와 같은 규칙).

    PHP 는 `stripos($content, '<img') === false` 로 본다. 정화 **전** 원문 기준이면
    제거될 태그까지 세므로, 여기서는 정화된 결과를 받아 판단한다.
    """
    return "<img" in (html or "").lower()


# ── 저장용 ──────────────────────────────────────────────────────────
#: PHP `Models/Post.php::create` 의 `HTML.Allowed`. 출력용보다 **좁다**.
_SAVE_TAGS: set[str] = {
    "p", "br", "strong", "em", "s", "ul", "ol", "li",
    "a", "img", "code", "pre", "blockquote",
}
_SAVE_ATTRS: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
}

#: `href="data:..."` 를 막는다. 이미지(`img src`)의 data URI 는 그대로 둔다 —
#: 본문에 base64 이미지를 넣는 규약이 있어서다. PHP 도 href 만 골라 `#` 으로 바꾼다.
_HREF_DATA = re.compile(r'(href\s*=\s*["\'])data:[^"\']*(["\'\s>])', re.IGNORECASE)

#: 요약을 만들 때 먼저 걷어낼 이미지 태그.
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

#: 썸네일 base64 최대 길이(500KB)와 허용 문자 — PHP `validateThumbnail` 과 같다.
_THUMB_MAX = 500 * 1024
_THUMB_CHARS = re.compile(r"^[A-Za-z0-9+/=]+$")


def sanitize_for_save(html: str | None) -> str:
    """글을 저장하기 전 정화. 출력용보다 좁은 목록을 쓴다(PHP 와 동일).

    ⚠️ 저장 목록이 좁다고 출력 정화를 생략하면 안 된다 — 옛 글은 더 넓은 HTML 을 갖고 있다.
    """
    if not html:
        return ""
    cleaned = nh3.clean(
        html,
        tags=_SAVE_TAGS,
        attributes=_SAVE_ATTRS,
        url_schemes=_SCHEMES,
        link_rel="noopener noreferrer",
    )
    return _HREF_DATA.sub(r"\1#\2", cleaned)


def make_summary(clean_html: str, limit: int = 200) -> str:
    """목록에 뿌릴 요약. **정화된 본문**에서 뽑는다(PHP 와 같은 순서).

    이미지 제거 → 태그 제거 → 엔티티 디코드 → 공백 정규화 → 앞에서 `limit` 자.
    순서를 바꾸면 결과가 달라진다(예: 태그를 먼저 지우면 `<img>` 의 alt 가 섞여 든다).
    """
    tmp = _IMG_TAG.sub("", clean_html)
    tmp = re.sub(r"<[^>]*>", "", tmp)
    tmp = unescape(tmp)
    tmp = re.sub(r"\s+", " ", tmp).strip()
    return tmp[:limit]


def clean_title(raw: str | None) -> str:
    """제목 — 태그를 벗기고 그대로 저장한다.

    ⚠️ PHP 는 여기서 `htmlspecialchars` 까지 걸어 **DB 에 `&amp;` 형태로** 넣는다.
    화면에서 Jinja 가 다시 이스케이프하면 이중 인코딩(`&amp;amp;`)이 되므로 여기서는
    태그만 벗긴다. 기존 글과 표시가 어긋나 보이면 이 지점을 먼저 의심할 것.
    """
    if not raw:
        return ""
    return re.sub(r"<[^>]*>", "", raw).strip()


def validate_thumbnail(thumb: str | None) -> str:
    """썸네일 값 검증 — PHP `validateThumbnail` 과 같은 기준. 실패하면 빈 문자열.

    ⚠️ **파일 경로는 그대로 통과시킨다.** 썸네일을 파일로 옮긴 뒤로 수정 화면의 hidden
       input 에는 경로가 실려 되돌아온다. 아래 base64 정규식(`^[A-Za-z0-9+/=]+$`)은 `.` 을
       거부하므로, 이 분기가 없으면 **글을 수정할 때마다 썸네일이 사라진다.**
    """
    if not thumb:
        return ""
    if thumbnail.is_path(thumb):
        return thumb
    if len(thumb) > _THUMB_MAX:
        return ""
    if not _THUMB_CHARS.match(thumb):
        return ""
    try:
        b64decode(thumb, validate=True)
    except (BinasciiError, ValueError):
        return ""
    return thumb


# ── 출력용 ──────────────────────────────────────────────────────────
#: 여는 헤딩 태그(h1~h3). 닫는 태그가 바로 뒤따르는 빈 헤딩은 세지 않는다 —
#: PHP 의 `/<h[1-3](?:\s[^>]*)?>(?!<\/h)/u` 와 같은 뜻이다.
_HEADING = re.compile(r"<h[1-3](?:\s[^>]*)?>(?!</h)", re.IGNORECASE)


def insert_thumbnail(content: str, thumbnail_b64: str) -> str:
    """썸네일을 본문에 끼워 넣는다 — PHP `views/blog/show.php` 와 같은 자리에.

    헤딩(h1~h3)이 **3개 이상이면 세 번째 헤딩 바로 앞**, 그보다 적으면 맨 앞이다.
    긴 글에서 첫 화면이 이미지로 시작하지 않게 하려는 의도라, 자리를 바꾸면 기존 글의
    인상이 달라진다. 규칙을 그대로 지킨다.
    """
    block = (
        '<div class="post-thumbnail-container">'
        f'<img class="post-thumbnail" src="{escape(thumbnail.src(thumbnail_b64))}" alt="썸네일">'
        "</div>"
    )
    spots = [m.start() for m in _HEADING.finditer(content)]
    if len(spots) >= 3:
        at = spots[2]
        return content[:at] + block + content[at:]
    return block + content
