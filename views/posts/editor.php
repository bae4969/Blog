<div id="post-writer" class="post-wrapper">
    <article class="post">
        <div class="post-content">
            <form id="post-form" method="POST" action="<?= $isEdit ? '/post/update/' . $post['posting_index'] : '/writer.php' ?>" class="post-form" novalidate>
                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                
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
                    <div id="quill-editor" class="quill-container"></div>
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
<script src="/vendor/quill/quill.min.js"></script>

<script>
// Quill 에디터 초기화
let quill;
let hasUnsavedChanges = false;
let initialContent = '';

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
                                // 파일 크기 제한 (5MB)
                                if (file.size > 5 * 1024 * 1024) {
                                    alert('이미지 크기는 5MB 이하여야 합니다.');
                                    return;
                                }

                                // 로딩 상태 표시
                                const range = quill.getSelection();
                                if (range) {
                                    quill.insertText(range.index, '이미지 처리 중...');
                                    quill.setSelection(range.index, range.index + 8);
                                }

                                // 이미지 압축 및 리사이즈
                                compressImage(file, function(compressedDataUrl) {
                                    // 로딩 텍스트 제거
                                    if (range) {
                                        quill.deleteText(range.index, 8);
                                        
                                        // 압축된 이미지 삽입
                                        quill.insertEmbed(range.index, 'image', compressedDataUrl);
                                        quill.setSelection(range.index + 1);
                                    }
                                });
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

    // 클립보드 붙여넣기 이벤트 처리
    quill.root.addEventListener('paste', function(e) {

        input.onchange = function() {
            const file = input.files[0];
            if (file) {
                // 파일 크기 제한 (5MB)
                if (file.size > 5 * 1024 * 1024) {
                    alert('이미지 크기는 5MB 이하여야 합니다.');
                    return;
                }

                // 로딩 상태 표시
                const range = quill.getSelection();
                if (range) {
                    quill.insertText(range.index, '이미지 처리 중...');
                    quill.setSelection(range.index, range.index + 8);
                }

                // 이미지 압축 및 리사이즈
                compressImage(file, function(compressedDataUrl) {
                    // 로딩 텍스트 제거
                    quill.deleteText(range.index, 8);
                    
                    // 압축된 이미지 삽입
                    quill.insertEmbed(range.index, 'image', compressedDataUrl);
                    quill.setSelection(range.index + 1);
                });
            }
        };
    });

    // 클립보드 붙여넣기 이벤트 처리
    quill.root.addEventListener('paste', function(e) {
        const clipboardItems = e.clipboardData.items;
        
        for (let i = 0; i < clipboardItems.length; i++) {
            const item = clipboardItems[i];
            
            // 이미지 파일인 경우
            if (item.type.indexOf('image') !== -1) {
                e.preventDefault(); // 기본 붙여넣기 방지
                
                const file = item.getAsFile();
                if (file) {
                    // 파일 크기 제한 (5MB)
                    if (file.size > 5 * 1024 * 1024) {
                        alert('이미지 크기는 5MB 이하여야 합니다.');
                        return;
                    }

                    // 로딩 상태 표시
                    const range = quill.getSelection();
                    if (range) {
                        quill.insertText(range.index, '이미지 처리 중...');
                        quill.setSelection(range.index, range.index + 8);
                    }

                    // 이미지 압축 및 리사이즈
                    compressImage(file, function(compressedDataUrl) {
                        // 로딩 텍스트 제거
                        if (range) {
                            quill.deleteText(range.index, 8);
                            
                            // 압축된 이미지 삽입
                            quill.insertEmbed(range.index, 'image', compressedDataUrl);
                            quill.setSelection(range.index + 1);
                        }
                    });
                }
                break; // 이미지 처리 후 루프 종료
            }
        }
    });

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
            
            // 이미지 파일인 경우
            if (file.type.indexOf('image') !== -1) {
                // 파일 크기 제한 (5MB)
                if (file.size > 5 * 1024 * 1024) {
                    alert('이미지 크기는 5MB 이하여야 합니다.');
                    continue;
                }

                // 로딩 상태 표시
                const range = quill.getSelection();
                if (range) {
                    quill.insertText(range.index, '이미지 처리 중...');
                    quill.setSelection(range.index, range.index + 8);
                }

                // 이미지 압축 및 리사이즈
                compressImage(file, function(compressedDataUrl) {
                    // 로딩 텍스트 제거
                    if (range) {
                        quill.deleteText(range.index, 8);
                        
                        // 압축된 이미지 삽입
                        quill.insertEmbed(range.index, 'image', compressedDataUrl);
                        quill.setSelection(range.index + 1);
                    }
                });
            }
        }
    });

    // Quill 내용 변경 시 hidden textarea 업데이트 및 변경 상태 추적
    quill.on('text-change', function() {
        convertDashesToDivider(); // 구분선 변환 추가
        document.getElementById('input_content').value = quill.root.innerHTML;
        validateContent();
        
        // 내용이 변경되었는지 확인
        const currentContent = quill.root.innerHTML;
        hasUnsavedChanges = (currentContent !== initialContent || 
                           document.getElementById('input_title').value.trim() !== '' ||
                           document.getElementById('input_category').value !== '-1');
    });

    // 제목과 카테고리 변경도 감지
    document.getElementById('input_title').addEventListener('input', function() {
        const currentContent = quill.root.innerHTML;
        hasUnsavedChanges = (currentContent !== initialContent || 
                           this.value.trim() !== '' ||
                           document.getElementById('input_category').value !== '-1');
    });
    
    document.getElementById('input_category').addEventListener('change', function() {
        const currentContent = quill.root.innerHTML;
        hasUnsavedChanges = (currentContent !== initialContent || 
                           document.getElementById('input_title').value.trim() !== '' ||
                           this.value !== '-1');
    });

    // 초기 유효성 검사
    validateTitle();
    validateCategory();
    validateContent();
    
    // 제목 아이콘 클릭 시 확인 메시지
    const mainTitle = document.getElementById('mainTitle');
    if (mainTitle) {
        mainTitle.addEventListener('click', function(e) {
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
                        // 원래 동작 실행
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
});

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

// 이미지 압축 함수
function compressImage(file, callback) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const img = new Image();
    
    img.onload = function() {
        // 최대 크기 설정 (1200px)
        const maxWidth = 1200;
        const maxHeight = 1200;
        
        let { width, height } = img;
        
        // 비율 유지하면서 리사이즈
        if (width > height) {
            if (width > maxWidth) {
                height = (height * maxWidth) / width;
                width = maxWidth;
            }
        } else {
            if (height > maxHeight) {
                width = (width * maxHeight) / height;
                height = maxHeight;
            }
        }
        
        canvas.width = width;
        canvas.height = height;
        
        // 이미지 그리기
        ctx.drawImage(img, 0, 0, width, height);
        
        // 압축된 이미지를 Data URL로 변환 (품질 80%)
        const compressedDataUrl = canvas.toDataURL('image/jpeg', 0.8);
        callback(compressedDataUrl);
    };
    
    img.src = URL.createObjectURL(file);
}

// 공통 함수들
function loginoutClick() {
    <?php if ($auth->isLoggedIn()): ?>
        if (confirm('로그아웃하시겠습니까?')) {
            location.href = '/logout.php';
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
    
    </style>
`;

// 다크 테마 스타일 추가
document.head.insertAdjacentHTML('beforeend', quillDarkTheme);
</script>
