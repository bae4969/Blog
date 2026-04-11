// 전역 변수
let userInfo = null;
let showState = 0; // 0: 초기, 1: 1열, 2: 2열
let categoryIndex = -1;
let searchString = "";
let pageIndex = 0;
let pageSize = 10;
let pageCount = 0;
let loadCount = 0;
const SESSION_EXPIRED_ALERT_SHOWN_KEY = 'blog.sessionExpiredAlertShown';
let sessionExpiredAlertVisible = false;

// 레이아웃 전환 제어(히스테리시스 & 디바운스)
const BREAKPOINT = 1200;
const HYSTERESIS = 50; // px 여유 구간: 1150~1250에서는 기존 레이아웃 유지
let resizeTimer = null;
let relayoutTimer = null;

// 페이지 로드 시 초기화
document.addEventListener('DOMContentLoaded', function() {
    // URL 파라미터 파싱
    const params = new URLSearchParams(window.location.search);
    if (params.get('category_index')) {
        categoryIndex = parseInt(params.get('category_index'));
        // 카테고리 선택 상태를 쿠키에 저장
        setCookie('selectedCategory', categoryIndex.toString(), 24);
    } else {
        // URL에 카테고리 파라미터가 없으면 쿠키에서 복원
        const savedCategory = getCookie('selectedCategory');
        if (savedCategory) {
            categoryIndex = parseInt(savedCategory);
        }
    }
    
    if (params.get('search_string')) {
        searchString = decodeURIComponent(params.get('search_string'));
    }
    if (params.get('page_index')) {
        pageIndex = parseInt(params.get('page_index'));
    }

    // 초기화 함수들
    verifyLogin();
    initProfile();
    initCategoryList();
    initSearchEnhancements();
    
    // 세션 모니터링 시작
    startSessionMonitoring();
    
    // 현재 페이지에 따라 다른 초기화
    const currentPath = window.location.pathname;
    if (currentPath === '/index.php' || currentPath === '/' || currentPath === '/blog') {
        initPostingList();
        // 초기 게시글 배치
        setPostingList(true);
        attachPostImageHandlers();
        observePostings();
    } else if (currentPath === '/reader.php') {
        initPostingDetail();
    }
});

function scheduleRelayout(delay = 120) {
    if (relayoutTimer) cancelAnimationFrame(relayoutTimer);
    relayoutTimer = requestAnimationFrame(() => {
        setTimeout(() => setPostingList(false), delay);
    });
}

function attachPostImageHandlers() {
    const images = document.querySelectorAll('#postings img.posting_thumbnail');
    images.forEach(img => {
        if (img.dataset._relayoutAttached === '1') return;
        img.dataset._relayoutAttached = '1';
        if (!img.complete) {
            img.addEventListener('load', () => scheduleRelayout(50));
            img.addEventListener('error', () => scheduleRelayout(50));
        }
    });
}

function observePostings() {
    const root = document.getElementById('postings');
    if (!root) return;
    const observer = new MutationObserver(() => {
        attachPostImageHandlers();
        scheduleRelayout(80);
    });
    observer.observe(root, { childList: true, subtree: true });
}

