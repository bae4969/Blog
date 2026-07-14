# 로그 인프라

## 로그 테이블
- `Log.blog_log` — 블로그 앱 로그 (접근·인증·감사 등)
- `Log.stock_ticker_log` — ticker WebSocket 수집 로그

로그 관련 질문 시 **두 테이블 모두** 확인한다.

## 쿼리 방법
호스트에 mysql/php 없음. 컨테이너 경유:
```
sudo docker exec php-blog php -r "..."
```
prod: `php-blog`, test: `php-blog-test`

## 알려진 정상 패턴
- **매일 16:01** `WebSocketConnectionClosedException` — 장 마감 후 한투 서버가 연결 끊는 정상 동작
- **매일 새벽 4시** `WebSocketTimeoutException` (ping/pong timed out) — 공유기 정기 재부팅으로 인한 것, 이상 없음
