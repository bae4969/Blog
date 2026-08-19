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
