"""주식·코인 리소스 스키마.

⚠️ 옛 컬럼 이름(`stock_code`·`execution_datetime`…)을 그대로 내보내지 않는다.
   `/stocks/api/*` 는 DB 컬럼명을 그대로 실어 나르는데, 그러면 컬럼을 못 바꾸게 된다.
   주식과 코인이 서로 다른 테이블·컬럼을 쓰는 것도 여기서 흡수한다 — 소비자는 둘을
   같은 모양으로 본다.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class StockOut(BaseModel):
    code: str
    name_kr: str | None = None
    name_en: str | None = None
    market: str = Field(description="KOSPI·NASDAQ·COIN 등")
    type: str | None = Field(default=None, description="STOCK·ETF·ETN·COIN")
    price: float | None = None
    market_cap: float | None = Field(default=None, description="시가총액. 코인은 가격×수량")
    quantity: float | None = Field(default=None, description="상장주식수 또는 코인 수량")
    #: 등락률은 **마지막 거래일 기준**이다(KST 의 오늘이 아니다) — `_latest_quotes` 참조.
    prev_price: float | None = Field(default=None, description="직전 거래일 종가")
    change_pct: float | None = Field(default=None, description="등락률(%). 직전 종가가 없으면 null")


class Candle(BaseModel):
    """⚠️ 액면분할·병합이 **소급 보정된** 값이다(원본 그대로가 아니다).
    보정을 안 하면 분할 시점에서 차트가 절벽처럼 끊긴다.

    ⚠️ 거래량은 원본이 **매수·매도·미구분 셋으로 나뉘어** 있다(`ask`/`bid`/`non`).
       DB 컬럼은 `execution_min`·`execution_max` 인데 뜻은 저가·고가라 이름을 바로잡는다.
    """

    at: datetime
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = Field(default=None, description="셋의 합")
    ask_volume: float | None = None
    bid_volume: float | None = None
    non_volume: float | None = Field(default=None, description="매수·매도 구분이 안 되는 체결")


class Execution(BaseModel):
    at: datetime
    price: float | None = None
    #: 체결을 매수·매도로 가른 값. 구분이 안 되는 건 `non_volume` 으로 온다.
    non_volume: float | None = None
    ask_volume: float | None = None
    bid_volume: float | None = None


class MarketStat(BaseModel):
    """시장 묶음 통계 — 화면 상단의 한국·미국·코인 탭이 쓴다.

    ⚠️ **구독 중인 종목만** 센다(`stock_last_ws_query`·`coin_last_ws_query` 와 조인).
       전체 종목을 세면 수집하지 않는 것까지 들어가 화면 숫자와 어긋난다.
    """

    group: str = Field(description="KR·US·COIN")
    label: str = Field(description="한국·미국·코인")
    count: int
    market_cap: float | None = None


class TopStock(BaseModel):
    """거래대금 상위. `candle` 이 종목별 테이블이라 UNION 으로 합계를 낸 결과다."""

    code: str
    name_kr: str | None = None
    market: str | None = None
    price: float | None = None
    trading_amount: float | None = Field(default=None, description="기간 거래대금 합계")
    prev_price: float | None = Field(default=None, description="직전 거래일 종가")
    change_pct: float | None = Field(default=None, description="등락률(%). 직전 종가가 없으면 null")


class HeatmapItem(BaseModel):
    """히트맵 타일 하나 — 크기는 `market_cap`, 색은 `change_pct`.

    ⚠️ `change_pct` 는 **각 종목 캔들의 마지막 날짜**를 기준으로 계산한다. 미국 종목은
       `execution_datetime` 이 현지시각(ET)이라 KST 의 "오늘"로 자르면 하루씩 어긋난다.
       종목마다 자기 마지막 거래일과 그 직전 거래일을 비교하므로 시장이 섞여도 맞는다.
    """

    code: str
    name_kr: str | None = None
    market: str | None = None
    market_cap: float | None = Field(default=None, description="타일 크기. 코인은 가격×수량")
    price: float | None = Field(default=None, description="마지막 거래일 종가")
    prev_price: float | None = Field(default=None, description="직전 거래일 종가")
    change_pct: float | None = Field(default=None, description="등락률(%). 직전 종가가 없으면 null")


class QuoteOut(BaseModel):
    """지수·환율 카드 하나.

    ⚠️ `name` 은 `quote_info` 를 그대로 쓰지 않는다. 크로스 환산 환율은 `quote_code` 가
       **환산 재료**(`KRWEUR` → `FXEUR` = "달러/유로")라 원본 이름이 실제 저장값과 다르다.
    """

    code: str = Field(description="`quote_last_rest_query.quote_query`. 저장 식별자이자 테이블명")
    name: str
    category: str = Field(description="INDEX_KR·INDEX_EX·FX")
    price: float | None = None
    prev_price: float | None = None
    change_pct: float | None = Field(default=None, description="수집 이력이 하루뿐이면 null")
    at: datetime | None = Field(default=None, description="마지막 값의 시각. 해외지수는 현지시각")
    spark: list[float] = Field(default_factory=list, description="마지막 거래일 종가 열 — 스파크라인용")
