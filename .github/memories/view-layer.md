# 뷰 레이어 규칙

## 디렉토리 구조
```
views/
  home/     — 공통 요소 + 로그인 (layout, header, footer, partials-*)
  blog/     — 블로그 (layout, index, show, editor)
  admin/    — 관리자 (layout, users, categories, cache, stocks, wol, ip-blocks)
  stock/    — 주식 (layout, index, show, backtest)
```

## 레이아웃 규칙
- 섹션별 분리 — 각 섹션 폴더에 `layout.php` 존재
- `renderLayout($layout, $view)` — `$layout`은 뷰 폴더명 (`'blog'`, `'admin'`, `'stock'`, `'home'`)
- 뷰 내 자동 주입 변수: `$session`, `$auth`, `$config`, `$view`

## Partial 규칙
- 공통 partial: `views/home/partials-{이름}.php` 명명 규칙
- 새 partial 추가 시: `views/home/partials-{이름}.php`로 생성
- 새 섹션 추가 시: `views/{섹션}/layout.php` 생성 + `View::renderLayout()`에서 자동 해석

## CSS 규칙
- 색상/변수: `public/css/common.css`의 `:root`에서 일괄 정의
- 섹션별 색상 오버라이드: `common.css` 내 CSS 스코프로 처리
- 로드 순서: `common.css` → `blog.css` → 섹션별 CSS (`stocks.css`, `admin.css` 등)
- 캐시 버스팅: `?v={filemtime}` 패턴
- 에디터: Quill (`public/vendor/quill/` 로컬 파일)
