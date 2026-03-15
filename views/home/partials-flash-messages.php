<?php if ($session->hasFlash('success')): ?>
    <div class="alert alert-success">
        <?= $view->escape($session->getFlash('success')) ?>
    </div>
<?php endif; ?>

<?php if ($session->hasFlash('error')): ?>
    <div class="alert alert-error">
        <?= $view->escape($session->getFlash('error')) ?>
    </div>
<?php endif; ?>
