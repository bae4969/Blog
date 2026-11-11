-- 상담 변경안: 미리보기와 반영을 분리하고 읽은 버전/재시도 키를 고정한다.
CREATE TABLE IF NOT EXISTS invest_plan_change (
    change_id VARCHAR(32) NOT NULL PRIMARY KEY,
    user_index INT UNSIGNED NOT NULL,
    request_key VARCHAR(64) NOT NULL,
    base_rev INT UNSIGNED NOT NULL DEFAULT 0,
    payload LONGTEXT NOT NULL,
    result_rev INT UNSIGNED NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_plan_change_user (user_index, created_at),
    UNIQUE KEY uniq_plan_change_request (user_index, request_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
