"""ORM 모델 — 운영 블로그(`Blog`)의 기존 테이블에 맞춘다.

⚠️ **스키마를 함부로 바꾸지 않는다.** 이 테이블들은 PHP 시절부터 쌓인 운영 데이터고,
`sql/` 에 마이그레이션 도구가 없어 변경은 수동이다. 이 파일은 **있는 그대로를 비추는
거울**로 둔다.

컬럼 이름이 `posting_*`·`category_*` 로 반복되는 건 옛 규약이다. 파이썬 쪽에서 굳이
줄이지 않는다 — DB 와 이름이 달라지면 두 스택을 오갈 때 헷갈린다.
"""

from sqlalchemy import Column, DateTime, Integer, SmallInteger, Text, func

from app.db.session import Base


class Post(Base):
    """게시글. 본문(`posting_content`)까지 들어 있어 목록 조회에서는 빼고 읽는다."""

    __tablename__ = "posting_list"

    posting_index = Column(Integer, primary_key=True, autoincrement=True)
    user_index = Column(Integer, nullable=False, server_default="0")
    category_index = Column(SmallInteger, nullable=False, server_default="0")
    #: 0=공개, 1=비공개(숨김). 관리자(level<=1)만 1 을 본다.
    posting_state = Column(SmallInteger, nullable=False, server_default="0")
    #: ⚠️ PHP 가 KST 로 넣어 둔 값이다. UTC 로 보고 변환하면 9시간 밀린다.
    posting_first_post_datetime = Column(DateTime, nullable=False, server_default=func.now())
    posting_last_edit_datetime = Column(DateTime, nullable=False, server_default=func.now())
    posting_read_cnt = Column(Integer, nullable=False, server_default="0")
    posting_title = Column(Text, nullable=False)
    posting_thumbnail = Column(Text, nullable=False)
    posting_summary = Column(Text, nullable=False)
    posting_content = Column(Text, nullable=False)


class Category(Base):
    """카테고리. 읽기/쓰기 권한을 등급으로 건다.

    ⚠️ 등급은 **낮을수록 권한이 높다**(0:root … 4:visitor). 그래서 "읽을 수 있다"는
    조건이 `category_read_level >= 내 등급` 이다(PHP `Post::getMetaAllFromDb` 와 동일).
    부등호를 뒤집으면 비공개 카테고리가 전부 노출된다.
    """

    __tablename__ = "category_list"

    category_index = Column(SmallInteger, primary_key=True, autoincrement=True)
    category_name = Column(Text, nullable=False)
    category_order = Column(SmallInteger, nullable=False)
    category_read_level = Column(SmallInteger, nullable=False, server_default="0")
    category_write_level = Column(SmallInteger, nullable=False, server_default="0")


class User(Base):
    """옛 계정 테이블. **인증에는 쓰지 않는다** — 로그인은 중앙 auth(`Auth.users`)다.

    글쓴이 이름을 보여주려면 `user_index` 를 여기에 맞춰야 해서 읽기용으로만 둔다.
    계정 이관이 끝나면 이 모델은 없앤다.
    """

    __tablename__ = "user_list"

    user_index = Column(Integer, primary_key=True, autoincrement=True)
    #: 표시 이름이 따로 없다 — 화면에 쓰는 글쓴이 이름이 곧 이 로그인 아이디다.
    user_id = Column(Text, nullable=False)
    user_level = Column(SmallInteger, nullable=False, server_default="4")
    user_state = Column(SmallInteger, nullable=False, server_default="0")
