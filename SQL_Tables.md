# StockTicker 데이터베이스 및 테이블 구조

이 문서는 `StockTicker` 프로젝트에서 사용하는 MariaDB 내의 데이터베이스와 각각의 핵심 테이블들, 그리고 컬럼(Column) 구조를 정리한 문서입니다. `ApiBithumb.py`, `ApiKoreaInvest.py`, 그리고 `Util.py` 내부의 SQL 테이블 생성 쿼리를 기반으로 작성되었습니다.

---

## 1. 메인 데이터베이스

### 1-1. `Bithumb` DB
빗썸 가상화폐 거래소의 종목 기본 메타 정보 및 WebSocket 쿼리 상태 정보를 저장합니다.

#### 🗂️ 테이블: `coin_info`
전체 가상화폐 종목의 개요, 이름, 현재가, 거래 대금을 저장합니다.
| Column Name | Data Type | Constraint & Default | Description |
| :--- | :--- | :--- | :--- |
| **`coin_code`** | VARCHAR(16) | **PK**, NOT NULL | 코인 코드 (예: `BTC_KRW`) |
| `coin_name_kr` | VARCHAR(256) | NOT NULL, DEFAULT '' | 코인 한글명 |
| `coin_name_en` | VARCHAR(256) | NOT NULL, DEFAULT '' | 코인 영문명 |
| `coin_price` | DOUBLE UNSIGNED| NOT NULL, DEFAULT 0 | 코인 종가/현재가 |
| `coin_amount` | DOUBLE UNSIGNED| NOT NULL, DEFAULT 0 | 24시간 누적 거래대금 |
| `coin_order` | INT(10) UNSIGNED| NOT NULL, AUTO_INCREMENT | 정렬/인덱싱을 위한 순번 |
| `coin_update` | DATETIME | DEFAULT CURRENT_TIMESTAMP ON UPDATE | 최근 업데이트 시간 |

#### 🗂️ 테이블: `coin_last_ws_query`
어떤 코인에 대해 어떤 웹소켓 스트리밍(체결, 호가 등)을 수집하고 있는지 상태를 기록합니다. (재시작 시 활용)
| Column Name | Data Type | Constraint & Default | Description |
| :--- | :--- | :--- | :--- |
| **`coin_query`** | VARCHAR(32) | **PK**, NOT NULL | 쿼리 ID |
| `coin_code` | VARCHAR(16) | NOT NULL, FK(coin_info) | 연결된 코인 코드 |
| `query_type` | VARCHAR(16) | NOT NULL | 수집 데이터 종류(체결, 호가 등) |
| `coin_api_type` | VARCHAR(32) | NOT NULL | 빗썸 웹소켓 연결용 타입 명 |
| `coin_api_coin_code`| VARCHAR(32) | NOT NULL | 빗썸 API용 코인 코드 형태 |

<br/>

### 1-2. `KoreaInvest` DB
한국투자증권에서 제공하는 국내(KOSPI, KOSDAQ, KONEX) 및 해외(NYSE, NASDAQ, AMEX) 주식의 마스터 데이터 정보를 저장합니다.

#### 🗂️ 테이블: `stock_info`
수집된 주식들의 상장 수식 수, 시가 총액, 마켓 분류 등을 기록합니다.
| Column Name | Data Type | Constraint & Default | Description |
| :--- | :--- | :--- | :--- |
| **`stock_code`** | VARCHAR(16) | **PK**, NOT NULL | 주식/티커 코드 |
| `stock_name_kr` | VARCHAR(256) | NOT NULL, DEFAULT '' | 주식 한글명 |
| `stock_name_en` | VARCHAR(256) | NOT NULL, DEFAULT '' | 주식 영문명 |
| `stock_market` | VARCHAR(32) | NOT NULL, DEFAULT '' | 소속 마켓 (예: KOSPI, NASDAQ) |
| `stock_type` | VARCHAR(32) | NOT NULL | 주식 속성 (STOCK, ETF, ETN) |
| `stock_count` | BIGINT(20) UNSIGNED | NOT NULL, DEFAULT 0 | 상장 주식 수 |
| `stock_price` | DOUBLE UNSIGNED| NOT NULL, DEFAULT 0 | 현재가 또는 기준가 |
| `stock_capitalization`| DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 시가 총액 (count * price) |
| `stock_update` | DATETIME | DEFAULT CURRENT_TIMESTAMP ON UPDATE | 최근 업데이트 시간 |

#### 🗂️ 테이블: `stock_last_ws_query`
한국투자증권 주식 실시간 웹소켓 구독 상태 기록 테이블입니다.
| Column Name | Data Type | Constraint & Default | Description |
| :--- | :--- | :--- | :--- |
| **`stock_query`** | VARCHAR(32) | **PK**, NOT NULL | 쿼리 ID |
| `stock_code` | VARCHAR(16) | NOT NULL, FK(stock_info)| 연결된 주식 코드 |
| `query_type` | VARCHAR(16) | NOT NULL | 수집 데이터 종류 (체결, 호가) |
| `stock_api_type`| VARCHAR(32) | NOT NULL | API 쿼리 타입구분용 |
| `stock_api_stock_code`| VARCHAR(32) | NOT NULL | API 조회용 종목 형태 |

