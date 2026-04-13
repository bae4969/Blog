<?php

namespace Blog\Controllers;

use Blog\Models\Post;
use Blog\Models\Category;
use Blog\Models\User;
use Blog\Core\Cache;

class HomeController extends BaseController
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

    public function redirectToBlog(): void
    {
        $qs = $_SERVER['QUERY_STRING'] ?? '';
        $this->redirect('/blog' . ($qs ? '?' . $qs : ''));
    }

    public function redirectBySubdomain(): void
    {
        $host = $_SERVER['HTTP_HOST'] ?? 'localhost';
        $subdomain = explode('.', $host)[0];
        $qs = $_SERVER['QUERY_STRING'] ?? '';
        $suffix = $qs ? '?' . $qs : '';

        if ($subdomain === 'stock') {
            $this->redirect('/stocks' . $suffix);
        } else {
            $this->redirect('/blog' . $suffix);
        }
    }

    public function index(): void
    {
        $page = (int)$this->getParam('page', 1);
        $categoryId = (int)$this->getParam('category_index', -1);
        $search = $this->getParam('search_string', '');
        $userLevel = $this->auth->getCurrentUserLevel();
        
        // 카테고리 ID가 -1이면 null로 설정
        $categoryId = $categoryId > 0 ? $categoryId : null;
        
        $this->userModel->updateVisitorCount();
        
        // 데이터 조회
        $posts = $this->postModel->getMetaAll($userLevel, $page, 10, $categoryId, $search);
        $categories = $this->categoryModel->getReadAll($userLevel);
        $totalCount = $this->postModel->getTotalCount($categoryId, $search);
        $visitorCount = $this->userModel->getVisitorCount();
        
        // 페이지네이션 계산
        $totalPages = max(1, ceil($totalCount / 10));

        // 페이지 범위 제한 (존재하지 않는 페이지 요청 차단)
        if ($page > $totalPages) {
            $page = $totalPages;
        }
        
        // 사용자 게시글 작성 제한 정보
        $userPostingInfo = null;
        if ($this->auth->isLoggedIn()) {
            $userIndex = $this->auth->getCurrentUserIndex();
            $userPostingInfo = $this->userModel->getPostingLimitInfo($userIndex);
        }
        
        $data = [
            'posts' => $posts,
            'categories' => $categories,
            'currentPage' => $page,
            'totalPages' => $totalPages,
            'currentCategory' => $categoryId,
            'search' => $search,
            'visitorCount' => $visitorCount,
            'userPostingInfo' => $userPostingInfo,
            'csrfToken' => $this->view->csrfToken()
        ];
        
        $this->renderLayout('blog', 'blog/index', $data);
    }

    public function search(): void
    {
        if (!$this->requireInternalRequest()) {
            return;
        }

        // 검색 요청 Rate Limiting (IP당 분당 20회)
        $ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
        $cache = Cache::getInstance();
        $searchRateKey = Cache::key('search_rate', $ip);
        $searchCount = (int)($cache->get($searchRateKey) ?? 0) + 1;
        $cache->set($searchRateKey, $searchCount, 60);
        if ($searchCount > 20) {
            $this->jsonResponse(['error' => '검색 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.'], 429);
            return;
        }

        $categoryId = (int)$this->getParam('category_index', -1);
        $search = $this->getParam('search_string', '');
        $userLevel = $this->auth->getCurrentUserLevel();
        
        $categoryId = $categoryId > 0 ? $categoryId : null;
        
        $posts = $this->postModel->getMetaAll($userLevel, 1, 10, $categoryId, $search);
        $totalCount = $this->postModel->getTotalCount($categoryId, $search);
        
        $this->json([
            'success' => true,
            'posts' => $posts,
            'totalCount' => $totalCount
        ]);
    }
}
