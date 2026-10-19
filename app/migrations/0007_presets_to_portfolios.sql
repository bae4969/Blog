-- 백테스트 프리셋을 포트폴리오로 합친다(2026-10-19 사용자 결정 B) — "실행하면 자동 저장되는 포트폴리오"와 "[저장]으로 남기는
-- 프리셋"이 따로 놀아 헷갈렸다. 이제 목록은 화면 위 ☆ 줄의 "내 포트폴리오" 하나다. 옛 프리셋은 아직 실행하지 않은
-- 포트폴리오로 옮긴다(지표는 '{}'·비공개 — 한 번 실행하면 채워진다). 옛 표는 지우지 않는다(더하기만).
--
-- config_hash 는 파이썬 `_config_hash`(app/ui/backtest.py)와 같아야 한다 — 다르면 옮긴 것을 실행할 때 새 행이 하나 더 생긴다:
--   md5( sorted("코드:" + php_round(비중, 2) 를 %g 로) 를 "|" 로 이은 것 + "|" + 전략 )
--   · 정렬은 코드포인트 순 → utf8mb4_bin, · php_round 는 0.5 를 0 에서 먼 쪽으로 → DECIMAL 의 ROUND, · %g → 끝의 0 과 점을 뗀다.
-- 같은 주인·같은 키의 프리셋이 여럿이면 가장 최근 것 하나만 쓴다. 두 문장 모두 다시 돌려도 안전하다.
-- ① 같은 구성의 포트폴리오가 이미 있으면(실행해 본 프리셋) 그 구성의 가장 최근 포트폴리오에 프리셋 이름을 준다 — 포트폴리오는
--    종목 이름을 이은 자동 이름이라, 사용자가 붙인 프리셋 이름이 사라지지 않게. 갱신 시각은 그대로 둔다.
UPDATE backtest_portfolio x
JOIN (
    SELECT r.preset_id, r.user_index, r.preset_name, r.hash,
           ROW_NUMBER() OVER (PARTITION BY r.user_index, r.hash ORDER BY r.updated_at DESC, r.preset_id DESC) AS nth
    FROM (
        SELECT s.preset_id, s.user_index, s.preset_name, s.updated_at, s.strategy,
               MD5(CONCAT(GROUP_CONCAT(s.part ORDER BY s.part COLLATE utf8mb4_bin SEPARATOR '|'), '|', s.strategy)) AS hash
        FROM (
            SELECT q.preset_id, q.user_index, q.preset_name, q.updated_at,
                   COALESCE(NULLIF(JSON_VALUE(q.config_json, '$.strategy'), ''), q.strategy, 'buyhold') AS strategy,
                   CONCAT(j.code, ':', TRIM(TRAILING '.' FROM TRIM(TRAILING '0' FROM CAST(ROUND(COALESCE(j.w, 0), 2) AS CHAR)))) AS part
            FROM backtest_preset q,
                 JSON_TABLE(q.config_json, '$.stocks[*]' COLUMNS (
                     code VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin PATH '$.code',
                     w DECIMAL(16, 6) PATH '$.weight')) j
            WHERE j.code IS NOT NULL AND j.code <> ''
        ) s
        GROUP BY s.preset_id, s.user_index, s.preset_name, s.updated_at, s.strategy
    ) r
) m ON m.user_index = x.user_index AND m.hash = x.config_hash AND m.nth = 1
JOIN (
    SELECT y.portfolio_id,
           ROW_NUMBER() OVER (PARTITION BY y.user_index, y.config_hash ORDER BY y.updated_at DESC, y.portfolio_id DESC) AS rk
    FROM backtest_portfolio y
    WHERE y.user_index IS NOT NULL
) z ON z.portfolio_id = x.portfolio_id AND z.rk = 1
SET x.portfolio_name = m.preset_name, x.updated_at = x.updated_at;

-- ② 그 구성의 포트폴리오가 없으면 실행 전 포트폴리오로 옮긴다.
INSERT INTO backtest_portfolio (portfolio_name, user_index, is_public, config_hash, config_json,
                                display_score, display_grade, ranking_score, ranking_grade, metrics_json,
                                stock_summary, strategy, period_start, period_end, initial_capital, monthly_dca)
SELECT p.preset_name, p.user_index, 0, h.hash, p.config_json,
       0, 'F', 0, 'F', '{}',
       LEFT(COALESCE(NULLIF(p.stock_summary, ''), p.preset_name), 200), h.strategy, CURDATE(), CURDATE(),
       COALESCE(CAST(JSON_VALUE(p.config_json, '$.initialCapital') AS UNSIGNED), 0),
       COALESCE(CAST(JSON_VALUE(p.config_json, '$.monthlyDCA') AS UNSIGNED), 0)
FROM backtest_preset p
JOIN (
    SELECT r.preset_id, r.strategy, r.hash,
           ROW_NUMBER() OVER (PARTITION BY r.user_index, r.hash ORDER BY r.updated_at DESC, r.preset_id DESC) AS nth
    FROM (
        SELECT s.preset_id, s.user_index, s.updated_at, s.strategy,
               MD5(CONCAT(GROUP_CONCAT(s.part ORDER BY s.part COLLATE utf8mb4_bin SEPARATOR '|'), '|', s.strategy)) AS hash
        FROM (
            SELECT q.preset_id, q.user_index, q.updated_at,
                   COALESCE(NULLIF(JSON_VALUE(q.config_json, '$.strategy'), ''), q.strategy, 'buyhold') AS strategy,
                   CONCAT(j.code, ':', TRIM(TRAILING '.' FROM TRIM(TRAILING '0' FROM CAST(ROUND(COALESCE(j.w, 0), 2) AS CHAR)))) AS part
            FROM backtest_preset q,
                 JSON_TABLE(q.config_json, '$.stocks[*]' COLUMNS (
                     code VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin PATH '$.code',
                     w DECIMAL(16, 6) PATH '$.weight')) j
            WHERE j.code IS NOT NULL AND j.code <> ''
        ) s
        GROUP BY s.preset_id, s.user_index, s.updated_at, s.strategy
    ) r
) h ON h.preset_id = p.preset_id AND h.nth = 1
WHERE NOT EXISTS (SELECT 1 FROM backtest_portfolio x WHERE x.user_index = p.user_index AND x.config_hash = h.hash);