// 로그인 상태 확인
function verifyLogin() {
    fetch('/get/login_verify', {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(response => response.json())
        .then(data => {
            userInfo = data;
            updateLoginStatus();

            // 정상 로그인 상태라면 이전 만료 알림 표시 상태를 초기화
            if (!data.session_expired && data && data.state === 0) {
                clearSessionExpiredAlertShown();
            }
            
            // 세션이 만료된 경우 알림 표시
            if (data.session_expired) {
                showSessionExpiredAlert();
            }
        })
        .catch(error => {
            console.error('로그인 상태 확인 실패:', error);
        });
}

// 로그인 상태 UI 업데이트
function updateLoginStatus() {
    const topRight = document.getElementById('topRight');
    const topWrite = document.getElementById('topWrite');
    
    if (topRight) {
        topRight.textContent = userInfo && userInfo.state === 0 ? '로그아웃' : '로그인';
    }
    
    if (topWrite) {
        const buttonRole = topWrite.dataset.buttonRole || 'blog-write';

        if (!(userInfo && userInfo.state === 0)) {
            topWrite.style.display = 'none';
            return;
        }

        if (buttonRole === 'stock-admin') {
            topWrite.textContent = '관리자';
            topWrite.style.display = 'block';
            return;
        }

        if (userInfo.can_write === 1) {
            topWrite.textContent = '글쓰기';
            topWrite.style.display = 'block';
            return;
        }

        topWrite.style.display = 'none';
    }
}

// 프로필 초기화
function initProfile() {
    // 프로필 정보는 서버에서 렌더링되므로 여기서는 추가 작업 없음
}

// 카테고리 목록 초기화
function initCategoryList() {
    // 카테고리 목록은 서버에서 렌더링되므로 여기서는 추가 작업 없음
}

// 게시글 목록 초기화
function initPostingList() {
    // 게시글 목록은 서버에서 렌더링되므로 여기서는 추가 작업 없음
}

// 게시글 상세 초기화
function initPostingDetail() {
    // 검색 카테고리 선택 상태 복원
    const searchCategorySelect = document.getElementById('search_category_list');
    if (searchCategorySelect && categoryIndex > 0) {
        searchCategorySelect.value = categoryIndex.toString();
    }
}

// 로그인/로그아웃 클릭
function loginoutClick() {
    if (userInfo && userInfo.state === 0) {
        if (confirm('로그아웃하시겠습니까?')) {
            var form = document.getElementById('logout-form');
            if (form) {
                var returnUrl = location.pathname + location.search;
                var input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'return_url';
                input.value = returnUrl;
                form.appendChild(input);
                form.submit();
            }
            else { location.href = '/blog'; }
        }
    } else {
        var returnUrl = location.pathname + location.search;
        location.href = '/login.php?return=' + encodeURIComponent(returnUrl);
    }
}

// 글쓰기 클릭
function writePostingClick() {
    if (userInfo && userInfo.state === 0 && userInfo.can_write === 1) {
        location.href = `/writer.php${categoryIndex > 0 ? '?category_index=' + categoryIndex : ''}`;
    } else {
        alert('글쓰기 권한이 없습니다.');
    }
}

// 카테고리 선택 함수
function selectCategory(categoryId) {
    categoryIndex = categoryId;
    // 카테고리 선택 상태를 쿠키에 저장
    setCookie('selectedCategory', categoryIndex.toString(), 24);
    // 해당 카테고리로 이동
    location.href = `/blog${categoryId > 0 ? '?category_index=' + categoryId : ''}`;
}

// 검색 기능 향상 초기화
function initSearchEnhancements() {
    const searchText = document.getElementById('search_posting_text');
    const searchBtn = document.getElementById('search_posting_btn');
    
    if (!searchText) return;
    
    // 키보드 단축키 지원 (Ctrl+S 또는 Cmd+S)
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            searchText.focus();
            searchText.select();
        }
    });
    
    // 검색어 입력 시 실시간 힌트 표시
    searchText.addEventListener('input', function() {
        const value = this.value.trim();
        if (value.length > 0) {
            this.style.borderColor = '#4CAF50';
        } else {
            this.style.borderColor = '';
        }
    });
    
    // 검색 버튼에 툴팁 추가
    if (searchBtn) {
        searchBtn.title = '검색 (Enter 또는 Ctrl+S)';
    }
    
    // 검색 입력창에 툴팁 추가
    searchText.title = '게시글 제목으로 검색 (Ctrl+S로 포커스)';
}

