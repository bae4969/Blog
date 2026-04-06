<div id="post-writer" class="post-wrapper">
    <article class="post">
        <div class="post-content">
            <form id="post-form" method="POST" action="<?= $isEdit ? '/post/update/' . $post['posting_index'] : '/writer.php' ?>" class="post-form" novalidate>
                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                <input type="hidden" id="input_thumbnail" name="thumbnail" value="<?= $isEdit ? htmlspecialchars($post['posting_thumbnail'] ?? '', ENT_QUOTES, 'UTF-8') : '' ?>">
                
                <div class="form-row">
                    <div class="form-group form-group-category">
                        <label for="input_category" class="form-label">카테고리</label>
                        <select id="input_category" name="category_index" required class="form-control">
                            <option value="-1">카테고리를 선택하세요</option>
                            <?php foreach ($categories as $category): ?>
                                <option value="<?= $category['category_index'] ?>" 
                                        <?= ($isEdit ? $post['category_index'] : $selectedCategory) == $category['category_index'] ? 'selected' : '' ?>>
                                    <?= $view->escape($category['category_name']) ?>
                                </option>
                            <?php endforeach; ?>
                        </select>
                    </div>
                    
                    <div class="form-group form-group-title">
                        <label for="input_title" class="form-label">제목</label>
                        <input id="input_title" name="title" type="text" placeholder="제목을 입력하세요 (최대 255자)" 
                               maxlength="255" required class="form-control" 
                               value="<?= $isEdit ? $view->escape($post['posting_title']) : '' ?>" />
                    </div>
                </div>

                <div class="form-group">
                    <label for="input_content" class="form-label">내용</label>
                    <div id="quill-wrapper" class="quill-wrapper">
                        <div id="quill-editor" class="quill-container"></div>
                        <div id="thumb-overlay" class="thumb-overlay"></div>
                    </div>
                    <textarea id="input_content" name="content" style="display: none;"><?= $isEdit ? $post['posting_content'] : '' ?></textarea>
                </div>
            </form>
        </div>
        
        <div class="form-actions">
            <button id="btn_submit" type="submit" form="post-form" class="btn btn-primary">
                <span class="btn-text"><?= $isEdit ? '수정' : '작성' ?></span>
                <span class="btn-loading" style="display: none;"><?= $isEdit ? '수정 중...' : '작성 중...' ?></span>
            </button>
            <button type="button" onclick="handleCancel()" class="btn btn-secondary">취소</button>
        </div>
        </div>
    </article>
</div>

<!-- Quill.js 로컬 파일 -->
<link href="/vendor/quill/quill.snow.css" rel="stylesheet">
<script nonce="<?= $view->getNonce() ?>" src="/vendor/quill/quill.min.js"></script>

<script nonce="<?= $view->getNonce() ?>">
// Quill 에디터 초기화
let quill;
let hasUnsavedChanges = false;
let initialContent = '';

function getCsrfToken() {
    return document.querySelector('input[name="csrf_token"]').value;
}

// 이미지를 클라이언트에서 리사이즈/압축 후 base64 data URI로 에디터에 삽입
const MAX_IMAGE_AREA = 1200 * 900; // 1,080,000 픽셀

function compressAndInsertImage(file) {
    if (!file.type.startsWith('image/')) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const img = new Image();
        img.onload = function() {
            let { width, height } = img;
            const area = width * height;

            // 면적 기준 초과 시 비율 유지하며 축소
            if (area > MAX_IMAGE_AREA) {
                const scale = Math.sqrt(MAX_IMAGE_AREA / area);
                width = Math.round(width * scale);
                height = Math.round(height * scale);
            }

            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, width, height);

            const dataUrl = canvas.toDataURL('image/jpeg', 0.8);

            const range = quill.getSelection(true);
            const idx = range ? range.index : quill.getLength() - 1;
            quill.insertEmbed(idx, 'image', dataUrl);
            quill.setSelection(idx + 1);
        };
        img.src = e.target.result;
    };
    reader.readAsDataURL(file);
}

