from agents.id_verification import compute_match_score, run_id_verification
from agents.payslip import run_payslip
from app.config import load_config_dir
from app.json_utils import load_json


def test_name_normalization_punctuation():
    score = compute_match_score("Parag Bajaj", "Parag, Bajaj")
    assert score == 1.0


def test_id_verification_match():
    config = load_config_dir("configs")
    payload = {
        "lead": {"name": "Parag Bajaj"},
        "documents": {
            "aadhaar_doc": {"parsed_json": {"name": "Parag Bajaj", "aadhaar_last4": "1234"}, "image_base64": "face-data"},
            "pan_doc": {"parsed_json": {"name": "Parag Bajaj", "pan_masked": "XXXXXX1234"}},
            "selfie_doc": {"image_base64": "face-data"},
        },
    }
    result = run_id_verification(payload, config, {})
    assert result["status"] == "ok"
    assert result["output"]["name_match"] is True
    assert result["output"]["face_match"] is True


def test_payslip_parsing_sample():
    config = load_config_dir("configs")
    payslip_payload = load_json("data/payslip_samples.json")[0]
    payload = {"documents": {"payslip_doc": payslip_payload["payslip_doc"]}}
    result = run_payslip(payload, config, {})
    assert result["status"] == "ok"
    assert result["output"]["monthly_income_estimate"] == 58000


def test_payslip_ocr_stub():
    config = load_config_dir("configs")
    payload = {"documents": {"payslip_doc": {"image_base64": "stub"}}}
    result = run_payslip(payload, config, {})
    assert result["status"] == "insufficient_data"
    assert "OCR not enabled" in result["rationale_summary"][0]
