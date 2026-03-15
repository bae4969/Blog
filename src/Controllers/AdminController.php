<?php

namespace Blog\Controllers;

use Blog\Models\Stock;
use Blog\Models\Category;
use Blog\Models\User;
use Blog\Models\WolDevice;
use Blog\Core\Cache;
use Blog\Core\Logger;

class AdminController extends BaseController
{
    private $stockModel;
    private $categoryModel;
    private $userModel;
    private $wolDeviceModel;

    public function __construct()
    {
        parent::__construct();
        $this->auth->requireStockAdminAccess();
        $this->stockModel = new Stock();
        $this->categoryModel = new Category();
        $this->userModel = new User();
        $this->wolDeviceModel = new WolDevice();
    }

    private function adminData(string $currentMenu, array $extra = []): array
    {
        return array_merge([
            'isAdminPage' => true,
            'adminCurrentMenu' => $currentMenu,
            'additionalCss' => ['/css/admin.css'],
        ], $extra);
    }

    public function index(): void
    {
        $this->redirect('/admin/users');
    }

    public function users(): void
    {
        $searchQuery = mb_substr($this->sanitizeInput((string)$this->getParam('q', '')), 0, 50);
        $users = $searchQuery === ''
            ? $this->userModel->getAllUsers()
            : $this->userModel->getAllUsersBySearch($searchQuery);

        $levelLabels = [
            0 => '슈퍼관리자',
            1 => '관리자',
            2 => '에디터',
            3 => '작성자',
            4 => '구독자',
        ];

        $this->renderLayout('admin', 'admin/users', $this->adminData('users', [
            'users' => $users,
            'levelLabels' => $levelLabels,
            'searchQuery' => $searchQuery,
            'csrfToken' => $this->view->csrfToken(),
        ]));
    }

    private function getAdminUsersUrl(): string
    {
        $searchQuery = mb_substr($this->sanitizeInput((string)$this->getParam('q', '')), 0, 50);

        if ($searchQuery === '') {
            return '/admin/users';
        }

        return '/admin/users?q=' . urlencode($searchQuery);
    }

    public function createUser(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('user.create', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect($this->getAdminUsersUrl());
            return;
        }

        $userId = $this->sanitizeInput($this->getParam('user_id', ''));
        $password = $this->getParam('user_pw', '');
        $level = (int)$this->getParam('user_level', 4);
        $postingLimit = (int)$this->getParam('user_posting_limit', 10);

        if (empty($userId) || empty($password)) {
            $this->auditAdminAction('user.create', ['target_user_id' => $userId, 'reason' => 'required_missing'], 'rejected');
            $this->session->setFlash('error', '아이디와 비밀번호는 필수입니다.');
            $this->redirect($this->getAdminUsersUrl());
            return;
        }

        if (strlen($userId) < 2 || strlen($userId) > 50) {
            $this->auditAdminAction('user.create', ['target_user_id' => $userId, 'reason' => 'invalid_user_id_length'], 'rejected');
            $this->session->setFlash('error', '아이디는 2~50자여야 합니다.');
            $this->redirect($this->getAdminUsersUrl());
            return;
        }

        if (!in_array($level, [0, 1, 2, 3, 4], true)) {
            $this->auditAdminAction('user.create', ['target_user_id' => $userId, 'reason' => 'invalid_level', 'requested_level' => $level], 'rejected');
            $this->session->setFlash('error', '유효하지 않은 권한 레벨입니다.');
            $this->redirect($this->getAdminUsersUrl());
            return;
        }

        if ($postingLimit < 0 || $postingLimit > 10000) {
            $this->auditAdminAction('user.create', ['target_user_id' => $userId, 'reason' => 'invalid_posting_limit', 'requested_limit' => $postingLimit], 'rejected');
            $this->session->setFlash('error', '게시글 제한은 0~10000 사이여야 합니다.');
            $this->redirect($this->getAdminUsersUrl());
            return;
        }

        if ($this->userModel->isUserIdExists($userId)) {
            $this->auditAdminAction('user.create', ['target_user_id' => $userId, 'reason' => 'already_exists'], 'rejected');
            $this->session->setFlash('error', '이미 존재하는 아이디입니다.');
            $this->redirect($this->getAdminUsersUrl());
            return;
        }

        $this->userModel->createUser($userId, $password, $level, $postingLimit);
        $this->auditAdminAction('user.create', [
            'target_user_id' => $userId,
            'level' => $level,
            'posting_limit' => $postingLimit,
        ]);
        $this->session->setFlash('success', "사용자 '{$userId}'가 생성되었습니다.");
        $this->redirect($this->getAdminUsersUrl());
    }

