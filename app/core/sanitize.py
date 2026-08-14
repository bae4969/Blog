"""본문 HTML 정화 — PHP `src/Core/HtmlSanitizer.php`(HTMLPurifier) 정책을 옮긴 것.

⚠️ **이것이 유일한 방어선이다.** PHP 는 글을 저장할 때 정화하지 않고 화면에 뿌릴 때만
정화한다. 즉 `posting_content` 에는 사용자가 쓴 원본이 그대로 들어 있어, 여기서 태우지
않고 `| safe` 로 내보내면 곧바로 XSS 다. (2026-08-14 확인: 저장 경로에 sanitize 호출 없음.)

정책이 PHP 와 다르면 같은 글이 두 스택에서 다르게 보인다 — 태그·속성 목록을 바꿀 때는
PHP 쪽도 함께 고칠 것.
"""

import re
from html import escape

import nh3

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
        f'<img class="post-thumbnail" src="data:image/webp;base64,{escape(thumbnail_b64)}" alt="썸네일">'
        "</div>"
    )
    spots = [m.start() for m in _HEADING.finditer(content)]
    if len(spots) >= 3:
        at = spots[2]
        return content[:at] + block + content[at:]
    return block + content
