-- 2026-09-23 블로그를 금융(인사이트 `/insights`)·일반(블로그 `/blog`)으로 나눈다.
-- 카테고리가 어느 목록에 나올지 정하는 묶음 컬럼. 기본값이 있어 옛 코드에는 아무 영향이 없다.
ALTER TABLE category_list
    ADD COLUMN IF NOT EXISTS category_group ENUM('finance', 'general') NOT NULL DEFAULT 'general'
        COMMENT '금융(인사이트) / 일반(블로그)' AFTER category_write_level;

-- 처음 나눌 때 금융 카테고리 하나만 금융 쪽이다. 그 뒤로는 관리자 화면에서 바꾼다.
UPDATE category_list SET category_group = 'finance' WHERE category_name = '금융';
