from ai_agents.rules.fallback_engine import rule_based_financial_advice


def test_fallback_flags_loss():
    advice = rule_based_financial_advice({"total_sales": 100.0, "total_expenses": 200.0, "net_profit": -100.0})
    assert "loss" in advice.lower()


def test_fallback_flags_high_expense_ratio():
    advice = rule_based_financial_advice({"total_sales": 100.0, "total_expenses": 80.0, "net_profit": 20.0})
    assert "70%" in advice or "expenses" in advice.lower()


def test_fallback_handles_zero_activity():
    advice = rule_based_financial_advice({"total_sales": 0.0, "total_expenses": 0.0, "net_profit": 0.0})
    assert "no transactions" in advice.lower()


def test_fallback_healthy_case():
    advice = rule_based_financial_advice({"total_sales": 1000.0, "total_expenses": 200.0, "net_profit": 800.0})
    assert "healthy" in advice.lower()
