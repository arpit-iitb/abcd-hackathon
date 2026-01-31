from agents.fraud import run_fraud
from app.config import load_config_dir


def test_fraud_missing_data_returns_insufficient():
    config = load_config_dir("configs")
    payload = {"bank_statement": {}, "payslip": {}, "id_verification": {}, "bureau": {}}
    result = run_fraud(payload, config, {})
    assert result["status"] == "insufficient_data"