---

## 2. 수집 데이터 전용 (시계열 데이터)

위에서 정의된 종목(코인, 주식)별로 **독립적인 데이터베이스**(`Z_Coin_{Symbol}`, `Z_Stock_{Symbol}`)를 생성하고, 내부에 년도(YYYY)별로 테이블을 동적 생성하여 Week 단위로 파티셔닝(Partitioning)합니다.

### 2-1. 체결 데이터 (Raw 데이터)
모든 실시간 체결 기록을 가장 Raw한 형태로 쌓습니다. 매도/매수 포지션을 포함합니다.
* **코인**: `Z_Coin_{Symbol}.Raw{YYYY}`  (예. `Z_Coin_BTC_KRW.Raw2026`)
* **주식**: `Z_Stock_{Symbol}.Raw{YYYY}` (예. `Z_Stock_AAPL.Raw2026`)

| Column Name | Data Type | Constraint & Default | Description |
| :--- | :--- | :--- | :--- |
| `execution_datetime` | DATETIME | NOT NULL | 체결된 정확한 시간 |
| `execution_price` | DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 체결 가격 |
| `execution_non_volume` | DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 체결 수량 (구분 불가 시) |
| `execution_ask_volume` | DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 매도 체결 수량 |
| `execution_bid_volume` | DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 매수 체결 수량 |

### 2-2. 캔들 데이터 (Candle 데이터 / 10분봉 기준 집계)
Raw 테이블을 활용해 10분봉 단위 시가/종가/고가/저가(OHLC)와 누적 거래량/거래대금을 계산하며 업데이트되는 테이블입니다.
* **코인**: `Z_Coin_{Symbol}.Candle{YYYY}`
* **주식**: `Z_Stock_{Symbol}.Candle{YYYY}`

| Column Name | Data Type | Constraint & Default | Description |
| :--- | :--- | :--- | :--- |
| **`execution_datetime`**| DATETIME | **PK**, NOT NULL | 해당 캔들의 10분 단위 기준 시각 |
| `execution_open` | DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 시가 |
| `execution_close` | DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 종가 |
| `execution_min` | DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 최저가 |
| `execution_max` | DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 최고가 |
| `execution_non_volume`| DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 체결 누적 수량 (구분 불가) |
| `execution_ask_volume`| DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 매도 체결 누적 수량 |
| `execution_bid_volume`| DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 매수 체결 누적 수량 |
| `execution_non_amount`| DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 체결 누적 대금 (구분 불가) |
| `execution_ask_amount`| DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 매도 누적 대금 |
| `execution_bid_amount`| DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 매수 누적 대금 |

### 2-3. 호가 데이터 (Orderbook) - *작업 예정(TODO)*
체결이 아닌 매물 대기 중인 호가창 데이터를 담는 테이블입니다. (`주차별 분리`)
* **테이블 형태**: `coin_orderbook_{Symbol}_{YYYYWW}` 및 `stock_orderbook_{Symbol}_{YYYYWW}`

| Column Name | Data Type | Constraint & Default | Description |
| :--- | :--- | :--- | :--- |
| `execution_datetime` | DATETIME | NOT NULL | 호가 데이터 발생 시간 |
| `execution_price` | DOUBLE UNSIGNED | NOT NULL, DEFAULT 0 | 호가 |
| `execution_volume` | BIGINT(20) UNSIGNED| NOT NULL, DEFAULT 0 | 해당 호가에 걸린 잔량 |

---

## 3. 로깅 목적 (Log DB)
시스템 상의 모든 로그(에러 메세지, 주기적 안내 등)를 기록하는 DB입니다.

#### 🗂️ 테이블: `Log{YYYY}`
`Util.py`의 `MySqlLogger` 클래스를 통해 비동기로 삽입되며, 연도별 DB가 일주일 단위(YEARWEEK)로 파티셔닝 됩니다.
| Column Name | Data Type | Constraint & Default | Description |
| :--- | :--- | :--- | :--- |
| `log_datetime` | DATETIME | DEFAULT CURRENT_TIMESTAMP | 로그 발생 시간 |
| `log_name` | VARCHAR(255) | | 로그 생성 주체 (예: ApiBithumb) |
| `log_type` | CHAR(1) | | 로그 타입 (E, N 등) |
| `log_message` | TEXT | | 로그 상세 메시지 (에러 원인 포함) |
| `log_function`| VARCHAR(255) | | 로그를 호출한 내부 함수명 |
| `log_file` | VARCHAR(255) | | 로그를 호출한 내부 파일명 |
| `log_line` | INT | | 실제 로그가 반환된 코드 내 라인 수 |
