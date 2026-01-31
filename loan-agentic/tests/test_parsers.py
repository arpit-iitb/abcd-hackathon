from app.json_utils import load_json
from app.state import LoanApplicationInput


def build_application_payload(sample_dir: str = "data"):
    lead_payload = load_json(f"{sample_dir}/lead_samples.json")
    bureau_payload = load_json(f"{sample_dir}/bureau_samples.json")
    bank_payload = load_json(f"{sample_dir}/bank_statement_samples.json")
    id_docs_payload = load_json(f"{sample_dir}/id_docs_samples.json")
    payslip_payload = load_json(f"{sample_dir}/payslip_samples.json")

    lead_sample = lead_payload[0] if isinstance(lead_payload, list) else lead_payload
    bureau_sample = bureau_payload[0] if isinstance(bureau_payload, list) else bureau_payload
    bank_sample = bank_payload[0] if isinstance(bank_payload, list) else bank_payload
    id_docs_sample = id_docs_payload[0] if isinstance(id_docs_payload, list) else id_docs_payload
    payslip_sample = payslip_payload[0] if isinstance(payslip_payload, list) else payslip_payload

    return {
        "lead": lead_sample,
        "bureau_report": {
            "raw": bureau_sample.get("raw", bureau_sample),
            "normalized": bureau_sample.get("normalized"),
        },
        "bank_statement": bank_sample.get("transactions", bank_sample),
        "documents": {
            "aadhaar_doc": id_docs_sample.get("aadhaar_doc"),
            "pan_doc": id_docs_sample.get("pan_doc"),
            "selfie_doc": id_docs_sample.get("selfie_doc"),
            "payslip_doc": payslip_sample.get("payslip_doc") or {"parsed_json": payslip_sample},
        },
    }


def test_application_schema_validation():
    payload = build_application_payload()
    application = LoanApplicationInput.model_validate(payload)
    assert application.lead.name
    assert len(application.bank_statement) > 0