document.addEventListener('DOMContentLoaded', function() {
    // 다크 테마에 맞는 Quill 설정
    quill = new Quill('#quill-editor', {
        theme: 'snow',
        placeholder: '내용을 입력하세요...',
        modules: {
            toolbar: {
                container: [
                    [{ 'header': [1, 2, 3, false] }],
                    ['bold', 'italic', 'underline', 'strike'],
                    [{ 'color': [] }, { 'background': [] }],
                    [{ 'list': 'ordered'}, { 'list': 'bullet' }],
                    ['link', 'image'],
                    ['blockquote', 'code-block'],
                    ['divider'],
                    ['clean']
                ],
                handlers: {
                    'divider': function() {
                        const range = quill.getSelection();
                        if (range) {
                            quill.insertText(range.index, '\n---\n');
                            quill.setSelection(range.index + 5);
                        }
                    },
                    'image': function() {
                        const input = document.createElement('input');
                        input.setAttribute('type', 'file');
                        input.setAttribute('accept', 'image/*');
                        input.click();

                        input.onchange = function() {
                            const file = input.files[0];
                            if (file) {
                                compressAndInsertImage(file);
                            }
                        };
                    }
                }
            }
        }
    });

    // 기존 내용이 있으면 에디터에 로드
    const existingContent = document.getElementById('input_content').value;
    if (existingContent) {
        quill.clipboard.dangerouslyPasteHTML(existingContent);
    }
    
    // 초기 내용 저장
    initialContent = quill.root.innerHTML;
    
    // --- 텍스트를 구분선으로 변환하는 함수
    function convertDashesToDivider() {
        const editor = quill.root;
        const paragraphs = editor.querySelectorAll('p');
        
        paragraphs.forEach(p => {
            if (p.textContent.trim() === '---') {
                p.innerHTML = '';
                p.style.cssText = `
                    margin: 20px 0;
                    height: 2px;
                    background: linear-gradient(to right, transparent, #36383A, transparent);
                    border: none;
                    padding: 0;
                    position: relative;
                `;
            }
        });
    }
    
    // 초기 로드 시에도 구분선 변환
    convertDashesToDivider();

    // 클립보드 붙여넣기 이벤트 처리 (capture phase로 Quill보다 먼저 실행)
    quill.root.addEventListener('paste', function(e) {
        const clipboardItems = e.clipboardData && e.clipboardData.items;
        if (!clipboardItems) return;
        
        for (let i = 0; i < clipboardItems.length; i++) {
            const item = clipboardItems[i];
            
            if (item.type.indexOf('image') !== -1) {
                e.preventDefault();
                e.stopImmediatePropagation();
                
                const file = item.getAsFile();
                if (file) {
                    compressAndInsertImage(file);
                }
                return;
            }
        }
    }, true);

    // 드래그 앤 드롭 이벤트 처리
    quill.root.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
    });

    quill.root.addEventListener('dragenter', function(e) {
        e.preventDefault();
        e.stopPropagation();
    });

    quill.root.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        
        const files = e.dataTransfer.files;
        
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            
            if (file.type.indexOf('image') !== -1) {
                compressAndInsertImage(file);
            }
        }
    });

    // Quill 내용 변경 시 hidden textarea 업데이트 및 변경 상태 추적
    quill.on('text-change', function() {
        convertDashesToDivider();
        document.getElementById('input_content').value = quill.root.innerHTML;
        validateContent();
        updateUnsavedState();
        
        // 이미지 변경 시 별 아이콘 오버레이 갱신
        scheduleOverlayUpdate();
    });

    // 제목과 카테고리 변경도 감지
    document.getElementById('input_title').addEventListener('input', updateUnsavedState);
    document.getElementById('input_category').addEventListener('change', updateUnsavedState);

    function updateUnsavedState() {
        const currentContent = quill.root.innerHTML;
        hasUnsavedChanges = (currentContent !== initialContent || 
                           document.getElementById('input_title').value.trim() !== '' ||
                           document.getElementById('input_category').value !== '-1');
    }

    // 초기 유효성 검사
    validateTitle();
    validateCategory();
    validateContent();
    
    // 제목 아이콘 클릭 시 확인 메시지
    const blogTitle = document.getElementById('blogTitle');
    if (blogTitle) {
        blogTitle.addEventListener('click', function(e) {
            if (hasUnsavedChanges) {
                e.preventDefault();
                if (confirm('작성 중인 내용이 있습니다. 정말 나가시겠습니까?')) {
                    hasUnsavedChanges = false;
                    location.href = '/blog';
                }
            }
        });
    }
    
    // 다른 링크들 클릭 시 확인 메시지
    const topLeft = document.getElementById('topLeft');
    const topRight = document.getElementById('topRight');
    const topWrite = document.getElementById('topWrite');
    
    [topLeft, topRight, topWrite].forEach(element => {
        if (element) {
            element.addEventListener('click', function(e) {
                if (hasUnsavedChanges) {
                    e.preventDefault();
                    if (confirm('작성 중인 내용이 있습니다. 정말 나가시겠습니까?')) {
                        hasUnsavedChanges = false;
                        if (element === topLeft) {
                            location.href = '/blog';
                        } else if (element === topRight) {
                            loginoutClick();
                        } else if (element === topWrite) {
                            writePostingClick();
                        }
                    }
                }
            });
        }
    });

    // === 썸네일 별 아이콘 기능 (오버레이 방식) ===
    initThumbnailOverlay();

    // 기존 썸네일이 있는 수정 모드: 첫 이미지를 선택 상태로 표시
    const existingThumbnail = document.getElementById('input_thumbnail').value;
    if (existingThumbnail) {
        const firstImg = document.querySelector('#quill-editor .ql-editor img');
        if (firstImg) {
            selectedThumbnailSrc = firstImg.src;
        }
        updateStarOverlay();
    } else {
        autoSelectFirstImage();
    }
});

