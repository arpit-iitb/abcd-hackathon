from app.config import load_config_dir
from agents.lead_sourcing import run_lead_sourcing
from app.json_utils import load_json


def test_lead_sourcing_pass_fail():
    config = load_config_dir("configs")
    leads = load_json("data/lead_samples.json")

    pass_result = run_lead_sourcing(leads[0], config, {})
    assert pass_result["status"] == "ok"
    assert pass_result["output"]["selected"] is True
    assert pass_result["output"]["rejection_reasons"] == []

    fail_result = run_lead_sourcing(leads[1], config, {})
    assert fail_result["status"] == "ok"
    assert fail_result["output"]["selected"] is False
    assert "tier_not_allowed" in fail_result["output"]["rejection_reasons"]
