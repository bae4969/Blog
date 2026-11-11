-- 새 상담은 과거 대화를 지우지 않고 전달 시작점만 옮긴다.
CREATE TABLE IF NOT EXISTS assistant_context (
    user_index INT UNSIGNED NOT NULL PRIMARY KEY,
    after_chat_id INT UNSIGNED NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 첨부는 공개 uploads에 두지 않는다. 사용자별 최근 4장, 최대 24시간만 보관한다.
CREATE TABLE IF NOT EXISTS assistant_image (
    image_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_index INT UNSIGNED NOT NULL,
    chat_id INT UNSIGNED NOT NULL,
    data_url MEDIUMTEXT NOT NULL,
    expires_at DATETIME NOT NULL,
    KEY idx_user_image (user_index, image_id),
    KEY idx_image_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