// === 썸네일 오버레이 함수들 ===

let selectedThumbnailSrc = '';
let overlayUpdateTimer = null;

function initThumbnailOverlay() {
    // Quill 에디터 스크롤 및 리사이즈 시 별 위치 갱신
    const qlEditor = document.querySelector('#quill-editor .ql-editor');
    if (qlEditor) {
        qlEditor.addEventListener('scroll', function() {
            updateStarOverlay();
        });
    }
    window.addEventListener('resize', function() {
        updateStarOverlay();
    });
}

function scheduleOverlayUpdate() {
    if (overlayUpdateTimer) clearTimeout(overlayUpdateTimer);
    overlayUpdateTimer = setTimeout(function() {
        updateStarOverlay();
    }, 100);
}

function updateStarOverlay() {
    const overlay = document.getElementById('thumb-overlay');
    const qlEditor = document.querySelector('#quill-editor .ql-editor');
    const wrapper = document.getElementById('quill-wrapper');
    if (!overlay || !qlEditor || !wrapper) return;

    // 기존 별 제거
    overlay.innerHTML = '';

    const images = qlEditor.querySelectorAll('img');
    if (images.length === 0) {
        // 이미지 없으면 썸네일도 초기화
        if (selectedThumbnailSrc) {
            selectedThumbnailSrc = '';
            document.getElementById('input_thumbnail').value = '';
        }
        return;
    }

    const wrapperRect = wrapper.getBoundingClientRect();
    const editorRect = qlEditor.getBoundingClientRect();
    // 툴바 높이만큼 오프셋 (wrapper 기준)
    const toolbarHeight = editorRect.top - wrapperRect.top;

    images.forEach(function(img, idx) {
        const imgRect = img.getBoundingClientRect();
        
        // 에디터 뷰포트 밖이면 스킵
        if (imgRect.bottom < editorRect.top || imgRect.top > editorRect.bottom) return;

        const star = document.createElement('button');
        star.type = 'button';
        star.className = 'img-thumb-star';
        if (selectedThumbnailSrc && img.src === selectedThumbnailSrc) {
            star.classList.add('active');
        }
        star.innerHTML = '&#9733;';
        star.title = '썸네일로 선택';

        // wrapper에 상대적인 위치 계산
        star.style.top = (imgRect.top - wrapperRect.top + 6) + 'px';
        star.style.left = (imgRect.right - wrapperRect.left - 34) + 'px';

        star.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            selectAsThumbnail(img);
        });

        overlay.appendChild(star);
    });

    // 선택된 이미지가 삭제된 경우
    if (selectedThumbnailSrc) {
        let found = false;
        images.forEach(function(img) {
            if (img.src === selectedThumbnailSrc) found = true;
        });
        if (!found) {
            selectedThumbnailSrc = '';
            document.getElementById('input_thumbnail').value = '';
            autoSelectFirstImage();
        }
    }
}

