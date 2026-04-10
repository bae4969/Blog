<div id="inputLayout">
    <img id="blogTitle" onclick="location.href='/blog'" src="/res/title.png" alt="Blog Page" style="display: block; margin: 0 auto 30px; cursor: pointer;" />
	
    <form method="POST" action="/login.php" class="login-form" autocomplete="on">
        <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
        
        <!-- Honeypot: 봇 감지용 숨김 필드 (사람은 입력하지 않음) -->
        <div style="position:absolute;left:-9999px;top:-9999px;" aria-hidden="true">
            <input type="text" name="website_url" value="" tabindex="-1" autocomplete="off">
        </div>

        <div class="input">
            <input id="text_id" name="user_id" type="text" placeholder="ID" required
                   inputmode="text" autocomplete="username"
                   onkeyup="if(window.event.keyCode==13){loginClick()}" />
        </div>

        <div class="input">
            <input id="text_pw" type="password" placeholder="PW" required
                   autocomplete="current-password"
                   onkeyup="if(window.event.keyCode==13){loginClick()}" />
            <input type="hidden" id="hashed_pw" name="user_pw" value="" />
        </div>

        <div class="input">
            <button id="btn_login" class="btn btn-primary" type="submit">Login</button>
        </div>
    </form>
</div>

<script nonce="<?= $view->getNonce() ?>" src="/js/sha256.js"></script>
<script nonce="<?= $view->getNonce() ?>">
const formEl = document.querySelector('.login-form');
formEl.addEventListener('submit', function(e) {
    e.preventDefault();
    loginClick();
});

function loginClick() {
    const userId = document.getElementById("text_id").value.trim();
    const password = document.getElementById("text_pw").value;
    
    if (!userId || !password) {
        alert('아이디와 비밀번호를 모두 입력해주세요.');
        return;
    }
    
    // 비밀번호 해시화
    const hashedPassword = sha256(password);
    document.getElementById("hashed_pw").value = hashedPassword;
    
    // 폼 제출
    formEl.submit();
}
</script>
