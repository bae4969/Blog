-- 관심 종목 순서(2026-10-13) — 레일에서 손잡이로 끌어(또는 ↑↓·방향키로) 바꾼다.
-- NULL 은 아직 순서가 없는 줄이다(이 칸을 모르는 옛 코드가 담은 것) — 읽을 때 맨 뒤, 담은 시각순으로 둔다.
ALTER TABLE stock_watchlist
    ADD COLUMN IF NOT EXISTS sort_order INT UNSIGNED NULL
        COMMENT '계정 안 표시 순서(1부터). NULL 은 맨 뒤 — 담은 시각순' AFTER stock_code;

-- 지금까지의 순서(담은 순서 = created_at, stock_code)를 그대로 옮긴다. 다시 돌려도 채운 줄은 건드리지 않는다.
UPDATE stock_watchlist w
  JOIN (SELECT user_index, market, stock_code,
               ROW_NUMBER() OVER (PARTITION BY user_index ORDER BY created_at, stock_code) AS rn
          FROM stock_watchlist) r
    ON r.user_index = w.user_index AND r.market = w.market AND r.stock_code = w.stock_code
   SET w.sort_order = r.rn
 WHERE w.sort_order IS NULL;
