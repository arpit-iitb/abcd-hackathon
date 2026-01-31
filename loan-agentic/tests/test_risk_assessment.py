from agents.risk_assessment import run_risk_assessment
from app.config import load_config_dir


def test_risk_assessment_missing_data_returns_insufficient():
    config = load_config_dir("configs")
    payload = {"bureau": {}, "bank_statement": {}, "lead": {}}
    result = run_risk_assessment(payload, config, {})
    assert result["status"] == "insufficient_data"