// 게시글 검색
function searchPostingClick() {
    const categorySelect = document.getElementById('search_category_list');
    const searchText = document.getElementById('search_posting_text');
    const searchBtn = document.getElementById('search_posting_btn');
    const searchInputGroup = document.querySelector('.search-input-group');
    
    if (!categorySelect || !searchText) return;
    
    // 검색 중 애니메이션 효과
    if (searchInputGroup) {
        searchInputGroup.classList.add('searching');
        searchBtn.style.transform = 'scale(0.95)';
    }
    
    const selectedCategory = categorySelect.value;
    const searchValue = searchText.value.trim();
    
    // 선택된 카테고리를 전역 변수와 쿠키에 저장
    categoryIndex = parseInt(selectedCategory);
    setCookie('selectedCategory', categoryIndex.toString(), 24);
    
    // 검색어가 없으면 전체 목록으로 이동
    if (!searchValue && selectedCategory === '-1') {
        location.href = '/blog';
        return;
    }
    
    let url = '/blog?';
    if (selectedCategory !== '-1') {
        url += 'category_index=' + selectedCategory + '&';
    }
    if (searchValue) {
        url += 'search_string=' + encodeURIComponent(searchValue);
    }
    
    // 약간의 지연 후 페이지 이동 (애니메이션 효과를 위해)
    setTimeout(() => {
        location.href = url;
    }, 200);
}

