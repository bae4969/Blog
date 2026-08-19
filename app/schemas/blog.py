"""블로그 리소스 스키마."""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class CategoryOut(BaseModel):
    id: int = Field(description="카테고리 번호")
    name: str
    order: int = Field(description="화면 정렬 순서")


class PostSummary(BaseModel):
    """목록용. **본문은 넣지 않는다** — `posting_content` 는 mediumtext 라 무겁고,
    목록에 필요한 것은 요약뿐이다(화면 쪽 SELECT 도 같은 이유로 뺀다)."""

    id: int
    title: str
    summary: str = Field(description="본문에서 뽑은 요약. 태그는 제거된 상태다.")
    #: ⚠️ DB 에 든 값(경로 또는 base64)이 아니라 **바로 쓸 수 있는 URL** 이다.
    #: 2026-08-19 에 썸네일을 파일로 옮기면서 컬럼이 경로가 됐지만, 옮기지 못한 행은
    #: base64 로 남아 있을 수 있다. 그 차이를 API 소비자에게 넘기지 않는다.
    thumbnail_url: str | None = None
    category: CategoryOut | None = None
    author: str | None = Field(default=None, description="글쓴이 아이디. 계정이 지워졌으면 null")
    read_count: int
    #: 숨긴 글인가(`posting_state != 0`). 관리자에게만 목록에 나타나고 흐리게 표시된다 —
    #: 일반 사용자 응답에는 숨긴 글 자체가 없으므로 항상 false 다.
    is_hidden: bool = False
    created_at: datetime
    updated_at: datetime


class PostDetail(PostSummary):
    """상세용 — 요약에 본문을 더한 것."""

    #: 출력 정화를 마친 HTML 이다. ⚠️ 소비자가 그대로 렌더할 것을 전제로 한다 —
    #: DB 에는 정화 전 원본이 들어 있어 여기서 거르지 않으면 그대로 XSS 가 된다.
    content: str


class Page(BaseModel, Generic[T]):
    """목록 응답 봉투. 커서가 아니라 페이지 번호다 — 화면이 그렇게 쓰고 있다."""

    items: list[T]
    total: int = Field(description="필터를 적용한 전체 건수")
    page: int
    size: int
    pages: int = Field(description="전체 쪽수. 최소 1")


class PostCreate(BaseModel):
    """글 작성 입력.

    ⚠️ 본문은 **저장용 정화**를 거친 뒤 들어간다(`sanitize_for_save`). 화면과 같은
       정책이라, 여기로 넣은 글과 에디터로 쓴 글이 같은 태그 집합을 갖는다.
    """

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(default="", description="HTML. 저장 시 정화된다")
    category_id: int = Field(description="쓰기 등급을 넘는 카테고리여야 한다")
    #: base64 WebP 또는 이미 저장된 경로. 넣으면 파일로 구워 경로만 저장한다.
    thumbnail: str | None = None


class PostUpdate(BaseModel):
    """글 수정 입력. 준 항목만 바뀐다."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = None
    category_id: int | None = None
    thumbnail: str | None = None
