"""API 응답 스키마 — `/api/v1/*` 의 **계약**이다.

화면(Jinja)은 DB 행을 그대로 템플릿에 넘기지만, API 는 그러면 안 된다. 컬럼을 하나
추가하는 순간 응답이 조용히 바뀌고, 그걸 소비하는 쪽은 알 길이 없다. 여기 적힌 것만
나가고 여기 없는 것은 안 나간다 — `response_model` 이 그걸 강제한다.

⚠️ 옛 컬럼 이름(`posting_*`·`category_*`)을 그대로 내보내지 않는다. DB 규약이 바깥
   계약이 되면 컬럼을 못 바꾸게 된다. 이름은 여기서 한 번 옮긴다.
"""

from app.schemas.blog import (
    CategoryOut,
    Page,
    PostCreate,
    PostDetail,
    PostSummary,
    PostUpdate,
)

__all__ = ["CategoryOut", "Page", "PostCreate", "PostDetail", "PostSummary", "PostUpdate"]
