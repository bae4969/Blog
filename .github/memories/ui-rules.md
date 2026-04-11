# UI 규칙

- 이모지(emoji) 절대 사용 금지 — 항상 인라인 SVG 벡터 아이콘 사용
- 일반 브라우저 툴팁(title 속성) 절대 사용 금지 — 커스텀 툴팁만 사용
- 툴팁 구현 방식:
  - 기본: `data-xxx` 속성 + CSS `::after` pseudo-element (`bmk-val` 패턴)
  - overflow 컨테이너 내부: JS floating tooltip — `body`에 `position: fixed` div 동적 생성 (`preset-float-tooltip` 패턴)
  - ⓘ 설명용: `.metric-info` + `.metric-tooltip` (hover/focus로 표시)
  - `overflow: hidden/auto` 안에서는 CSS `::after`가 잘리므로 반드시 JS floating 방식 사용
- CSS 색상/변수: `public/css/common.css`의 `:root`에서 일괄 정의