// 게시글 삭제
function deletePost(postId) {
    if (confirm('정말로 이 게시글을 삭제하시겠습니까?')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/post/delete/${postId}`;
        
        // CSRF 토큰 추가
        const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
        if (csrfToken) {
            const tokenInput = document.createElement('input');
            tokenInput.type = 'hidden';
            tokenInput.name = 'csrf_token';
            tokenInput.value = csrfToken;
            form.appendChild(tokenInput);
        }
        
        document.body.appendChild(form);
        form.submit();
    }
}

// 페이지 리사이즈 처리(디바운스)
window.addEventListener('resize', function() {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => scheduleRelayout(0), 150);
});

// 게시글 목록 설정 (히스테리시스 적용)
function shouldUseTwoCols(currentWidth, currentState) {
    // 현재 2열이면 1550px 이하로 줄어들 때만 1열로 변경
    if (currentState === 2) return currentWidth >= (BREAKPOINT - HYSTERESIS);
    // 현재 1열이면 1650px 이상 넓어질 때만 2열로 변경
    if (currentState === 1) return currentWidth >= (BREAKPOINT + HYSTERESIS);
    // 초기 상태: 단순 기준으로 결정
    return currentWidth >= BREAKPOINT;
}

function setPostingList(isInitial = false) {
    const left = document.getElementById('left');
    const right = document.getElementById('right');
    const temp = document.getElementById('temp');
    const postingsRoot = document.getElementById('postings');
    if (!left || !right || !postingsRoot) return;

    const allPosts = Array.from(postingsRoot.querySelectorAll('.posting, .posting_ban'));
    if (allPosts.length === 0) return;

    const width = document.body.offsetWidth;
    const wantTwoCols = shouldUseTwoCols(width, showState);

    if (!wantTwoCols) {
        if (showState !== 1 || isInitial) {
            showState = 1;
            if (temp) temp.style.height = 0;
            left.style.width = '100%';
            right.style.width = '0%';
            // 모든 포스팅을 왼쪽 단일 열로 이동
            allPosts.forEach(post => left.appendChild(post));
        }
        return;
    }

    // 2열 배치
    if (showState !== 2 || isInitial) {
        showState = 2;
        if (temp) temp.style.height = 0;
        left.style.width = '50%';
        right.style.width = '50%';

        // 먼저 두 컬럼 비우기
        while (left.firstChild) left.removeChild(left.firstChild);
        while (right.firstChild) right.removeChild(right.firstChild);

        // 높이가 더 낮은 쪽에 순서대로 배치
        allPosts.forEach(post => {
            const leftHeight = left.offsetHeight;
            const rightHeight = right.offsetHeight;
            if (leftHeight <= rightHeight) {
                left.appendChild(post);
            } else {
                right.appendChild(post);
            }
        });
    }
}

// 유틸리티 함수들
function setCookie(name, value, hours = 2) {
    const date = new Date();
    date.setTime(date.getTime() + hours * 3600000);
    document.cookie = `${name}=${value};expires=${date.toUTCString()};path=/`;
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
        const cookieValue = parts.pop().split(';').shift();
        setCookie(name, cookieValue, 2); // 쿠키 갱신
        return cookieValue;
    }
    return null;
}

function deleteCookie(name) {
    setCookie(name, '', -1);
}

function hasShownSessionExpiredAlert() {
    try {
        return window.sessionStorage.getItem(SESSION_EXPIRED_ALERT_SHOWN_KEY) === '1';
    } catch (error) {
        return false;
    }
}

function markSessionExpiredAlertShown() {
    try {
        window.sessionStorage.setItem(SESSION_EXPIRED_ALERT_SHOWN_KEY, '1');
    } catch (error) {}
}

function clearSessionExpiredAlertShown() {
    try {
        window.sessionStorage.removeItem(SESSION_EXPIRED_ALERT_SHOWN_KEY);
    } catch (error) {}
}

// AJAX 요청 헬퍼 함수
function makeRequest(url, options = {}) {
    const defaultOptions = {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
    };
    
    const finalOptions = { ...defaultOptions, ...options };
    
    return fetch(url, finalOptions)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        });
}

// 에러 처리
window.addEventListener('error', function(e) {
    console.error('JavaScript 에러:', e.error);
});

// 세션 만료 알림 표시
function showSessionExpiredAlert() {
    if (sessionExpiredAlertVisible || hasShownSessionExpiredAlert()) {
        return;
    }

    sessionExpiredAlertVisible = true;
    markSessionExpiredAlertShown();

    const hostContainer = document.getElementById('blog') || document.body;
    const alertDiv = document.createElement('div');
    alertDiv.style.cssText = `
        position: absolute;
        top: 20px;
        right: 20px;
        background: var(--alert-session-bg);
        color: var(--alert-session-text);
        padding: 15px 20px;
        border-radius: 5px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        z-index: 10000;
        font-family: Arial, sans-serif;
        font-size: 14px;
        max-width: 300px;
    `;
    alertDiv.innerHTML = `
        <div style="font-weight: bold; margin-bottom: 5px;">세션이 만료되었습니다</div>
        <div style="margin-bottom: 10px;">자동으로 로그아웃됩니다.</div>
        <button onclick="this.parentElement.remove()" style="
            background: var(--alert-session-btn-bg);
            border: 1px solid var(--alert-session-btn-border);
            color: var(--alert-session-text);
            padding: 5px 10px;
            border-radius: 3px;
            cursor: pointer;
        ">확인</button>
    `;
    
    hostContainer.appendChild(alertDiv);

    const removeAlert = () => {
        if (alertDiv.parentElement) {
            alertDiv.remove();
        }
        sessionExpiredAlertVisible = false;
    };

    const confirmButton = alertDiv.querySelector('button');
    if (confirmButton) {
        confirmButton.addEventListener('click', removeAlert);
    }
    
    // 5초 후 자동으로 제거
    setTimeout(() => {
        removeAlert();
    }, 5000);
}

// 주기적 세션 상태 확인 (5분마다)
let sessionCheckInterval = null;

function startSessionMonitoring() {
    // 이미 실행 중이면 중지
    if (sessionCheckInterval) {
        clearInterval(sessionCheckInterval);
    }
    
    // 5분마다 세션 상태 확인
    sessionCheckInterval = setInterval(() => {
        verifyLogin();
    }, 5 * 60 * 1000); // 5분
}

function stopSessionMonitoring() {
    if (sessionCheckInterval) {
        clearInterval(sessionCheckInterval);
        sessionCheckInterval = null;
    }
}

// 페이지 언로드 시 정리
window.addEventListener('beforeunload', function() {
    stopSessionMonitoring();
});
