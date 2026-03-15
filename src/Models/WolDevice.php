<?php

namespace Blog\Models;

use Blog\Database\Database;

class WolDevice
{
    private $db;

    public function __construct()
    {
        $this->db = Database::getInstance();
    }

    public function getAll(): array
    {
        $sql = "SELECT * FROM wol_device_list ORDER BY wol_device_id ASC";
        return $this->db->fetchAll($sql);
    }

    public function getById(int $id): ?array
    {
        $sql = "SELECT * FROM wol_device_list WHERE wol_device_id = ?";
        return $this->db->fetch($sql, [$id]);
    }

    public function create(string $name, string $ipRange, string $macAddress): int
    {
        $sql = "INSERT INTO wol_device_list (wol_device_name, wol_device_ip_range, wol_device_mac_address) VALUES (?, ?, ?)";
        $this->db->query($sql, [$name, $ipRange, $macAddress]);
        return (int)$this->db->lastInsertId();
    }

    public function update(int $id, string $name, string $ipRange, string $macAddress): bool
    {
        $sql = "UPDATE wol_device_list SET wol_device_name = ?, wol_device_ip_range = ?, wol_device_mac_address = ? WHERE wol_device_id = ?";
        $stmt = $this->db->query($sql, [$name, $ipRange, $macAddress, $id]);
        return $stmt->rowCount() > 0;
    }

    public function delete(int $id): bool
    {
        $sql = "DELETE FROM wol_device_list WHERE wol_device_id = ?";
        $stmt = $this->db->query($sql, [$id]);
        return $stmt->rowCount() > 0;
    }
}
