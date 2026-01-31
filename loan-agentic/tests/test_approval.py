from agents.approval import run_approval
from app.config import load_config_dir


def _payload(requested_amount, avg_balance, risk_grade, fraud_grade, selected=True):
    return {
        "lead": {"requested_amount": requested_amount},
        "bank_statement": {"avg_balance": avg_balance},
        "risk_assessment": {"final_risk_grade": risk_grade},
        "fraud": {"fraud_grade": fraud_grade},
        "lead_sourcing": {"output": {"selected": selected}},
    }


def test_approval_reject_fraudulent():
    config = load_config_dir("configs")
    payload = _payload(100000, 20000, "low", "fraudulent")
    result = run_approval(payload, config, {})
    assert result["output"]["decision"] == "rejected"
    assert "fraudulent_grade" in result["output"]["reasons"]


def test_approval_sanction_cap_and_balance():
    config = load_config_dir("configs")
    payload = _payload(200000, 10000, "low", "good")
    result = run_approval(payload, config, {})
    assert result["output"]["sanctioned_amount"] == 100000


def test_approval_reject_below_min_amount():
    config = load_config_dir("configs")
    payload = _payload(3000, 1000, "low", "good")
    result = run_approval(payload, config, {})
    assert result["output"]["decision"] == "rejected"
    assert result["output"]["sanctioned_amount"] == 0.0
    assert "sanction_below_min" in result["output"]["reasons"]


def test_approval_human_review_for_suspicious_fraud():
    config = load_config_dir("configs")
    payload = _payload(100000, 20000, "medium", "suspicious")
    result = run_approval(payload, config, {})
    assert result["output"]["decision"] == "human_review_required"
    assert result["output"]["human_review"]["required"] is True