function selectAsThumbnail(img) {
    // 같은 이미지를 다시 클릭하면 선택 해제 → 첫 이미지 자동 선택
    if (selectedThumbnailSrc === img.src) {
        selectedThumbnailSrc = '';
        document.getElementById('input_thumbnail').value = '';
        autoSelectFirstImage();
        return;
    }

    selectedThumbnailSrc = img.src;
    generateThumbnailFromUrl(img.src);
    updateStarOverlay();
}

function autoSelectFirstImage() {
    const firstImg = document.querySelector('#quill-editor .ql-editor img');
    if (firstImg && !selectedThumbnailSrc) {
        selectedThumbnailSrc = firstImg.src;
        generateThumbnailFromUrl(firstImg.src);
        updateStarOverlay();
    }
}

// URL에서 썸네일 생성
function generateThumbnailFromUrl(url) {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = function() {
        const base64 = resizeToThumbnail(img);
        document.getElementById('input_thumbnail').value = base64;
    };
    img.onerror = function() {
        // 로드 실패 시 무시
    };
    img.src = url;
}

// canvas로 리사이즈하여 webp base64 반환
function resizeToThumbnail(img) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const maxSize = 300;

    let { width, height } = img;
    if (width > height) {
        if (width > maxSize) { height = (height * maxSize) / width; width = maxSize; }
    } else {
        if (height > maxSize) { width = (width * maxSize) / height; height = maxSize; }
    }

    canvas.width = width;
    canvas.height = height;
    ctx.drawImage(img, 0, 0, width, height);

    const dataUrl = canvas.toDataURL('image/webp', 0.7);
    return dataUrl.replace(/^data:image\/webp;base64,/, '');
}

// 이미지 압축 함수 (기존 호환용)
function compressImage(file, callback) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const img = new Image();
    
    img.onload = function() {
        const maxWidth = 1200;
        const maxHeight = 1200;
        
        let { width, height } = img;
        
        if (width > height) {
            if (width > maxWidth) { height = (height * maxWidth) / width; width = maxWidth; }
        } else {
            if (height > maxHeight) { width = (width * maxHeight) / height; height = maxHeight; }
        }
        
        canvas.width = width;
        canvas.height = height;
        ctx.drawImage(img, 0, 0, width, height);
        
        const compressedDataUrl = canvas.toDataURL('image/jpeg', 0.8);
        callback(compressedDataUrl);
    };
    
    img.src = URL.createObjectURL(file);
}

// 페이지 이탈 시 확인 메시지 (브라우저 뒤로가기, 새로고침, 탭 닫기 등)
window.addEventListener('beforeunload', function(e) {
    if (hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = ''; // 최신 브라우저에서는 빈 문자열만 설정하면 됨
        return '';
    }
});

// 폼 제출 이벤트 처리
document.querySelector('.post-form').addEventListener('submit', function(e) {
    e.preventDefault();
    hasUnsavedChanges = false; // 제출 시 변경 상태 초기화
    handleFormSubmit();
});

// 실시간 유효성 검사
document.getElementById('input_title').addEventListener('input', validateTitle);
document.getElementById('input_category').addEventListener('change', validateCategory);

