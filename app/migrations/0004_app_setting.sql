-- 외부 연동 설정(2026-10-10) — AI 서버·SMTP 인증 정보를 관리자 화면(`/admin/integrations`)에서 넣고 바꾼다.
-- 전에는 `.env.api` 에 있었다(운영은 배포로 안 따라가 손으로 넣어야 했다). 이제 여기 한 곳뿐이다.
-- ⚠️ 비밀 값(키·비밀번호)은 평문이다. 화면으로는 다시 내보내지 않는다(끝 4자리만).
CREATE TABLE IF NOT EXISTS app_setting (
    setting_key    VARCHAR(64) NOT NULL PRIMARY KEY,
    setting_value  TEXT NOT NULL,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
