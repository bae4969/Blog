# 주식 구독 추천 기준

## ETF 추천 기준
- 이미 구독 중인 ETF의 테마/섹터를 먼저 파악
- 같은 지수를 추종하는 중복 ETF(예: S&P500을 TIGER/KODEX/RISE 등으로 여러 개) 추천하지 않음
- **빠진 섹터/테마**를 찾아서 해당 테마의 시총 상위 ETF 1~2개만 추천
- 한국/미국 ETF 모두 포함 가능
- ETF도 추천 대상에 포함 (사용자가 ETF 환영)

## 개별주식 추천 기준
- ETF/ETN/우선주/ADR 제외하고 순수 개별주식 위주
- 시가총액 상위 순으로 정렬
- 이미 구독 중인 종목과 겹치지 않는 섹터 우선

## DB 조회 방법
- 미구독 종목: stock_info LEFT JOIN stock_last_ws_query WHERE wsq IS NULL
- 미구독 코인: coin_info LEFT JOIN coin_last_ws_query WHERE cwq IS NULL
- 시장 필터: KR=KOSPI/KOSDAQ/KONEX, US=NYSE/NASDAQ/AMEX, COIN=Bithumb
