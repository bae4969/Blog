<div class="admin-content">
    <h2>WOL (Wake-on-LAN)</h2>

    <div class="admin-card">
        <div class="stat-row">
            <div class="stat-item"><span class="stat-label">등록된 장치</span> <span class="stat-value"><?= count($devices) ?></span></div>
        </div>
    </div>

    <!-- 장치 등록 -->
    <div class="admin-card">
        <h3>새 장치 등록</h3>
        <form method="post" action="/admin/wol/create" class="admin-form">
            <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
            <div class="admin-form-grid">
                <div class="admin-form-field">
                    <label>장치 이름</label>
                    <input type="text" name="device_name" required maxlength="100" placeholder="예: 메인 PC">
                </div>
                <div class="admin-form-field">
                    <label>IP 대역</label>
                    <input type="text" name="ip_range" required maxlength="100" placeholder="예: 192.168.0.10 또는 192.168.0.0/24">
                </div>
                <div class="admin-form-field">
                    <label>MAC 주소</label>
                    <input type="text" name="mac_address" required maxlength="17" placeholder="예: AA-BB-CC-DD-EE-FF">
                </div>
            </div>
            <div class="admin-form-actions">
                <button type="submit" class="btn btn-primary">등록</button>
            </div>
        </form>
    </div>

    <!-- 장치 목록 -->
    <div class="admin-card">
        <h3>장치 목록</h3>
        <?php if (empty($devices)): ?>
            <p class="admin-placeholder">등록된 장치가 없습니다.</p>
        <?php else: ?>
            <div class="wol-device-list">
                <?php foreach ($devices as $device): ?>
                    <div class="wol-device">
                        <div class="wol-device-info">
                            <form method="post" action="/admin/wol/update" class="wol-edit-form" id="wol-edit-<?= (int)$device['wol_device_id'] ?>">
                                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                <input type="hidden" name="device_id" value="<?= (int)$device['wol_device_id'] ?>">
                                <div class="wol-edit-row">
                                    <label>이름</label>
                                    <input type="text" name="device_name" value="<?= $view->escape($device['wol_device_name']) ?>" required maxlength="100" class="inline-input">
                                </div>
                                <div class="wol-edit-row">
                                    <label>IP 대역</label>
                                    <input type="text" name="ip_range" value="<?= $view->escape($device['wol_device_ip_range']) ?>" required maxlength="100" class="inline-input">
                                </div>
                                <div class="wol-edit-row">
                                    <label>MAC</label>
                                    <input type="text" name="mac_address" value="<?= $view->escape($device['wol_device_mac_address']) ?>" required maxlength="17" class="inline-input">
                                </div>
                            </form>
                            <form method="post" action="/admin/wol/execute" id="wol-exec-<?= (int)$device['wol_device_id'] ?>" class="wol-hidden-form"
                                  onsubmit="return confirm('<?= $view->escape($device['wol_device_name']) ?>에 WOL 패킷을 전송하시겠습니까?');">
                                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                <input type="hidden" name="device_id" value="<?= (int)$device['wol_device_id'] ?>">
                            </form>
                            <form method="post" action="/admin/wol/delete" id="wol-del-<?= (int)$device['wol_device_id'] ?>" class="wol-hidden-form"
                                  onsubmit="return confirm('<?= $view->escape($device['wol_device_name']) ?> 장치를 삭제하시겠습니까?');">
                                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                <input type="hidden" name="device_id" value="<?= (int)$device['wol_device_id'] ?>">
                            </form>
                            <div class="wol-device-actions">
                                <button type="submit" form="wol-edit-<?= (int)$device['wol_device_id'] ?>" class="btn btn-sm btn-primary wol-save-btn" disabled>저장</button>
                                <button type="submit" form="wol-exec-<?= (int)$device['wol_device_id'] ?>" class="btn btn-sm btn-wol">전원 켜기</button>
                                <button type="submit" form="wol-del-<?= (int)$device['wol_device_id'] ?>" class="btn btn-sm btn-danger">삭제</button>
                            </div>
                        </div>
                    </div>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>
    </div>

    <!-- 안내 -->
    <div class="admin-card">
        <h3>WOL 안내</h3>
        <div class="admin-help">
            <p>* WOL은 같은 네트워크(LAN)에 있는 장치만 깨울 수 있습니다</p>
            <p>* 대상 장치의 BIOS/UEFI에서 WOL이 활성화되어 있어야 합니다</p>
            <p>* 패킷 전송 성공이 장치 부팅을 보장하지는 않습니다</p>
            <p>* MAC 주소 형식: <code>AA-BB-CC-DD-EE-FF</code> 또는 <code>AA:BB:CC:DD:EE:FF</code></p>
        </div>
    </div>
</div>

<script>
document.querySelectorAll('.wol-edit-form').forEach(function(form) {
    var btn = document.querySelector('button[form="' + form.id + '"]');
    if (!btn) return;
    form.querySelectorAll('.inline-input').forEach(function(input) {
        input.addEventListener('input', function() { btn.disabled = false; });
    });
});
</script>