    public function updateUser(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('user.update', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect($this->getAdminUsersUrl());
            return;
        }

        $userIndex = (int)$this->getParam('user_index', 0);
        $action = $this->sanitizeInput($this->getParam('action', ''));

        if ($userIndex <= 0) {
            $this->auditAdminAction('user.update', ['reason' => 'invalid_user_index', 'target_user_index' => $userIndex], 'rejected');
            $this->session->setFlash('error', '유효하지 않은 사용자입니다.');
            $this->redirect($this->getAdminUsersUrl());
            return;
        }

        $user = $this->userModel->getUserByIndex($userIndex);
        if (!$user) {
            $this->auditAdminAction('user.update', ['reason' => 'user_not_found', 'target_user_index' => $userIndex], 'rejected');
            $this->session->setFlash('error', '사용자를 찾을 수 없습니다.');
            $this->redirect($this->getAdminUsersUrl());
            return;
        }

        $currentUserIndex = $this->auth->getCurrentUserIndex();

        switch ($action) {
            case 'update_level':
                $newLevel = (int)$this->getParam('user_level', 4);
                if (!in_array($newLevel, [0, 1, 2, 3, 4], true)) {
                    $this->auditAdminAction('user.update_level', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id'], 'reason' => 'invalid_level', 'requested_level' => $newLevel], 'rejected');
                    $this->session->setFlash('error', '유효하지 않은 권한 레벨입니다.');
                    break;
                }
                if ($userIndex === $currentUserIndex) {
                    $this->auditAdminAction('user.update_level', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id'], 'reason' => 'self_update_blocked'], 'denied');
                    $this->session->setFlash('error', '자신의 권한은 변경할 수 없습니다.');
                    break;
                }
                $this->userModel->updateUserLevel($userIndex, $newLevel);
                $this->auditAdminAction('user.update_level', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id'], 'new_level' => $newLevel]);
                $this->session->setFlash('success', "'{$user['user_id']}'의 권한이 변경되었습니다.");
                break;

            case 'toggle_state':
                if ($userIndex === $currentUserIndex) {
                    $this->auditAdminAction('user.toggle_state', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id'], 'reason' => 'self_toggle_blocked'], 'denied');
                    $this->session->setFlash('error', '자신의 상태는 변경할 수 없습니다.');
                    break;
                }
                $newState = (int)$user['user_state'] === 0 ? 1 : 0;
                $this->userModel->updateUserState($userIndex, $newState);
                $this->auditAdminAction('user.toggle_state', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id'], 'new_state' => $newState]);
                $stateLabel = $newState === 0 ? '활성화' : '비활성화';
                $this->session->setFlash('success', "'{$user['user_id']}'가 {$stateLabel}되었습니다.");
                break;

            case 'update_posting_limit':
                $newLimit = (int)$this->getParam('user_posting_limit', 10);
                if ($newLimit < 0 || $newLimit > 10000) {
                    $this->auditAdminAction('user.update_posting_limit', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id'], 'reason' => 'invalid_posting_limit', 'requested_limit' => $newLimit], 'rejected');
                    $this->session->setFlash('error', '게시글 제한은 0~10000 사이여야 합니다.');
                    break;
                }
                $this->userModel->updateUserPostingLimit($userIndex, $newLimit);
                $this->auditAdminAction('user.update_posting_limit', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id'], 'new_limit' => $newLimit]);
                $this->session->setFlash('success', "'{$user['user_id']}'의 게시글 제한이 {$newLimit}으로 변경되었습니다.");
                break;

            case 'reset_password':
                $newPassword = $this->getParam('new_password', '');
                if (empty($newPassword)) {
                    $this->auditAdminAction('user.reset_password', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id'], 'reason' => 'empty_password'], 'rejected');
                    $this->session->setFlash('error', '새 비밀번호를 입력해주세요.');
                    break;
                }
                $this->userModel->resetUserPassword($userIndex, $newPassword);
                $this->auditAdminAction('user.reset_password', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id']]);
                $this->session->setFlash('success', "'{$user['user_id']}'의 비밀번호가 초기화되었습니다.");
                break;

            default:
                $this->auditAdminAction('user.update', ['target_user_index' => $userIndex, 'target_user_id' => $user['user_id'], 'reason' => 'unknown_action', 'action' => $action], 'rejected');
                $this->session->setFlash('error', '알 수 없는 작업입니다.');
        }

        $this->redirect($this->getAdminUsersUrl());
    }

    public function categories(): void
    {
        $categories = $this->categoryModel->getAllForAdmin();

        $levelLabels = [
            0 => '슈퍼관리자',
            1 => '관리자',
            2 => '에디터',
            3 => '작성자',
            4 => '구독자',
        ];

        $levelOptions = [
            0 => '슈퍼관리자만',
            1 => '관리자 이상',
            2 => '에디터 이상',
            3 => '작성자 이상',
            4 => '모든 사용자',
        ];

        $this->renderLayout('admin', 'admin/categories', $this->adminData('categories', [
            'categories' => $categories,
            'levelLabels' => $levelLabels,
            'levelOptions' => $levelOptions,
            'csrfToken' => $this->view->csrfToken(),
        ]));
    }

    public function createCategory(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('category.create', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $name = trim($this->sanitizeInput($this->getParam('category_name', '')));
        $readLevel = (int)$this->getParam('category_read_level', 4);
        $writeLevel = (int)$this->getParam('category_write_level', 1);

        if (empty($name)) {
            $this->auditAdminAction('category.create', ['reason' => 'empty_name'], 'rejected');
            $this->session->setFlash('error', '카테고리 이름은 필수입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        if (mb_strlen($name) > 50) {
            $this->auditAdminAction('category.create', ['category_name' => $name, 'reason' => 'name_too_long'], 'rejected');
            $this->session->setFlash('error', '카테고리 이름은 50자 이내여야 합니다.');
            $this->redirect('/admin/categories');
            return;
        }

        if (!in_array($readLevel, [0, 1, 2, 3, 4], true) || !in_array($writeLevel, [0, 1, 2, 3, 4], true)) {
            $this->auditAdminAction('category.create', ['category_name' => $name, 'reason' => 'invalid_level', 'read_level' => $readLevel, 'write_level' => $writeLevel], 'rejected');
            $this->session->setFlash('error', '유효하지 않은 권한 레벨입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $order = $this->categoryModel->getMaxOrder() + 1;
        $this->categoryModel->create($name, $order, $readLevel, $writeLevel);
        $this->auditAdminAction('category.create', ['category_name' => $name, 'read_level' => $readLevel, 'write_level' => $writeLevel, 'order' => $order]);
        $this->session->setFlash('success', "카테고리 '{$name}'이(가) 생성되었습니다.");
        $this->redirect('/admin/categories');
    }

    public function updateCategory(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('category.update', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $categoryId = (int)$this->getParam('category_index', 0);
        if ($categoryId <= 0) {
            $this->auditAdminAction('category.update', ['reason' => 'invalid_category_index', 'category_index' => $categoryId], 'rejected');
            $this->session->setFlash('error', '유효하지 않은 카테고리입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $category = $this->categoryModel->getByIdForAdmin($categoryId);
        if (!$category) {
            $this->auditAdminAction('category.update', ['reason' => 'category_not_found', 'category_index' => $categoryId], 'rejected');
            $this->session->setFlash('error', '카테고리를 찾을 수 없습니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $name = trim($this->sanitizeInput($this->getParam('category_name', '')));
        $readLevel = (int)$this->getParam('category_read_level', 4);
        $writeLevel = (int)$this->getParam('category_write_level', 1);

        if (empty($name)) {
            $this->auditAdminAction('category.update', ['category_index' => $categoryId, 'reason' => 'empty_name'], 'rejected');
            $this->session->setFlash('error', '카테고리 이름은 필수입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        if (mb_strlen($name) > 50) {
            $this->auditAdminAction('category.update', ['category_index' => $categoryId, 'category_name' => $name, 'reason' => 'name_too_long'], 'rejected');
            $this->session->setFlash('error', '카테고리 이름은 50자 이내여야 합니다.');
            $this->redirect('/admin/categories');
            return;
        }

        if (!in_array($readLevel, [0, 1, 2, 3, 4], true) || !in_array($writeLevel, [0, 1, 2, 3, 4], true)) {
            $this->auditAdminAction('category.update', ['category_index' => $categoryId, 'category_name' => $name, 'reason' => 'invalid_level', 'read_level' => $readLevel, 'write_level' => $writeLevel], 'rejected');
            $this->session->setFlash('error', '유효하지 않은 권한 레벨입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $this->categoryModel->update($categoryId, $name, $readLevel, $writeLevel);
        $this->auditAdminAction('category.update', ['category_index' => $categoryId, 'category_name' => $name, 'read_level' => $readLevel, 'write_level' => $writeLevel]);
        $this->session->setFlash('success', "카테고리 '{$name}'이(가) 수정되었습니다.");
        $this->redirect('/admin/categories');
    }

    public function deleteCategory(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('category.delete', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $categoryId = (int)$this->getParam('category_index', 0);
        if ($categoryId <= 0) {
            $this->auditAdminAction('category.delete', ['reason' => 'invalid_category_index', 'category_index' => $categoryId], 'rejected');
            $this->session->setFlash('error', '유효하지 않은 카테고리입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $category = $this->categoryModel->getByIdForAdmin($categoryId);
        if (!$category) {
            $this->auditAdminAction('category.delete', ['reason' => 'category_not_found', 'category_index' => $categoryId], 'rejected');
            $this->session->setFlash('error', '카테고리를 찾을 수 없습니다.');
            $this->redirect('/admin/categories');
            return;
        }

        if ($this->categoryModel->delete($categoryId)) {
            $this->auditAdminAction('category.delete', ['category_index' => $categoryId, 'category_name' => $category['category_name']]);
            $this->session->setFlash('success', "카테고리 '{$category['category_name']}'이(가) 삭제되었습니다.");
        } else {
            $postCount = $this->categoryModel->getPostCount($categoryId);
            $this->auditAdminAction('category.delete', ['category_index' => $categoryId, 'category_name' => $category['category_name'], 'reason' => 'category_has_posts', 'post_count' => $postCount], 'rejected');
            $this->session->setFlash('error', "게시글이 {$postCount}개 존재하여 삭제할 수 없습니다. 게시글을 먼저 이동하거나 삭제해주세요.");
        }

        $this->redirect('/admin/categories');
    }

    public function reorderCategory(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('category.reorder', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $categoryId = (int)$this->getParam('category_index', 0);
        $direction = $this->sanitizeInput($this->getParam('direction', ''));

        if ($categoryId <= 0 || !in_array($direction, ['up', 'down'], true)) {
            $this->auditAdminAction('category.reorder', ['category_index' => $categoryId, 'direction' => $direction, 'reason' => 'invalid_request'], 'rejected');
            $this->session->setFlash('error', '유효하지 않은 요청입니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $categories = $this->categoryModel->getAllForAdmin();
        $currentIdx = null;
        foreach ($categories as $i => $cat) {
            if ((int)$cat['category_index'] === $categoryId) {
                $currentIdx = $i;
                break;
            }
        }

        if ($currentIdx === null) {
            $this->auditAdminAction('category.reorder', ['category_index' => $categoryId, 'direction' => $direction, 'reason' => 'category_not_found'], 'rejected');
            $this->session->setFlash('error', '카테고리를 찾을 수 없습니다.');
            $this->redirect('/admin/categories');
            return;
        }

        $swapIdx = $direction === 'up' ? $currentIdx - 1 : $currentIdx + 1;
        if ($swapIdx < 0 || $swapIdx >= count($categories)) {
            $this->auditAdminAction('category.reorder', ['category_index' => $categoryId, 'direction' => $direction, 'reason' => 'boundary_reached'], 'rejected');
            $this->redirect('/admin/categories');
            return;
        }

        $this->categoryModel->swapOrder(
            (int)$categories[$currentIdx]['category_index'],
            (int)$categories[$swapIdx]['category_index']
        );
        $this->auditAdminAction('category.reorder', [
            'category_index' => $categoryId,
            'direction' => $direction,
            'swap_with_category_index' => (int)$categories[$swapIdx]['category_index'],
        ]);
        $this->redirect('/admin/categories');
    }

    public function cache(): void
    {
        $cache = Cache::getInstance();
        $fileDetails = $cache->getFileDetails();
        $config = $cache->getConfig();

        $this->renderLayout('admin', 'admin/cache', $this->adminData('cache', [
            'fileDetails' => $fileDetails,
            'cacheConfig' => $config['cache'],
            'cacheTtl' => $config['cache_ttl'],
            'invalidation' => $config['cache_invalidation'],
            'performance' => $config['performance'],
            'csrfToken' => $this->view->csrfToken(),
        ]));
    }

    public function clearAllCache(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('cache.clear_all', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/cache');
            return;
        }

        $cache = Cache::getInstance();
        $cache->clear();
        $this->auditAdminAction('cache.clear_all');
        $this->session->setFlash('success', '모든 캐시가 삭제되었습니다.');
        $this->redirect('/admin/cache');
    }

    public function clearExpiredCache(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('cache.clear_expired', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/cache');
            return;
        }

        $cache = Cache::getInstance();
        $count = $cache->clearExpired();
        $this->auditAdminAction('cache.clear_expired', ['deleted_count' => $count]);
        $this->session->setFlash('success', "만료된 캐시 {$count}개가 삭제되었습니다.");
        $this->redirect('/admin/cache');
    }

    public function clearPatternCache(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('cache.clear_pattern', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/cache');
            return;
        }

        $pattern = $this->sanitizeInput($this->getParam('pattern', ''));
        if (empty($pattern)) {
            $this->auditAdminAction('cache.clear_pattern', ['reason' => 'empty_pattern'], 'rejected');
            $this->session->setFlash('error', '패턴을 입력해주세요.');
            $this->redirect('/admin/cache');
            return;
        }

        $cache = Cache::getInstance();

        if ($pattern === '__all__') {
            $cache->clear();
            $this->auditAdminAction('cache.clear_pattern', ['pattern' => $pattern, 'cleared_all' => true]);
            $this->session->setFlash('success', '모든 캐시가 삭제되었습니다.');
            $this->redirect('/admin/cache');
            return;
        }

        $cache->deletePattern($pattern);
        $this->auditAdminAction('cache.clear_pattern', ['pattern' => $pattern, 'cleared_all' => false]);
        $this->session->setFlash('success', "'{$pattern}' 패턴 캐시가 삭제되었습니다.");
        $this->redirect('/admin/cache');
    }

    public function warmupCache(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('cache.warmup', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/cache');
            return;
        }

        $userLevel = $this->auth->getCurrentUserLevel();

        $categoryModel = new Category();
        $categoryModel->getReadAll($userLevel);
        $categoryModel->getWriteAll($userLevel);

        $postModel = new \Blog\Models\Post();
        $postModel->getMetaAll($userLevel, 1, 10);
        $postModel->getTotalCount();

        $this->auditAdminAction('cache.warmup', ['user_level' => $userLevel]);
        $this->session->setFlash('success', '캐시 워밍업이 완료되었습니다.');
        $this->redirect('/admin/cache');
    }

    public function stockSubscriptions(): void
    {
        $page = isset($_GET['page']) ? max(1, intval($_GET['page'])) : 1;
        $market = $this->normalizeAdminMarket($_GET['market'] ?? 'KR');
        $search = isset($_GET['search']) ? $this->sanitizeInput($_GET['search']) : '';
        $perPage = 100;

        $listResult = $this->stockModel->getAdminStockListWithCount($page, $perPage, $market, $search);
        $stocks = $listResult['stocks'];
        $totalCount = $listResult['total'];
        $totalPages = (int)max(1, ceil($totalCount / $perPage));
        $registeredCodes = $this->stockModel->getRegisteredStockCodeSet();
        $selectionMarketMap = $this->stockModel->getSelectionMarketMap();
        $registeredCountsByMarket = $this->stockModel->getRegisteredCountsByMarket();

        $this->renderLayout('admin', 'admin/stocks', $this->adminData('stocks', [
            'stocks' => $stocks,
            'currentPage' => $page,
            'totalPages' => $totalPages,
            'totalCount' => $totalCount,
            'currentMarket' => $market,
            'searchQuery' => $search,
            'registeredCodes' => $registeredCodes,
            'selectionMarketMap' => $selectionMarketMap,
            'registeredCountsByMarket' => $registeredCountsByMarket,
            'registeredCount' => count($registeredCodes),
            'forceSelectionSync' => isset($_GET['sync']) && $_GET['sync'] === '1',
            'additionalCss' => ['/css/admin.css', '/css/stocks.css'],
        ]));
    }

    public function updateStockSubscriptions(): void
    {
        $market = $this->normalizeAdminMarket($_POST['current_market'] ?? 'KR');
        $search = isset($_POST['current_search']) ? $this->sanitizeInput($_POST['current_search']) : '';
        $page = isset($_POST['current_page']) ? max(1, intval($_POST['current_page'])) : 1;

        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('stock.subscriptions.update', ['reason' => 'csrf_invalid', 'market' => $market, 'page' => $page], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다. 다시 시도해주세요.');
            $this->redirect($this->buildStockRedirectUrl($market, $search, $page));
            return;
        }

        $selectedCodes = $_POST['selected_codes'] ?? [];
        if (!is_array($selectedCodes)) {
            $selectedCodes = [];
        }

        $selectedCodes = array_values(array_filter(array_map(function ($value) {
            return $this->sanitizeInput((string)$value);
        }, $selectedCodes)));

        try {
            $result = $this->stockModel->replaceRegisteredSubscriptions($selectedCodes);
            $this->auditAdminAction('stock.subscriptions.update', [
                'market' => $market,
                'page' => $page,
                'search' => $search,
                'selected_count' => count($selectedCodes),
                'kr_count' => $result['kr_count'],
                'us_count' => $result['us_count'],
                'coin_count' => $result['coin_count'],
            ]);
            $this->session->setFlash(
                'success',
                sprintf(
                    '구독 종목을 저장했습니다. 한국 %d건, 미국 %d건, 코인 %d건이 반영되었습니다.',
                    $result['kr_count'],
                    $result['us_count'],
                    $result['coin_count']
                )
            );
            $this->redirect($this->buildStockRedirectUrl($market, $search, $page, true));
            return;
        } catch (\InvalidArgumentException $e) {
            $this->auditAdminAction('stock.subscriptions.update', ['market' => $market, 'page' => $page, 'search' => $search, 'selected_count' => count($selectedCodes), 'reason' => 'invalid_argument', 'error' => $e->getMessage()], 'rejected');
            $this->session->setFlash('error', $e->getMessage());
            $this->redirect($this->buildStockRedirectUrl($market, $search, $page));
            return;
        } catch (\Throwable $e) {
            $this->auditAdminAction('stock.subscriptions.update', ['market' => $market, 'page' => $page, 'search' => $search, 'selected_count' => count($selectedCodes), 'reason' => 'exception', 'error' => $e->getMessage()], 'error');
            error_log('Stock admin save failed: ' . $e->getMessage());
            $this->session->setFlash('error', '구독 종목 저장 중 오류가 발생했습니다.');
            $this->redirect($this->buildStockRedirectUrl($market, $search, $page));
            return;
        }
    }

    public function wol(): void
    {
        $devices = $this->wolDeviceModel->getAll();

        $this->renderLayout('admin', 'admin/wol', $this->adminData('wol', [
            'devices' => $devices,
            'csrfToken' => $this->view->csrfToken(),
        ]));
    }

    public function wolExecute(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('wol.execute', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/wol');
            return;
        }

        $deviceId = (int)$this->getParam('device_id', 0);
        $device = $this->wolDeviceModel->getById($deviceId);

        if (!$device) {
            $this->auditAdminAction('wol.execute', ['device_id' => $deviceId, 'reason' => 'device_not_found'], 'rejected');
            $this->session->setFlash('error', '등록되지 않은 장치입니다.');
            $this->redirect('/admin/wol');
            return;
        }

        $mac = $device['wol_device_mac_address'];
        $broadcastIp = trim((string)$device['wol_device_ip_range']);
        if (filter_var($broadcastIp, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) === false) {
            $this->auditAdminAction('wol.execute', ['device_id' => $deviceId, 'device_name' => $device['wol_device_name'], 'reason' => 'invalid_broadcast_ip', 'broadcast_ip' => $broadcastIp], 'rejected');
            $this->session->setFlash('error', '브로드캐스트 IP 형식이 올바르지 않습니다.');
            $this->redirect('/admin/wol');
            return;
        }
        $ports = [9, 7];
        $errors = [];
        $result = false;

        foreach ($ports as $port) {
            $sendResult = $this->sendMagicPacket($mac, $broadcastIp, $port);
            if ($sendResult !== true) {
                $errors[] = "{$port}번 포트: {$sendResult}";
                continue;
            }

            $result = true;
        }

        if ($result === true) {
            $this->auditAdminAction('wol.execute', ['device_id' => $deviceId, 'device_name' => $device['wol_device_name'], 'broadcast_ip' => $broadcastIp, 'ports' => $ports]);
            $this->session->setFlash('success', "'{$device['wol_device_name']}'에 WOL 패킷을 전송했습니다.");
        } else {
            $this->auditAdminAction('wol.execute', ['device_id' => $deviceId, 'device_name' => $device['wol_device_name'], 'broadcast_ip' => $broadcastIp, 'errors' => $errors], 'error');
            $this->session->setFlash('error', 'WOL 패킷 전송 실패: ' . implode(' | ', $errors));
        }

        $this->redirect('/admin/wol');
    }

    public function wolCreateDevice(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('wol.device.create', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/wol');
            return;
        }

        $name = trim($this->sanitizeInput($this->getParam('device_name', '')));
        $ipRange = trim($this->sanitizeInput($this->getParam('ip_range', '')));
        $mac = trim($this->sanitizeInput($this->getParam('mac_address', '')));

        if (empty($name) || empty($ipRange) || empty($mac)) {
            $this->auditAdminAction('wol.device.create', ['device_name' => $name, 'ip_range' => $ipRange, 'reason' => 'required_missing'], 'rejected');
            $this->session->setFlash('error', '모든 필드를 입력해주세요.');
            $this->redirect('/admin/wol');
            return;
        }

        $macClean = str_replace(['-', ':'], '', $mac);
        if (strlen($macClean) !== 12 || !ctype_xdigit($macClean)) {
            $this->auditAdminAction('wol.device.create', ['device_name' => $name, 'ip_range' => $ipRange, 'reason' => 'invalid_mac_format'], 'rejected');
            $this->session->setFlash('error', 'MAC 주소 형식이 올바르지 않습니다.');
            $this->redirect('/admin/wol');
            return;
        }

        $this->wolDeviceModel->create($name, $ipRange, $mac);
        $this->auditAdminAction('wol.device.create', ['device_name' => $name, 'ip_range' => $ipRange]);
        $this->session->setFlash('success', "'{$name}' 장치가 등록되었습니다.");
        $this->redirect('/admin/wol');
    }

    public function wolUpdateDevice(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('wol.device.update', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/wol');
            return;
        }

        $deviceId = (int)$this->getParam('device_id', 0);
        $device = $this->wolDeviceModel->getById($deviceId);
        if (!$device) {
            $this->auditAdminAction('wol.device.update', ['device_id' => $deviceId, 'reason' => 'device_not_found'], 'rejected');
            $this->session->setFlash('error', '장치를 찾을 수 없습니다.');
            $this->redirect('/admin/wol');
            return;
        }

        $name = trim($this->sanitizeInput($this->getParam('device_name', '')));
        $ipRange = trim($this->sanitizeInput($this->getParam('ip_range', '')));
        $mac = trim($this->sanitizeInput($this->getParam('mac_address', '')));

        if (empty($name) || empty($ipRange) || empty($mac)) {
            $this->auditAdminAction('wol.device.update', ['device_id' => $deviceId, 'device_name' => $name, 'ip_range' => $ipRange, 'reason' => 'required_missing'], 'rejected');
            $this->session->setFlash('error', '모든 필드를 입력해주세요.');
            $this->redirect('/admin/wol');
            return;
        }

        $macClean = str_replace(['-', ':'], '', $mac);
        if (strlen($macClean) !== 12 || !ctype_xdigit($macClean)) {
            $this->auditAdminAction('wol.device.update', ['device_id' => $deviceId, 'device_name' => $name, 'ip_range' => $ipRange, 'reason' => 'invalid_mac_format'], 'rejected');
            $this->session->setFlash('error', 'MAC 주소 형식이 올바르지 않습니다.');
            $this->redirect('/admin/wol');
            return;
        }

        $this->wolDeviceModel->update($deviceId, $name, $ipRange, $mac);
        $this->auditAdminAction('wol.device.update', ['device_id' => $deviceId, 'device_name' => $name, 'ip_range' => $ipRange]);
        $this->session->setFlash('success', "'{$name}' 장치가 수정되었습니다.");
        $this->redirect('/admin/wol');
    }

    public function wolDeleteDevice(): void
    {
        if (!$this->validateCsrfToken()) {
            $this->auditAdminAction('wol.device.delete', ['reason' => 'csrf_invalid'], 'denied');
            $this->session->setFlash('error', '잘못된 요청입니다.');
            $this->redirect('/admin/wol');
            return;
        }

        $deviceId = (int)$this->getParam('device_id', 0);
        $device = $this->wolDeviceModel->getById($deviceId);
        if (!$device) {
            $this->auditAdminAction('wol.device.delete', ['device_id' => $deviceId, 'reason' => 'device_not_found'], 'rejected');
            $this->session->setFlash('error', '장치를 찾을 수 없습니다.');
            $this->redirect('/admin/wol');
            return;
        }

        $this->wolDeviceModel->delete($deviceId);
        $this->auditAdminAction('wol.device.delete', ['device_id' => $deviceId, 'device_name' => $device['wol_device_name']]);
        $this->session->setFlash('success', "'{$device['wol_device_name']}' 장치가 삭제되었습니다.");
        $this->redirect('/admin/wol');
    }

    private function auditAdminAction(string $action, array $details = [], string $result = 'success'): void
    {
        $logPayload = [
            'action' => $action,
            'result' => $result,
            'actor_user_index' => $this->auth->getCurrentUserIndex(),
            'actor_user_id' => $this->auth->getCurrentUserId(),
            'actor_user_level' => $this->auth->getCurrentUserLevel(),
            'ip' => $this->getClientIp(),
            'method' => $this->getRequestMethod(),
            'uri' => $_SERVER['REQUEST_URI'] ?? '',
            'details' => $details,
        ];

        $message = json_encode($logPayload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($message === false) {
            $message = sprintf(
                'action=%s result=%s actor=%s(%s) details=encode_failed',
                $action,
                $result,
                (string)$this->auth->getCurrentUserId(),
                (string)$this->auth->getCurrentUserIndex()
            );
        }

        if ($result === 'error') {
            Logger::error('admin_audit', $message);
            return;
        }

        if ($result === 'rejected' || $result === 'denied') {
            Logger::warn('admin_audit', $message);
            return;
        }

        Logger::info('admin_audit', $message);
    }

    private function getClientIp(): string
    {
        $keys = ['HTTP_X_FORWARDED_FOR', 'HTTP_CLIENT_IP', 'REMOTE_ADDR'];

        foreach ($keys as $key) {
            if (!isset($_SERVER[$key])) {
                continue;
            }

            $raw = trim((string)$_SERVER[$key]);
            if ($raw === '') {
                continue;
            }

            if ($key === 'HTTP_X_FORWARDED_FOR') {
                $parts = explode(',', $raw);
                $candidate = trim((string)$parts[0]);
                return mb_substr($candidate, 0, 100, 'UTF-8');
            }

            return mb_substr($raw, 0, 100, 'UTF-8');
        }

        return '';
    }

    private function sendMagicPacket(string $mac, string $broadcastIp, int $port)
    {
        // MAC 주소 파싱 (XX-XX-XX-XX-XX-XX 또는 XX:XX:XX:XX:XX:XX)
        $macHex = str_replace(['-', ':'], '', $mac);
        if (strlen($macHex) !== 12 || !ctype_xdigit($macHex)) {
            return 'MAC 주소 형식이 올바르지 않습니다.';
        }

        $macBin = pack('H12', $macHex);

        // 매직 패킷: FF x 6 + MAC x 16 = 102 bytes
        $packet = str_repeat(chr(0xFF), 6) . str_repeat($macBin, 16);

        if (!function_exists('socket_create')) {
            return 'WOL 전송 실패: PHP sockets 확장이 비활성화되어 있습니다.';
        }

        $socket = @socket_create(AF_INET, SOCK_DGRAM, SOL_UDP);
        if (!$socket) {
            return '소켓 생성 실패';
        }

        socket_set_option($socket, SOL_SOCKET, SO_BROADCAST, 1);
        $sent = @socket_sendto($socket, $packet, strlen($packet), 0, $broadcastIp, $port);
        socket_close($socket);
        return $sent !== false ? true : '패킷 전송 실패';
    }

    private function normalizeAdminMarket(string $market): string
    {
        $market = strtoupper(trim($this->sanitizeInput($market)));
        return in_array($market, ['KR', 'US', 'COIN'], true) ? $market : 'KR';
    }

    private function buildStockRedirectUrl(string $market, string $search, int $page, bool $sync = false): string
    {
        $params = [
            'market' => $market,
            'page' => $page,
        ];

        if ($search !== '') {
            $params['search'] = $search;
        }

        if ($sync) {
            $params['sync'] = '1';
        }

        return '/admin/stocks?' . http_build_query($params);
    }
}
