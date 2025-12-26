<?php

namespace Blog\Controllers;

use Blog\Models\Post;
use Blog\Models\Category;
use Blog\Models\User;
use Blog\Core\Logger;

class PostController extends BaseController
{
    private $postModel;
    private $categoryModel;
    private $userModel;

    public function __construct()
    {
        parent::__construct();
        $this->postModel = new Post();
        $this->categoryModel = new Category();
        $this->userModel = new User();
    }

    public function show($postId = null): void
    {
        // 쿼리스트링 fallback 처리
        if ($postId === null) {
            $postId = (int)$this->getParam('posting_index', -1);
        } else {
            $postId = (int)$postId;
        }
        
        if ($postId <= 0) {
            Logger::warn('BlogPost', "show invalid id={$postId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '잘못된 접근입니다.');
            $this->redirect('/index.php');
            return;
        }

        $userLevel = $this->auth->getCurrentUserLevel();
        $post = $this->postModel->getDetailById($userLevel, $postId);

        if (!$post) {
            Logger::warn('BlogPost', "show not_found id={$postId} level={$userLevel}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글을 찾을 수 없습니다.');
            $this->redirect('/index.php');
        }

        // 조회수 증가
        $this->postModel->incrementReadCount($postId);

        // 방문자 수 업데이트
        $this->userModel->updateVisitorCount();

        $categories = $this->categoryModel->getReadAll($userLevel);
        $visitorCount = $this->userModel->getVisitorCount();
        
        // 현재 포스팅의 카테고리를 currentCategory로 설정
        $currentCategory = $post['category_index'] ?? null;
        
        // 카테고리 쓰기 권한 확인
        $canWriteToCategory = $this->categoryModel->isWriteAuth($userLevel, $post['category_index']);
        
        // 사용자 게시글 작성 제한 정보
        $userPostingInfo = null;
        if ($this->auth->isLoggedIn()) {
            $userIndex = $this->auth->getCurrentUserIndex();
            $userPostingInfo = $this->userModel->getPostingLimitInfo($userIndex);
        }
        
        $this->renderLayout('main', 'posts/show', [
            'post' => $post,
            'categories' => $categories,
            'visitorCount' => $visitorCount,
            'currentCategory' => $currentCategory,
            'canWriteToCategory' => $canWriteToCategory,
            'userLevel' => $userLevel,
            'userPostingInfo' => $userPostingInfo,
            'csrfToken' => $this->view->csrfToken()
        ]);
    }

    public function createForm(): void
    {
        $this->auth->requireWritePermission();
        
        $categoryId = (int)$this->getParam('category_index', -1);
        $userLevel = $this->auth->getCurrentUserLevel();
        $userIndex = $this->auth->getCurrentUserIndex();
        
        // 사용자의 게시글 작성 제한 확인
        $userPostingInfo = $this->userModel->getPostingLimitInfo($userIndex);
        
        // 제한에 도달한 경우 메시지 표시 후 index로 리다이렉트
        if ($userPostingInfo && $userPostingInfo['is_limited']) {
            Logger::warn('BlogPost', "createForm blocked_by_limit user={$userIndex} count={$userPostingInfo['current_count']} limit={$userPostingInfo['limit']}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글 작성 제한에 도달했습니다. (' . $userPostingInfo['current_count'] . '/' . $userPostingInfo['limit'] . ')');
            $this->redirect('/index.php');
            return;
        }
        
        $categories = $this->categoryModel->getWriteAll($userLevel);
        
        $this->renderLayout('main', 'posts/editor', [
            'categories' => $categories,
            'selectedCategory' => $categoryId > 0 ? $categoryId : null,
            'csrfToken' => $this->view->csrfToken(),
            'isEdit' => false
        ]);
    }

    public function create(): void
    {
        $this->auth->requireWritePermission();

        if (!$this->isPost()) {
            Logger::warn('BlogPost', 'create not_post_request', ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->redirect('/writer.php');
        }

        if (!$this->validateCsrfToken()) {
            Logger::warn('BlogPost', 'create csrf_invalid', ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '보안 토큰이 유효하지 않습니다.');
            $this->redirect('/writer.php');
        }

        // 사용자의 게시글 작성 제한 확인
        $userIndex = $this->auth->getCurrentUserIndex();
        $userPostingInfo = $this->userModel->getPostingLimitInfo($userIndex);
        
        if ($userPostingInfo && $userPostingInfo['is_limited']) {
            Logger::warn('BlogPost', "create blocked_by_limit user={$userIndex} count={$userPostingInfo['current_count']} limit={$userPostingInfo['limit']}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글 작성 제한에 도달했습니다. (' . $userPostingInfo['current_count'] . '/' . $userPostingInfo['limit'] . ')');
            $this->redirect('/index.php');
            return;
        }

        $title = $this->sanitizeInput($this->getParam('title', ''));
        $content = $this->getParam('content', '');
        $categoryId = (int)$this->getParam('category_index', -1);

        $errors = $this->validateRequired([
            'title' => $title,
            'content' => $content,
            'category_index' => $categoryId
        ], ['title', 'content', 'category_index']);

        if (!empty($errors)) {
            Logger::warn('BlogPost', "create validation_error user={$userIndex} category={$categoryId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '모든 필드를 입력해주세요.');
            $this->redirect('/writer.php');
        }

        if ($categoryId <= 0) {
            Logger::warn('BlogPost', "create invalid_category user={$userIndex} category={$categoryId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '카테고리를 선택해주세요.');
            $this->redirect('/writer.php');
        }

        $userIndex = $this->auth->getCurrentUserIndex();
        $userLevel = $this->auth->getCurrentUserLevel();
        
        try {
            $postId = $this->postModel->create([
                'title' => $title,
                'content' => $content,
                'category_index' => $categoryId,
                'user_index' => $userIndex,
                'user_level' => $userLevel
            ]);

            
            Logger::info('BlogPost', "create success post={$postId} user={$userIndex} category={$categoryId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);

            $this->session->setFlash('success', '게시글이 작성되었습니다.');
            $this->redirect("/reader.php?posting_index={$postId}");
        } catch (\Exception $e) {
            Logger::error('BlogPost', "create fail user={$userIndex} category={$categoryId} error=" . $e->getMessage(), ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글 작성 중 오류가 발생했습니다.');
            $this->redirect('/writer.php');
        }
    }

    public function editForm($postId = null): void
    {
        $this->auth->requireLogin();

        // URL 파라미터에서 postId 가져오기 (문자열로 전달되므로 int로 변환)
        if ($postId === null) {
            $postId = (int)$this->getParam('posting_index', -1);
        } else {
            $postId = (int)$postId;
        }
        if ($postId <= 0) {
            Logger::warn('BlogPost', "editForm invalid_id id={$postId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '잘못된 접근입니다.');
            $this->redirect('/index.php');
            return;
        }
        
        $userLevel = $this->auth->getCurrentUserLevel();
        $post = $this->postModel->getDetailById($userLevel, $postId);
        
        if (!$post) {
            Logger::warn('BlogPost', "editForm not_found id={$postId} level={$userLevel}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글을 찾을 수 없습니다.');
            $this->redirect('/index.php');
        }

        $currentUserIndex = $this->auth->getCurrentUserIndex();
        if ($post['user_index'] !== $currentUserIndex) {
            Logger::warn('BlogPost', "editForm no_permission id={$postId} user={$currentUserIndex}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '수정 권한이 없습니다.');
            $this->redirect('/index.php');
        }

        $categories = $this->categoryModel->getWriteAll($userLevel);
        
        $this->renderLayout('main', 'posts/editor', [
            'post' => $post,
            'categories' => $categories,
            'csrfToken' => $this->view->csrfToken(),
            'isEdit' => true
        ]);
    }

    public function update($postId): void
    {
        $this->auth->requireLogin();
        
        // URL 파라미터를 int로 변환
        $postId = (int)$postId;

        if (!$this->isPost()) {
            Logger::warn('BlogPost', "update not_post_request id={$postId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->redirect("/post/edit/{$postId}");
        }

        if (!$this->validateCsrfToken()) {
            Logger::warn('BlogPost', "update csrf_invalid id={$postId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '보안 토큰이 유효하지 않습니다.');
            $this->redirect("/post/edit/{$postId}");
        }

        $userLevel = $this->auth->getCurrentUserLevel();
        $post = $this->postModel->getDetailById($userLevel, $postId);
        
        if (!$post) {
            Logger::warn('BlogPost', "update not_found id={$postId} level={$userLevel}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글을 찾을 수 없습니다.');
            $this->redirect('/index.php');
        }

        $currentUserIndex = $this->auth->getCurrentUserIndex();
        if ($post['user_index'] !== $currentUserIndex) {
            Logger::warn('BlogPost', "update no_permission id={$postId} user={$currentUserIndex}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '수정 권한이 없습니다.');
            $this->redirect('/index.php');
        }

        // 사용자의 게시글 작성 제한 확인 (수정은 제한에 영향받지 않지만 일관성을 위해)
        $userPostingInfo = $this->userModel->getPostingLimitInfo($currentUserIndex);
        
        if ($userPostingInfo && $userPostingInfo['is_limited']) {
            Logger::warn('BlogPost', "update blocked_by_limit user={$currentUserIndex} count={$userPostingInfo['current_count']} limit={$userPostingInfo['limit']}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글 작성 제한에 도달했습니다. (' . $userPostingInfo['current_count'] . '/' . $userPostingInfo['limit'] . ')');
            $this->redirect('/index.php');
            return;
        }

        $title = $this->sanitizeInput($this->getParam('title', ''));
        $content = $this->getParam('content', '');
        $categoryId = (int)$this->getParam('category_index', -1);

        $errors = $this->validateRequired([
            'title' => $title,
            'content' => $content,
            'category_index' => $categoryId
        ], ['title', 'content', 'category_index']);

        if (!empty($errors)) {
            Logger::warn('BlogPost', "update validation_error id={$postId} user={$currentUserIndex} category={$categoryId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '모든 필드를 입력해주세요.');
            $this->redirect("/post/edit/{$postId}");
        }

        if ($categoryId <= 0) {
            Logger::warn('BlogPost', "update invalid_category id={$postId} user={$currentUserIndex} category={$categoryId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '카테고리를 선택해주세요.');
            $this->redirect("/post/edit/{$postId}");
        }

        try {
            $this->postModel->update($postId, [
                'title' => $title,
                'content' => $content,
                'category_index' => $categoryId
            ]);

            Logger::info('BlogPost', "update success id={$postId} user={$currentUserIndex} category={$categoryId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('success', '게시글이 수정되었습니다.');
            $this->redirect("/reader.php?posting_index={$postId}");
        } catch (\Exception $e) {
            Logger::error('BlogPost', "update fail id={$postId} user={$currentUserIndex} error=" . $e->getMessage(), ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글 수정 중 오류가 발생했습니다.');
            $this->redirect("/post/edit/{$postId}");
        }
    }

    public function enable($postId): void
    {
        $this->auth->requireLogin();
        
        // URL 파라미터를 int로 변환
        $postId = (int)$postId;

        if (!$this->isPost()) {
            Logger::warn('BlogPost', "enable not_post_request id={$postId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->redirect('/index.php');
        }

        if (!$this->validateCsrfToken()) {
            Logger::warn('BlogPost', "enable csrf_invalid id={$postId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '보안 토큰이 유효하지 않습니다.');
            $this->redirect('/index.php');
        }

        $userLevel = $this->auth->getCurrentUserLevel();
        $post = $this->postModel->getDetailById($userLevel, $postId);
        
        if (!$post) {
            Logger::warn('BlogPost', "enable not_found id={$postId} level={$userLevel}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글을 찾을 수 없습니다.');
            $this->redirect('/index.php');
        }

        $currentUserIndex = $this->auth->getCurrentUserIndex();
        if ($post['user_index'] !== $currentUserIndex) {
            Logger::warn('BlogPost', "enable no_permission id={$postId} user={$currentUserIndex}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '복구 권한이 없습니다.');
            $this->redirect('/index.php');
        }

        try {
            $this->postModel->enable($postId);
            Logger::info('BlogPost', "enable success id={$postId} user={$currentUserIndex}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('success', '게시글이 복구되었습니다.');
        } catch (\Exception $e) {
            Logger::error('BlogPost', "enable fail id={$postId} user={$currentUserIndex} error=" . $e->getMessage(), ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글 복구 중 오류가 발생했습니다.');
        }

        $this->redirect('/index.php');
    }

    public function disable($postId): void
    {
        $this->auth->requireLogin();
        
        // URL 파라미터를 int로 변환
        $postId = (int)$postId;

        if (!$this->isPost()) {
            Logger::warn('BlogPost', "disable not_post_request id={$postId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->redirect('/index.php');
        }

        if (!$this->validateCsrfToken()) {
            Logger::warn('BlogPost', "disable csrf_invalid id={$postId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '보안 토큰이 유효하지 않습니다.');
            $this->redirect('/index.php');
        }

        $userLevel = $this->auth->getCurrentUserLevel();
        $post = $this->postModel->getDetailById($userLevel, $postId);
        
        if (!$post) {
            Logger::warn('BlogPost', "disable not_found id={$postId} level={$userLevel}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글을 찾을 수 없습니다.');
            $this->redirect('/index.php');
        }

        $currentUserIndex = $this->auth->getCurrentUserIndex();
        
        // 게시글 작성자이거나 카테고리 쓰기 권한이 있는 경우에만 삭제 가능
        $canDelete = ($post['user_index'] === $currentUserIndex) || $this->categoryModel->isWriteAuth($userLevel, $post['category_index']);
        
        if (!$canDelete) {
            Logger::warn('BlogPost', "disable no_permission id={$postId} user={$currentUserIndex}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '삭제 권한이 없습니다.');
            $this->redirect('/index.php');
        }

        try {
            $this->postModel->disable($postId);
            Logger::info('BlogPost', "disable success id={$postId} user={$currentUserIndex}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('success', '게시글이 삭제되었습니다.');
        } catch (\Exception $e) {
            Logger::error('BlogPost', "disable fail id={$postId} user={$currentUserIndex} error=" . $e->getMessage(), ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '게시글 삭제 중 오류가 발생했습니다.');
        }

        $this->redirect('/index.php');
    }
}
