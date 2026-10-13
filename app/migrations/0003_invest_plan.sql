-- 투자 계획(2026-10-10) — AI 상담으로 짜는 이벤트 분기 계획. root 본인 전용이다.
-- 계획은 **문서 한 덩어리(JSON)** 로 두고, AI 가 고칠 때마다 새 버전을 쌓는다. 되돌리기 = 옛 버전을 새 버전으로 다시 쌓기.
CREATE TABLE IF NOT EXISTS invest_plan_rev (
    rev_id      INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_index  INT UNSIGNED NOT NULL,
    doc         LONGTEXT NOT NULL COMMENT '계획 문서(JSON) — 보유 자산 + 이벤트·가지 트리',
    summary     VARCHAR(500) NOT NULL DEFAULT '' COMMENT '이 버전에서 바뀐 것(사람이 읽는 요약)',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_rev (user_index, rev_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 상담 대화. 이미지는 저장하지 않는다(본문에 "[이미지 N장]" 만 남긴다).
CREATE TABLE IF NOT EXISTS invest_plan_chat (
    chat_id     INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_index  INT UNSIGNED NOT NULL,
    role        ENUM('user', 'assistant') NOT NULL,
    content     MEDIUMTEXT NOT NULL,
    rev_id      INT UNSIGNED NULL COMMENT '이 답으로 생긴 계획 버전',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_chat (user_index, chat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 이벤트 시작 메일을 보낸 기록. 시각을 키에 넣는다 — 이벤트 날짜가 옮겨지면 새로 알린다.
CREATE TABLE IF NOT EXISTS invest_plan_notice (
    user_index  INT UNSIGNED NOT NULL,
    node_id     VARCHAR(32) NOT NULL,
    event_at    DATETIME NOT NULL,
    sent_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_index, node_id, event_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
