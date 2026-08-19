"""썸네일 — DB 의 base64 를 파일로 옮긴다.

원래 `posting_list.posting_thumbnail` 에 **base64 WebP 를 통째로** 넣고 화면에서
`<img src="data:image/webp;base64,...">` 로 뿌렸다. 그 대가가 컸다(2026-08-19 측정):

- 썸네일 127개가 평균 87KB·합계 **17MB** 로, `posting_list` 23.6MB 의 **72%** 를 차지했다.
- 목록 한 장이 **1.59MB** 였고 그중 98%가 썸네일이었다. **브라우저가 캐시할 수 없어**
  방문할 때마다 다시 받는다.

그래서 파일로 굽고 컬럼에는 **경로**만 둔다. 목록은 약 25KB 로 줄고, 두 번째 방문부터는
이미지가 캐시에서 나온다.

## 두 형식을 동시에 읽는다

이관은 한 번에 안 끝나고(운영·테스트 DB 가 따로다) 실패한 행은 base64 로 남긴다.
그래서 읽는 쪽은 **항상 둘 다** 받아야 한다 — `src()` 하나로 통일한다.

⚠️ 구분자는 `.` 이다. base64 알파벳은 `A-Za-z0-9+/=` 라 **점이 들어갈 수 없으므로**
   `.webp` 로 끝나면 경로임이 확실하다. 길이나 접두사로 재면 오판이 난다.

## 파일 이름은 내용 해시다

글 번호가 아니라 바이트의 sha256 을 쓴다. 새 글은 INSERT 전에 번호를 모르는데 해시는
미리 알 수 있고, 같은 그림을 두 글이 쓰면 파일 하나를 공유한다.

⚠️ 이 디렉토리는 `.gitignore` 대상이라 **배포로 따라가지 않는다.** 환경마다 각자 갖는다
   (`20.blog` 와 `21.blog_test` 의 `public/uploads` 는 서로 다른 실체다).
"""

import hashlib
import logging
from base64 import b64decode
from binascii import Error as BinasciiError
from pathlib import Path

logger = logging.getLogger(__name__)

#: 컬럼에 저장하는 상대경로의 뿌리. 앞에 `/` 를 붙이면 그대로 URL 이 된다.
REL_DIR = "uploads/thumbnails"
_DIR = Path(__file__).resolve().parent.parent.parent / "public" / REL_DIR


def is_path(value: str) -> bool:
    """컬럼 값이 파일 경로인가. base64 에는 `.` 이 못 들어간다는 성질을 쓴다."""
    return "." in value


def src(value: str | None) -> str:
    """컬럼 값 → `<img src>`. 경로든 base64 든 받는다. 없으면 빈 문자열."""
    if not value:
        return ""
    if is_path(value):
        return "/" + value.lstrip("/")
    return "data:image/webp;base64," + value


def store(value: str) -> str:
    """base64 를 파일로 굽고 **컬럼에 넣을 값**을 돌려준다.

    - 이미 경로면 그대로 돌려준다(수정 저장 때 경로가 되돌아온다).
    - 디코드에 실패하거나 파일을 못 쓰면 **base64 를 그대로** 돌려준다 — 썸네일이
      사라지는 것보다 무거운 편이 낫다.
    """
    if not value or is_path(value):
        return value
    try:
        raw = b64decode(value, validate=True)
    except (BinasciiError, ValueError):
        logger.warning("썸네일 base64 디코드 실패 — 원본을 그대로 둔다")
        return value

    name = hashlib.sha256(raw).hexdigest()[:32] + ".webp"
    rel = f"{REL_DIR}/{name}"
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        path = _DIR / name
        if not path.exists():          # 같은 그림이면 다시 쓰지 않는다
            path.write_bytes(raw)
    except OSError:
        logger.exception("썸네일 파일 기록 실패 — base64 를 그대로 둔다")
        return value
    return rel
