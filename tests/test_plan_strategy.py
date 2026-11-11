"""운영 상담의 실패를 재현: 비중 오해, 부분 잔고 소실, 과거 실행 삭제, 조건과 재원의 혼동."""

from datetime import date, datetime, timezone

import pytest

from app.services import invest_plan as ip, plan_changes as pc, plan_reconcile, plan_strategy as ps


def policy(**overrides):
    return ps.Policy.model_validate({"id": "irp", "title": "IRP 목표", "account": "IRP", "status": "confirmed",
        "targets": [{"code": "A", "market": "KR", "name": "혼합", "weight": .6},
                    {"code": "B", "market": "KR", "name": "주식", "weight": .4}], **overrides})


def doc():
    return ip.PlanDoc.model_validate({"accounts": [{"name": "IRP", "type": "pension"}], "holdings": [
        {"kind": "cash", "name": "예수금", "account": "IRP", "qty": 1000, "unit_price": 1},
        {"kind": "stock", "name": "혼합", "code": "A", "market": "KR", "account": "IRP", "qty": 80, "avg_buy_price": 9},
        {"kind": "stock", "name": "주식", "code": "B", "market": "KR", "account": "IRP", "qty": 20, "buy_cost_krw": 180}],
        "strategy": {"policies": [policy().model_dump()]}})


def rows(d=None):
    return ip.valuate(d or doc(), {"A": 10, "B": 10}, {}, {})["root"]["rows"]


def build(d, operations):
    change = pc.Change(base_rev=10, request_key="test", operations=operations)
    return pc.build(d, change, "사용자 확인 내용", datetime(2026, 11, 11, tzinfo=timezone.utc))


def test_balance_target_is_not_contribution_split():
    out = ps.allocate(policy(), rows(), 500)
    orders = {r["code"]: r for r in out["orders"]}
    # 현재 80:20, 총 1500원에 60:40 → 100원/400원. 입금액의 60:40=300/200이 아니다.
    assert orders["A"]["qty"] == 10 and orders["B"]["qty"] == 40
    assert orders["A"]["after_weight"] == .6
    assert out["remaining_cash"] == 500 and out["total_absolute_deviation_pp"] == 0
    assert not out["execution_ready"]


def test_buy_only_insufficient_budget_keeps_overweight_and_reports_gap():
    out = ps.allocate(policy(), rows(), 100)
    assert [o["qty"] for o in out["orders"]] == [0, 10]
    assert out["max_deviation_pp"] > 0 and out["spent"] == 100
    assert out["total_absolute_deviation_pp"] == pytest.approx(2 * out["max_deviation_pp"])


@pytest.mark.parametrize("budget,fee", [(1001, 0), (-1, 0), (float("nan"), 0), (10, float("nan")), (10, .2)])
def test_invalid_budget_or_fee_is_not_a_trade(budget, fee):
    with pytest.raises(ValueError):
        ps.allocate(policy(), rows(), budget, fee)


def test_reserve_and_fees_are_in_cash_constraint():
    out = ps.allocate(policy(reserve_cash=500), rows(), 500, .01)
    assert out["spent"] + out["estimated_cost"] <= 500
    assert out["remaining_cash"] >= 500
    with pytest.raises(ValueError, match="현금"):
        ps.allocate(policy(reserve_cash=501), rows(), 500)


def test_missing_cost_does_not_block_weights_but_unknown_quote_does():
    d = doc()
    for h in d.holdings:
        h.avg_buy_price = h.buy_cost_krw = None
    assert ps.allocate(policy(), rows(d), 100)["spent"] == 100
    rr = rows(d)
    rr[1]["price"] = None
    with pytest.raises(ValueError, match="시세"):
        ps.allocate(policy(), rr, 100)


def test_unmapped_holding_or_stale_quote_cannot_silently_drop_from_denominator():
    rr = rows()
    rr.append({**rr[1], "code": "C"})
    with pytest.raises(ValueError, match="목표에 없는"):
        ps.allocate(policy(), rr, 100)
    rr = rows()
    rr[1]["quote_stale"] = True
    with pytest.raises(ValueError, match="오래된"):
        ps.allocate(policy(), rr, 100)


def test_partial_image_updates_only_seen_holding_and_invalidates_only_changed_cost():
    before = doc()
    after = build(before, [{"kind": "holding_patch", "data": {"account": "IRP", "code": "A", "market": "KR", "qty": 81}}])
    assert after.holdings[1].qty == 81 and after.holdings[1].avg_buy_price is None
    assert after.holdings[2] == before.holdings[2] and after.holdings[0] == before.holdings[0]
    # 새 평균가까지 읽으면 실제 필드로 남는다.
    after = build(before, [{"kind": "holding_patch", "data": {"account": "IRP", "code": "A", "market": "KR", "qty": 81, "avg_buy_price": 9.5}}])
    assert after.holdings[1].avg_buy_price == 9.5 and after.holdings[1].unit_price is None


def test_batch_validation_does_not_mutate_input_on_later_failure():
    before = doc()
    snapshot = before.model_dump_json()
    with pytest.raises(ValueError):
        build(before, [{"kind": "holding_patch", "data": {"account": "IRP", "code": "A", "market": "KR", "qty": 81}},
                       {"kind": "policy_upsert", "data": {"id": "bad"}}])
    assert before.model_dump_json() == snapshot


def test_unknown_fields_are_errors_not_silent_data_loss():
    with pytest.raises(ValueError, match="알 수 없는"):
        build(doc(), [{"kind": "holding_patch", "data": {"account": "IRP", "code": "A", "market": "KR", "average": 10}}])


