# Docker 환경

## db_bridge 네트워크 (172.16.9.0/24)

| 컨테이너 | IP | 포트 | 역할 |
|---|---|---|---|
| `php-blog-test` | 172.16.9.2 | 49001 | **현재 작업 디렉토리** (`21.blog`) — test 환경 |
| `mariadb` | 172.16.9.3 | — | MariaDB 12.1.2 (공유 DB) |
| `php-blog` | 172.16.9.4 | 49000 | prod 환경 (`20.blog` 마운트) |
| `stockticker` | 172.16.9.5 | — | Python ticker 수집기 (`10.StockTicker` 마운트) |

## php-blog-test (현재 작업 컨테이너)

- 이미지: `php-blog:latest` / PHP 8.2.30 + Apache
- 마운트: `/mnt/nvme/10.project/21.blog` → `/var/www/html` (바인드 마운트, 코드 즉시 반영)
- 환경변수: `APP_ENV=production`, `PHP_MEMORY_LIMIT=512M`, `PHP_POST_MAX_SIZE=40M`, `PHP_UPLOAD_MAX_FILESIZE=20M`
- 외부 포트: 49001 (nginx-proxy-manager가 프록시)
- TrueNAS Apps 프로젝트명: `ix-php-blog-test`

## mariadb

- 이미지: `mariadb:12.1.2`
- IP: 172.16.9.3 (컨테이너 내부에서 호스트명 `mariadb`로 접근)
- DB 접속 정보: host=`mariadb`, user=`service_bot`, password=`QAZplm4969`
- 주요 DB 스키마 전체:

| DB | 용도 |
|---|---|
| `Blog` | 앱 데이터 (게시글, 사용자, 카테고리 등) |
| `Log` | 로그 (`blog_log`, `stock_ticker_log`) |
| `KoreaInvest` | 한투 API 관련 데이터 (구독 종목 등) |
| `Bithumb` | 빗썸 코인 정보 (`coin_info`, `coin_last_ws_query`) |
| `candle` | 주식·코인 캔들(OHLCV) 데이터 |
| `tick` | 주식·코인 틱 데이터 |
| `Lab` | 실험/임시 데이터 |
| `Backup` | 백업 데이터 |
- 마운트: `/mnt/nvme/90.service/mariadb_data/data` → `/var/lib/mysql`, `/mnt/hdd/90.service/mariadb_backup` → `/backup`

## 코드/쿼리 실행 규칙

**호스트에는 php·mysql 바이너리가 없다.** 코드를 실행하거나 DB를 조회할 때는 반드시 Docker 컨테이너 내부에서 처리한다.

```bash
# PHP 실행
sudo docker exec php-blog-test php -r "..."

# DB 쿼리 (PHP 경유)
sudo docker exec php-blog-test php -r "
\$pdo = new PDO('mysql:host=mariadb;dbname=Log;charset=utf8mb4', 'service_bot', 'QAZplm4969');
// ...
"
```

- 로그 확인은 `php-blog-test`에서 해도 prod(`php-blog`)와 같은 DB를 바라보므로 동일
- prod 코드 확인이 필요하면 `php-blog`를 사용

## 운영 방식
- TrueNAS Apps(`ix-apps`)로 관리 — docker-compose 파일: `/mnt/.ix-apps/app_configs/php-blog-test/versions/1.0.0/templates/rendered/docker-compose.yaml`
- 외부 트래픽: nginx-proxy-manager(`ix-nginx-proxy-manager-npm-1`)가 각 포트로 프록시
