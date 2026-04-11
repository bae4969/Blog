CREATE TABLE IF NOT EXISTS backtest_preset (
    preset_id    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_index   INT UNSIGNED NOT NULL,
    preset_name  VARCHAR(100) NOT NULL,
    config_json  JSON NOT NULL,
    stock_summary VARCHAR(200) DEFAULT '',
    strategy     VARCHAR(20)  DEFAULT 'buyhold',
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_name (user_index, preset_name),
    INDEX idx_user (user_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
