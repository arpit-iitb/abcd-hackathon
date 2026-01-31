from agents.bureau import extract_dpd_values, extract_enquiry_count, run_bureau
from app.config import load_config_dir


def test_extract_dpd_values_from_string():
    data = {
        "repayment_history": "0, 30, 60, STD"
    }
    values = extract_dpd_values(data)
    assert 30 in values
    assert 60 in values
    assert 0 in values


def test_extract_enquiry_count_from_list():
    data = {
        "as_of_date": "2025-12-31",
        "enquiries": [
            {"date": "2025-12-15"},
            {"date": "2025-11-15"},
        ],
    }
    count = extract_enquiry_count(data, 30)
    assert count == 1


def test_bureau_scoring_low_high():
    config = load_config_dir("configs")
    payload_low = {
        "raw": {
            "as_of_date": "2025-12-31",
            "enquiries": [{"date": "2025-12-20"}],
            "repayment_history": "0,0,0",
        }
    }
    result_low = run_bureau(payload_low, config, {})
    assert result_low["output"]["bureau_risk_grade"] == "low"

    payload_high = {
        "raw": {
            "as_of_date": "2025-12-31",
            "enquiries": [
                {"date": "2025-12-30"},
                {"date": "2025-12-29"},
                {"date": "2025-12-28"},
                {"date": "2025-12-27"},
                {"date": "2025-12-26"},
                {"date": "2025-12-25"},
            ],
            "repayment_history": "30,60,90,60",
        }
    }
    result_high = run_bureau(payload_high, config, {})
    assert result_high["output"]["bureau_risk_grade"] == "high"