def test_repeated_canonical_metadata_does_not_touch_other_holding():
    before = doc()
    after = build(before, [{"kind": "holding_patch", "data": {"account": "IRP", "code": "B", "market": "KR", "qty": 20, "unit": "주", "type": "pension"}}])
    assert after.holdings == before.holdings


def test_corrected_policy_keeps_original_and_updates_one_canonical_policy():
    before = doc()
    replacement = policy(id="irp2", supersedes="irp").model_dump()
    replacement["targets"][0]["weight"] = .5
    replacement["targets"][1]["weight"] = .5
    after = build(before, [{"kind": "policy_upsert", "data": replacement}])
    assert [p.status for p in after.strategy.policies] == ["superseded", "confirmed"]
    assert after.strategy.policies[0].targets[0].weight == .6
    assert after.strategy.policies[1].evidence.source == "사용자 확인 내용"
    with pytest.raises(ValueError, match="원본"):
        build(before, [{"kind": "policy_upsert", "data": policy().model_dump()}])


def scenario(**kwargs):
    return ps.Scenario.model_validate({"id": "buy", "title": "분할 매수", "assumption": "가상 조건", "action": "buy",
        "account": "IRP", "budget": 600, "condition": "상담에서 자료 확인", "condition_source": "공식 자료",
        "rationale": "목표 비중 보완", "invalidation": "필요 현금 증가", "fallback": "보류 후 재검토", "review_on": "2027-01-01", **kwargs})


def decision(identifier="d", **kwargs):
    return ps.Decision(id=identifier, title="추가 매수 검토", question="현재 재원으로 추가할까", scenarios=[scenario()],
                       selected_id="buy", status="selected", **kwargs)


def test_unresolved_conditions_cannot_be_selected():
    with pytest.raises(ValueError, match="조건"):
        ps.Decision(id="d", title="검토", question="살까", scenarios=[scenario(fallback="")], selected_id="buy", status="selected")
    # 미정은 초안으로 보존한다.
    d = ps.Decision(id="d", title="검토", question="살까", scenarios=[scenario(fallback="")])
    assert d.status == "draft"


def test_exclusive_alternatives_share_budget_but_parallel_decisions_cannot():
    one = decision()
    one.scenarios.append(scenario(id="other", budget=900))
    s = ps.Strategy(decisions=[one])
    assert ps.review(s, rows(), date(2026, 11, 11))["funding"][0]["reserved"] == 600
    s.decisions.append(decision("d2"))
    out = ps.review(s, rows(), date(2026, 11, 11))
    assert out["funding"][0]["reserved"] == 1200 and not out["funding"][0]["ok"]


def test_observation_needs_no_dummy_branch_or_trade():
    after = build(doc(), [{"kind": "observation_upsert", "data": {
        "id": "watch", "title": "실적 관찰", "at": "2027-01-01T09:00:00+09:00", "purpose": "가정 확인", "source": "공식 발표"}}])
    assert len(after.strategy.observations) == 1 and after.nodes == [] and after.holdings == doc().holdings


def test_execution_survives_restore_and_rejects_overwrite():
    old = doc()
    record = ip.ExecutionRecord(id="actual", reference="d", title="실제 보고", at=date(2026, 11, 11), status="reported", source="사용자 보고")
    old.execution_log.append(record)
    restored = doc()
    plan_reconcile.preserve_execution(old, restored)
    assert restored.execution_log == [record]
    restored.execution_log[0] = record.model_copy(update={"status": "confirmed"})
    with pytest.raises(ValueError, match="덮어쓸"):
        plan_reconcile.preserve_execution(old, restored)


def test_condition_met_is_not_executed():
    d = decision()
    d.scenarios[0].condition_state = "met"
    assert ps.review(ps.Strategy(decisions=[d]), rows(), date.today())["decisions"][0]["execution_state"] == "unexecuted"


def test_no_keyword_or_assistant_question_alone_grants_permission():
    assert not pc.direct_scopes("이 원칙은 맞아?")
    assert not pc.direct_scopes("원칙 기록하지 마")
    assert not pc.direct_scopes("잔고 기록했니?")
    assert pc.direct_scopes("이 잔고 수량을 기록해줘") == {"facts"}
    assert not pc.affirmative("응 그런데 비중은 바꿔")
    assert pc.affirmative("응")
    op = pc.Operation(kind="decision_upsert", data=decision().model_dump(mode="json"))
    assert not pc.direct_allowed("계획을 기록해줘", [op])
    assert pc.direct_allowed("이 계획을 선택해서 기록해줘", [op])
    assert not pc.direct_allowed("선택은 나중에 하고 계획 초안을 기록해줘", [op])


def test_observation_permission_does_not_expand_to_facts_or_forbidden_policy():
    message = "IRP 잔고를 확인하는 관찰 일정만 추가해서 기록해줘. 매매나 새 원칙은 정하지 마."
    assert pc.direct_scopes(message) == {"observations"}
    assert pc.direct_scopes("잔고 수량을 기록해줘. 원칙은 바꾸지 마.") == {"facts"}
    assert not pc.direct_scopes("원칙은 저장하지 말고 검토만 해줘")
    assert not pc.direct_scopes('"원칙을 저장해줘"라는 말은 무슨 뜻이야?')


def test_strategy_update_is_not_reported_as_no_change():
    before = doc()
    after = before.model_copy(deep=True)
    after.strategy.goals.append(ps.Goal(id="g", title="노후", purpose="장기 적립"))
    assert ip.diff_summary(before, after) == "목표 갱신"