// 제목 유효성 검사
function validateTitle() {
    const titleInput = document.getElementById('input_title');
    const title = titleInput.value.trim();
    
    if (title.length === 0) {
        showFieldError(titleInput, '제목을 입력해주세요.');
        return false;
    } else if (title.length > 255) {
        showFieldError(titleInput, '제목은 255자를 초과할 수 없습니다.');
        return false;
    } else {
        clearFieldError(titleInput);
        return true;
    }
}

// 카테고리 유효성 검사
function validateCategory() {
    const categorySelect = document.getElementById('input_category');
    const category = categorySelect.value;
    
    if (category === '-1') {
        showFieldError(categorySelect, '카테고리를 선택해주세요.');
        return false;
    } else {
        clearFieldError(categorySelect);
        return true;
    }
}

// 내용 유효성 검사 (Quill 에디터용)
function validateContent() {
    const contentTextarea = document.getElementById('input_content');
    const content = contentTextarea.value.trim();
    
    // Quill 에디터의 실제 텍스트 내용 확인
    const textContent = quill ? quill.getText().trim() : '';
    
    if (textContent.length === 0) {
        showFieldError(document.querySelector('.quill-container'), '내용을 입력해주세요.');
        return false;
    } else if (textContent.length < 10) {
        showFieldError(document.querySelector('.quill-container'), '내용은 최소 10자 이상 입력해주세요.');
        return false;
    } else {
        clearFieldError(document.querySelector('.quill-container'));
        return true;
    }
}

// 필드 에러 표시
function showFieldError(field, message) {
    clearFieldError(field);
    field.classList.add('error');
    
    const errorDiv = document.createElement('div');
    errorDiv.className = 'field-error';
    errorDiv.textContent = message;
    
    field.parentNode.appendChild(errorDiv);
}

// 필드 에러 제거
function clearFieldError(field) {
    field.classList.remove('error');
    const existingError = field.parentNode.querySelector('.field-error');
    if (existingError) {
        existingError.remove();
    }
}

// 취소 버튼 처리
function handleCancel() {
    if (hasUnsavedChanges) {
        if (confirm('작성 중인 내용이 있습니다. 정말 나가시겠습니까?')) {
            hasUnsavedChanges = false; // 확인 시 변경 상태 초기화
            <?php if ($isEdit): ?>
                location.href = '/reader.php?posting_index=<?= $post['posting_index'] ?>';
            <?php else: ?>
                location.href = '/blog';
            <?php endif; ?>
        }
    } else {
        <?php if ($isEdit): ?>
            location.href = '/reader.php?posting_index=<?= $post['posting_index'] ?>';
        <?php else: ?>
            location.href = '/blog';
        <?php endif; ?>
    }
}

// 폼 제출 처리
function handleFormSubmit() {
    const isTitleValid = validateTitle();
    const isCategoryValid = validateCategory();
    const isContentValid = validateContent();
    
    if (!isTitleValid || !isCategoryValid || !isContentValid) {
        showNotification('입력 정보를 확인해주세요.', 'error');
        return;
    }
    
    // 로딩 상태 표시
    const submitBtn = document.getElementById('btn_submit');
    const btnText = submitBtn.querySelector('.btn-text');
    const btnLoading = submitBtn.querySelector('.btn-loading');
    
    btnText.style.display = 'none';
    btnLoading.style.display = 'inline';
    submitBtn.disabled = true;
    
    // 폼 제출
    document.querySelector('.post-form').submit();
}

