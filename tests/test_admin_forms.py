"""관리자 폼 — 템플릿이 보내는 필드 이름과 핸들러가 받는 이름이 같은지. DB 없이 본다.

⚠️ 2026-08-16 에 카테고리 화면 템플릿을 원본(PHP) 마크업으로 되돌리며 필드가 `category_name`
   이 됐는데 핸들러는 `name` 으로 받고 있었다. 이름이 늘 빈 값이라 **추가·수정이 전부 조용히
   거절**됐고, 화면은 "이름을 입력하세요" 토스트만 띄웠다. 한 달 넘게 아무도 몰랐다(2026-09-23 발견).
"""

import inspect
import re
from pathlib import Path

import pytest

from app.ui import admin

TEMPLATE = Path("app/templates/admin_categories.html").read_text()


def _form_fields(action: str) -> set[str]:
    """`action` 폼이 여는 자리부터 닫는 자리까지의 `name="…"`. (수정 폼은 표 칸을 가로지른다)"""
    start = TEMPLATE.index(f'action="{action}"')
    end = TEMPLATE.index("</form>", start)
    return set(re.findall(r'name="([a-z_]+)"', TEMPLATE[start:end]))


def _handler_fields(func) -> set[str]:
    """핸들러가 받는 폼 이름 — `Form(..., alias=)` 가 있으면 그 이름, 없으면 인자 이름.

    ⚠️ FastAPI 의 라우트 목록(`app.routes`)을 뒤지지 않는다. 0.14x 부터 포함된 라우터가 내부 타입
       (`_IncludedRouter`)으로 감싸여 밖에서 경로를 못 찾는다(CI 는 최신 버전으로 돈다 — 2026-09-23 실패).
       함수 서명은 버전과 상관없이 같다.
    """
    return {getattr(p.default, "alias", None) or p.name
            for p in inspect.signature(func).parameters.values() if p.name != "request"}


@pytest.mark.parametrize("path, func", [
    ("/admin/categories/create", admin.category_create),
    ("/admin/categories/update", admin.category_update),
])
def test_카테고리_폼_필드가_핸들러와_같다(path, func):
    assert _form_fields(path) == _handler_fields(func)


def test_외부연동_폼_필드가_app_settings와_일치한다():
    from app.core import app_settings

    tpl = Path("app/templates/admin_integrations.html").read_text()
    start = tpl.index('action="/admin/integrations"')
    end = tpl.index("</form>", start)
    # form="agySubmit" 처럼 외부 폼에 속한 입력(code)은 제외한다.
    fields = {
        m.group(1)
        for m in re.finditer(r'<(?:input|select|textarea)\b[^>]*\bname="([a-z0-9_]+)"[^>]*>', tpl[start:end])
        if 'form="' not in m.group(0)
    }
    assert fields == set(app_settings.DEFAULTS) | {"csrf_token"}
