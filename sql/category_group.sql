-- 2026-09-23 블로그를 금융(인사이트)·일반(블로그)으로 나눈다 — 이미 있는 테이블에 적용하는 변경.
-- ⚠️ **배포(머지)보다 먼저** 운영 `Blog` 에 적용한다. 새 코드는 이 컬럼을 읽으므로, 컬럼 없이
--    코드가 먼저 올라가면 블로그 목록·글이 500 이 난다. 반대로 컬럼이 먼저 생기는 건 옛 코드에
--    아무 영향이 없다(기본값이 있는 새 컬럼일 뿐이다).
-- root 로 적용한다(`blog_api` 는 DDL 권한이 없다).
ALTER TABLE category_list
    ADD COLUMN IF NOT EXISTS category_group ENUM('finance', 'general') NOT NULL DEFAULT 'general'
        COMMENT '금융(인사이트) / 일반(블로그)' AFTER category_write_level;

UPDATE category_list SET category_group = 'finance' WHERE category_name = '금융';
