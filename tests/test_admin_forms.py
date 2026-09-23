"""관리자 폼 — 템플릿이 보내는 필드 이름과 핸들러가 받는 이름이 같은지. DB 없이 본다.

⚠️ 2026-08-16 에 카테고리 화면 템플릿을 원본(PHP) 마크업으로 되돌리며 필드가 `category_name`
   이 됐는데 핸들러는 `name` 으로 받고 있었다. 이름이 늘 빈 값이라 **추가·수정이 전부 조용히
   거절**됐고, 화면은 "이름을 입력하세요" 토스트만 띄웠다. 한 달 넘게 아무도 몰랐다(2026-09-23 발견).
"""

import re
from pathlib import Path

import pytest

from app.main import app

TEMPLATE = Path("app/templates/admin_categories.html").read_text()


def _form_fields(action: str) -> set[str]:
    """`action` 폼이 여는 자리부터 닫는 자리까지의 `name="…"`. (수정 폼은 표 칸을 가로지른다)"""
    start = TEMPLATE.index(f'action="{action}"')
    end = TEMPLATE.index("</form>", start)
    return set(re.findall(r'name="([a-z_]+)"', TEMPLATE[start:end]))


def _handler_fields(path: str) -> set[str]:
    route = next(r for r in app.routes if getattr(r, "path", None) == path and "POST" in r.methods)
    return {p.alias for p in route.dependant.body_params}


@pytest.mark.parametrize("path", ["/admin/categories/create", "/admin/categories/update"])
def test_카테고리_폼_필드가_핸들러와_같다(path):
    assert _form_fields(path) == _handler_fields(path)
