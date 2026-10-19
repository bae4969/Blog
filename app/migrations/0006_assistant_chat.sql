-- 상담 대화를 투자 계획에서 떼어 낸다(2026-10-19) — 상담은 이제 모든 화면의 하단 시트(root 전용)이고, 투자 계획은 거기
-- 붙는 모듈 하나다. 대화는 계획 버전 번호(rev_id) 대신 모듈이 남기는 `meta`(JSON — 계획이면 plan_rev·badge)를 갖는다.
-- 옛 `invest_plan_chat` 은 지우지 않는다(더하기만 — 배포가 실패해 옛 이미지로 돌아가면 옛 코드가 그걸 쓴다).
CREATE TABLE IF NOT EXISTS assistant_chat (
    chat_id     INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_index  INT UNSIGNED NOT NULL,
    role        ENUM('user', 'assistant') NOT NULL,
    content     MEDIUMTEXT NOT NULL,
    meta        TEXT NULL COMMENT '모듈이 남긴 것(JSON) — 계획이면 {"plan_rev": 버전, "badge": "계획 버전 #N"}',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_chat (user_index, chat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 옛 대화를 옮긴다 — 새 테이블이 비어 있을 때만(파일 중간에서 죽어 처음부터 다시 돌아도 두 번 들어가지 않게).
INSERT INTO assistant_chat (user_index, role, content, meta, created_at)
SELECT c.user_index, c.role, c.content,
       IF(c.rev_id IS NULL, NULL, JSON_OBJECT('plan_rev', c.rev_id, 'badge', CONCAT('계획 버전 #', c.rev_id))),
       c.created_at
FROM invest_plan_chat c
WHERE NOT EXISTS (SELECT 1 FROM assistant_chat)
ORDER BY c.chat_id;
