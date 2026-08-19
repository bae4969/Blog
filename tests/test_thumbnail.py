"""썸네일 — 경로/base64 두 형식을 다루는 규칙.

이 테스트가 지키는 것은 2026-08-19 에 실제로 걸린 결함들이다. 이관은 한 번에 안 끝나고
운영·테스트 DB 가 따로라, 읽는 쪽이 **두 형식을 다 받는다**는 성질이 깨지면 화면이 조용히
망가진다.
"""

from base64 import b64encode

import pytest

from app.core import thumbnail
from app.core.sanitize import validate_thumbnail


class TestIsPath:
    """경로/base64 구분자는 `.` 이다 — base64 알파벳(A-Za-z0-9+/=)에 점이 없다."""

    @pytest.mark.parametrize("value", [
        "uploads/thumbnails/abc123.webp",
        "/uploads/thumbnails/abc123.webp",
    ])
    def test_경로로_본다(self, value):
        assert thumbnail.is_path(value)

    @pytest.mark.parametrize("value", [
        "UklGRtpHAwBXRUJQVlA4IM5HAwDQIQed",   # 실제 WebP base64 앞부분
        "AAAA",
        # ⚠️ 'uploads/' 는 **전부 유효한 base64 문자**다. 접두사로 구분하면 여기서 틀린다.
        "uploads/AAAA",
    ])
    def test_base64_로_본다(self, value):
        assert not thumbnail.is_path(value)


class TestSrc:
    def test_경로는_URL_로(self):
        assert thumbnail.src("uploads/thumbnails/x.webp") == "/uploads/thumbnails/x.webp"

    def test_앞에_슬래시가_있어도_두_번_안_붙는다(self):
        assert thumbnail.src("/uploads/thumbnails/x.webp") == "/uploads/thumbnails/x.webp"

    def test_base64_는_data_URI_로(self):
        assert thumbnail.src("AAAA") == "data:image/webp;base64,AAAA"

    @pytest.mark.parametrize("empty", ["", None])
    def test_비었으면_빈_문자열(self, empty):
        assert thumbnail.src(empty) == ""


class TestStore:
    def test_파일로_굽고_경로를_돌려준다(self, tmp_path, monkeypatch):
        monkeypatch.setattr(thumbnail, "_DIR", tmp_path)
        raw = b"RIFF0000WEBPfake"
        got = thumbnail.store(b64encode(raw).decode())
        assert got.startswith(thumbnail.REL_DIR + "/") and got.endswith(".webp")
        assert (tmp_path / got.split("/")[-1]).read_bytes() == raw

    def test_같은_그림은_파일을_공유한다(self, tmp_path, monkeypatch):
        monkeypatch.setattr(thumbnail, "_DIR", tmp_path)
        b64 = b64encode(b"same-bytes").decode()
        assert thumbnail.store(b64) == thumbnail.store(b64)
        assert len(list(tmp_path.iterdir())) == 1

    def test_이미_경로면_그대로_둔다(self, tmp_path, monkeypatch):
        """수정 저장 때 hidden input 으로 경로가 되돌아온다 — 다시 구우면 안 된다."""
        monkeypatch.setattr(thumbnail, "_DIR", tmp_path)
        path = "uploads/thumbnails/x.webp"
        assert thumbnail.store(path) == path
        assert not list(tmp_path.iterdir())

    def test_디코드_실패하면_원본을_지킨다(self, tmp_path, monkeypatch):
        """썸네일이 사라지는 것보다 무거운 채로 남는 편이 낫다."""
        monkeypatch.setattr(thumbnail, "_DIR", tmp_path)
        bad = "!!!not-base64!!!"
        assert thumbnail.store(bad) == bad


class TestValidateThumbnail:
    """⚠️ 이 분기가 없으면 **글을 수정할 때마다 썸네일이 사라진다.**

    수정 화면의 hidden input 에는 이제 경로가 실려 되돌아오는데, base64 정규식
    `^[A-Za-z0-9+/=]+$` 는 `.` 을 거부하기 때문이다.
    """

    def test_경로는_통과시킨다(self):
        path = "uploads/thumbnails/abc.webp"
        assert validate_thumbnail(path) == path

    def test_정상_base64_는_통과(self):
        b64 = b64encode(b"hello").decode()
        assert validate_thumbnail(b64) == b64

    @pytest.mark.parametrize("bad", ["", None, "!!!", "AAA A"])
    def test_이상한_값은_빈_문자열(self, bad):
        assert validate_thumbnail(bad) == ""