// 알림 표시
function showNotification(message, type = 'info') {
    // 기존 알림 제거
    const existingNotification = document.querySelector('.notification');
    if (existingNotification) {
        existingNotification.remove();
    }
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // 3초 후 자동 제거
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// 공통 함수들
function loginoutClick() {
    <?php if ($auth->isLoggedIn()): ?>
        if (confirm('로그아웃하시겠습니까?')) {
            document.getElementById('logout-form').submit();
        }
    <?php else: ?>
        location.href = '/login.php';
    <?php endif; ?>
}

function writePostingClick() {
    location.href = '/writer.php<?= ($isEdit ? '?category_index=' . $post['category_index'] : ($selectedCategory ? '?category_index=' . $selectedCategory : '')) ?>';
}

// Quill 에디터 다크 테마 스타일링
const quillDarkTheme = `
    <style>
    .ql-toolbar {
        background-color: #222426 !important;
        border-color: #36383A !important;
        color: #C3C3C3 !important;
    }
    
    .ql-toolbar .ql-stroke {
        stroke: #C3C3C3 !important;
    }
    
    .ql-toolbar .ql-fill {
        fill: #C3C3C3 !important;
    }
    
    .ql-toolbar button:hover {
        background-color: #36383A !important;
    }
    
    .ql-toolbar button.ql-active {
        background-color: #36383A !important;
        color: white !important;
    }
    
    .ql-container {
        background-color: #1A1C1D !important;
        color: #C3C3C3 !important;
        border-color: #36383A !important;
    }
    
    .ql-editor {
        background-color: #1A1C1D !important;
        color: #C3C3C3 !important;
        min-height: 300px !important;
    }
    
    .ql-editor.ql-blank::before {
        color: #666 !important;
    }
    
    .quill-container {
        border-radius: 8px;
        overflow: hidden;
    }
    
    .quill-container.error {
        border: 2px solid #dc3545;
    }
    
    .field-error {
        color: #dc3545;
        font-size: 0.875rem;
        margin-top: 5px;
    }
    
    /* 구분선 스타일 */
    .ql-editor hr {
        border: none;
        border-top: 2px solid #36383A;
        margin: 20px 0;
        background: none;
    }
    
    .ql-editor hr::before {
        content: '';
        display: block;
        height: 1px;
        background: linear-gradient(to right, transparent, #36383A, transparent);
        margin-top: 1px;
    }
    
    /* 구분선 버튼 아이콘 */
    .ql-toolbar .ql-divider::before {
        content: '';
        display: inline-block;
        width: 18px;
        height: 18px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23C3C3C3' stroke-width='2'%3E%3Cline x1='3' y1='12' x2='21' y2='12'%3E%3C/line%3E%3C/svg%3E");
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
    }
    
    /* --- 텍스트를 구분선으로 변환 */
    .ql-editor p {
        margin: 0;
    }
    
    /* --- 만 포함된 단락을 구분선으로 변환 */
    .ql-editor p:empty {
        margin: 20px 0;
        height: 2px;
        background: linear-gradient(to right, transparent, #36383A, transparent);
        border: none;
        padding: 0;
    }
    
    /* --- 텍스트가 있는 단락을 구분선으로 변환 */
    .ql-editor p:contains("---") {
        text-align: center;
        margin: 20px 0;
        font-size: 0;
        line-height: 0;
        height: 0;
        padding: 0;
        position: relative;
    }
    
    .ql-editor p:contains("---")::before {
        content: '';
        display: block;
        width: 100%;
        height: 2px;
        background: linear-gradient(to right, transparent, #36383A, transparent);
        position: absolute;
        top: 50%;
        left: 0;
        transform: translateY(-50%);
    }

    /* 썸네일 오버레이 */
    .quill-wrapper {
        position: relative;
    }
    
    .thumb-overlay {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 5;
    }
    
    .thumb-overlay .img-thumb-star {
        position: absolute;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        background: rgba(0, 0, 0, 0.55);
        border: none;
        color: var(--text-muted, #888);
        font-size: 18px;
        line-height: 28px;
        text-align: center;
        cursor: pointer;
        padding: 0;
        opacity: 0;
        transition: opacity 0.2s;
        pointer-events: auto;
    }
    
    .thumb-overlay .img-thumb-star:hover {
        opacity: 1 !important;
    }
    
    .thumb-overlay .img-thumb-star.active {
        color: var(--warning-color, #ffc107);
        opacity: 1;
    }
    
    #quill-wrapper:hover .thumb-overlay .img-thumb-star {
        opacity: 0.7;
    }
    
    #quill-wrapper:hover .thumb-overlay .img-thumb-star.active {
        opacity: 1;
    }
    
    </style>
`;

// 다크 테마 스타일 추가
document.head.insertAdjacentHTML('beforeend', quillDarkTheme);
</script>
