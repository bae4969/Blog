"""현재 실제 보유의 자산 패널·상담 공용 집계. 계획 가지와 저장된 원금·부채는 바꾸지 않는다."""

import json

from app.services import invest_plan as ip

GROUPS = (("cash", "현금성"), ("invest", "투자성"), ("housing", "부동산"))


def asset_group(row: dict) -> str:
    kind = row.get("type")
    if kind == "housing":
        return "housing"
    if kind in ("cash", "saving"):
        return "cash"
    if kind in ("invest", "pension"):
        return "invest"
    return "cash" if row["kind"] == "cash" else "invest"


def summarize(doc: ip.PlanDoc, current: dict, previous: dict) -> dict:
    """총액은 모든 부채 차감, 부동산은 연결된 부채만 차감. 미평가액을 0원으로 보이지 않는다."""
    accounts = {a.name: a for a in doc.accounts}
    groups = {key: {"key": key, "label": label, "items": [], "value": 0.0} for key, label in GROUPS}
    items = {}
    rows = []
    for i, value in enumerate(current["rows"]):
        row = dict(value)
        prior = previous["rows"][i]
        row["estimated"] = bool((row["code"] or row.get("quantity_missing")) and row["price"] is None
                                and row["value"] is not None)
        row["valuation"] = ("missing" if row["value"] is None else "quote" if row["price"] is not None else
                            "fx" if row["kind"] == "cash" and row["currency"] != "KRW" else
                            "fixed" if row["kind"] == "cash" and row["qty"] is not None else "input")
        # 전일 시세가 없을 때 amount 대체값으로 손익을 만들어 내지 않는다.
        row["change"] = (row["value"] - prior["value"]
                         if (row["price"] is not None and prior["price"] is not None
                             or row["kind"] == "cash" and row["currency"] != "KRW")
                         and row["value"] is not None and prior["value"] is not None else None)
        rows.append(row)
        group = asset_group(row)
        name = row["account"] or row["name"]
        key = (group, name)
        if key not in items:
            account = accounts.get(name)
            item = {"name": name, "institution": account.institution if account else "",
                    "type": row["type"], "rows": [], "debts": [], "debt": 0.0}
            items[key] = item
            groups[group]["items"].append(item)
        items[key]["rows"].append(row)

    housing_accounts = {a.name for a in doc.accounts if a.type == "housing"}
    housing_accounts.update(r["account"] for r in rows if asset_group(r) == "housing" and r["account"])
    other_debt = 0.0
    for debt in doc.debts:
        if debt.account and debt.account in housing_accounts:
            key = ("housing", debt.account)
            if key not in items:
                account = accounts.get(debt.account)
                item = {"name": debt.account, "institution": account.institution if account else "",
                        "type": "housing", "rows": [], "debts": [], "debt": 0.0}
                items[key] = item
                groups["housing"]["items"].append(item)
            items[key]["debt"] += debt.balance
            items[key]["debts"].append({"name": debt.name, "balance": debt.balance})
        else:
            other_debt += debt.balance

    def change_of(holdings):
        priced = [r for r in holdings if r["code"] or r["kind"] == "cash" and r["currency"] != "KRW"]
        return (sum(r["change"] for r in priced)
                if priced and all(r["change"] is not None for r in priced) else None)

    for group in groups.values():
        for item in group["items"]:
            item["gross"] = (sum(r["value"] for r in item["rows"])
                             if all(r["value"] is not None for r in item["rows"]) else None)
            item["value"] = item["gross"] - item["debt"] if item["gross"] is not None else None
            item["change"] = change_of(item["rows"])
        group["value"] = (sum(item["value"] for item in group["items"])
                          if all(item["value"] is not None for item in group["items"]) else None)

    missing = sum(r["value"] is None for r in rows)
    total = current["net"] if not missing else None
    stocks = [{**r, "weight": r["value"] / total if total and total > 0 and r["value"] is not None else None}
              for r in rows if r["kind"] == "stock"]
    stock_total = sum(r["value"] for r in stocks) if all(r["value"] is not None for r in stocks) else None
    return {"total": total, "known_total": current["net"], "change": change_of(rows),
            "groups": list(groups.values()), "other_debt": other_debt, "missing": missing,
            "estimated": sum(r["estimated"] for r in rows),
            "quantity_missing": sum(r.get("quantity_missing", False) for r in rows),
            "stale": sum(bool(r.get("quote_stale")) for r in rows), "stocks": stocks,
            "stock_total": stock_total,
            "stock_weight_pct": round(stock_total / total * 100, 2)
            if total and total > 0 and stock_total is not None else None}


