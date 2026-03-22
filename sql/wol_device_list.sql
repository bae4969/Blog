-- WOL(Wake-on-LAN) 장치 테이블
-- 참조: src/Models/WolDevice.php, src/Controllers/AdminController.php
CREATE TABLE IF NOT EXISTS `wol_device_list` (
    `wol_device_id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT,
    `wol_device_name` TEXT NOT NULL COLLATE 'utf8mb4_uca1400_ai_ci',
    `wol_device_ip_range` TEXT NOT NULL COLLATE 'utf8mb4_uca1400_ai_ci',
    `wol_device_mac_address` TEXT NOT NULL COLLATE 'utf8mb4_uca1400_ai_ci',
    PRIMARY KEY (`wol_device_id`) USING BTREE
)
COLLATE='utf8mb4_uca1400_ai_ci'
ENGINE=InnoDB
;
