-- 관심 종목(2026-09-23). 계정(`user_list.user_index`)마다 따로, 서버에 저장한다 — 기기끼리 맞춰진다.
-- market 은 시장 묶음이다(KR·US·COIN). 코드가 주식과 코인에서 겹칠 수 있어 키에 넣는다.
-- ⚠️ 이 파일은 스키마 **정의**다(새로 만들 때 보는 것). 이미 있는 DB 에는 컨테이너가 뜰 때
--    `app/migrations/0001_stock_watchlist.sql` 이 자동으로 적용된다(`app/migrate.py`).
CREATE TABLE IF NOT EXISTS stock_watchlist (
    user_index  INT UNSIGNED NOT NULL,
    market      ENUM('KR', 'US', 'COIN') NOT NULL,
    stock_code  VARCHAR(32) NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_index, market, stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