def prompt(assets: dict) -> str:
    """서버가 계산한 실제 보유 평가를 매 상담에 제공한다. 같은 데이터가 자산 패널에도 쓰인다."""
    compact = {k: assets[k] for k in ("total", "known_total", "stock_total", "stock_weight_pct", "other_debt", "missing", "estimated",
                                     "holdings_as_of", "checked_at")}
    compact["groups"] = [{"label": g["label"], "value": g["value"]} for g in assets["groups"]]
    compact["holdings"] = [{k: r.get(k) for k in ("name", "account", "code", "qty", "quantity_unit", "currency",
                                                  "unit_value_krw", "value", "valuation", "quantity_missing", "quote_at", "fx_rate")}
                           for g in assets["groups"] for item in g["items"] for r in item["rows"]]
    compact["consistency"] = assets.get("consistency", [])
    compact["stocks"] = [{k: r[k] for k in ("name", "code", "market", "account", "qty", "value", "price",
                                            "weight", "estimated", "valuation", "quote_at")} for r in assets["stocks"]]
    compact["gold"] = [{k: r[k] for k in ("name", "code", "account", "qty", "quantity_unit", "value", "price",
                                          "estimated", "valuation", "quote_at", "quote_source", "quote_stale")}
                       for g in assets["groups"] for item in g["items"] for r in item["rows"] if r.get("quantity_unit") == "g"]
    ratio = f"{assets['stock_weight_pct']:.2f}%" if assets["stock_weight_pct"] is not None else "계산 불가"
    return ("## 이번 상담의 실제 보유 자산 평가\n"
            f"현재 주식 비중(전체 순자산 기준): {ratio}. 이 값을 그대로 인용한다. "
            "이전 대화의 금액·비중과 다르면 이번 평가를 우선하고 과거 답의 계산을 재사용하지 않는다.\n"
            "투자 질문은 먼저 사용자가 실제 가진 주식의 수량·계좌·평가액·비중으로 계산한다. "
            "시장 전망을 이 보유 종목과 전체 자산에 미치는 원화 영향으로 연결한다. "
            "주식 비중은 서버가 계산한 stock_weight_pct(%)를 그대로 사용한다. "
            "모든 보유는 수량×단위당 원화 가치로 평가한다. 원화 1원은 1개, 외화는 원통화 잔액×해당 통화 환율이다. "
            "수량·통화 미확인은 입력 평가액에서 역산하지 말고 실제 수량을 확인한다. "
            "기억과 계획의 금액·일정이 다르면 현재 계획을 우선하고 불일치를 알린다. 기억을 임의로 고치지 않는다. "
            "시세가 있는 종목은 서버가 수량×수집된 최신 시세×환율로 계산했다. valuation=input은 등록된 입력 평가액이며 최신 시세로 계산한 값이 아니다. "
            "금현물(gold)은 주식에 포함하지 않으며 qty는 g, price는 네이버 KRX 원/g 시세다. "
            "금현물 평가액은 qty×price이고 quote_stale=true이면 갱신 지연 중인 마지막 평가액이다. "
            "아래 값은 미래 계획 가지의 보유가 아니다. "
            "아래 평가 요약의 부동산 금액과 total은 이미 대출을 차감한 순액이므로 대출을 다시 빼지 않는다. "
            "시세 시각(quote_at)·보유 기준일을 확인하고, 입력 평가액 대체(estimated)·미확인(missing)을 "
            "실시간 확정값으로 말하지 않는다. 추가 확인이나 상담 중 보유 변경 뒤에는 plan_get으로 다시 조회한다.\n"
            + json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
