from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import yaml


REQUIRED_KEYS = {
    "policy": [
        "lead_filter.allowed_tiers",
        "lead_filter.allowed_product_types",
        "lead_filter.allowed_loan_purposes",
        "lead_filter.max_requested_amount",
        "sanction_policy.max_multiplier_of_avg_balance",
        "sanction_policy.cap_amount",
        "sanction_policy.min_amount",
    ],
    "thresholds": [
        "bureau.enquiry_desperation_window_days",
        "bureau.max_enquiries_low_risk",
        "bureau.max_enquiries_medium_risk",
        "bureau.dpd_bad_threshold",
        "bureau.dpd_count_bad_medium",
        "bureau.dpd_count_bad_high",
        "bank.salary_keyword_list",
        "bank.suspicious_spend_monthly_ratio_medium",
        "bank.suspicious_spend_monthly_ratio_high",
        "bank.min_txns_for_confidence",
        "bank.request_to_balance_multiplier_low",
        "fraud.income_tolerance_ratio",
        "fraud.name_match_low_score",
        "id.name_match_min_score",
        "id.face_match_min_score",
        "id.face_match_enabled",
        "id.ocr_enabled",
        "approval.human_review_confidence_threshold",
        "approval.human_review_if_fraud_suspicious",
        "approval.human_review_if_missing_critical_fields",
        "approval.critical_fields",
        "risk.request_to_balance_multiplier_low",
        "risk.request_to_balance_multiplier_medium",
        "risk.request_to_balance_multiplier_high",
        "risk.adjustment_by_suspicious_grade.low",
        "risk.adjustment_by_suspicious_grade.medium",
        "risk.adjustment_by_suspicious_grade.high",
        "risk.adjustment_by_request_to_balance.low",
        "risk.adjustment_by_request_to_balance.medium",
        "risk.adjustment_by_request_to_balance.high",
    ],
    "suspicious_keywords": ["keywords"],
    "roi": ["roi_by_risk.low", "roi_by_risk.medium", "roi_by_risk.high"],
    "models": ["default.model", "default.temperature"],
}


def load_yaml(path: str) -> Dict[str, Any]:
    content = Path(path).read_text(encoding="utf-8")
    return yaml.safe_load(content) or {}


def _get_path_value(data: Dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_path_value(data: Dict[str, Any], path: str, value: Any) -> None:
    current = data
    parts = path.split(".")
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _parse_env_value(raw: str) -> Any:
    text = raw.strip()
    try:
        return yaml.safe_load(text)
    except Exception:
        return text


def _apply_env_overrides(config: Dict[str, Any], prefix: str = "LOAN_AGENTIC__") -> None:
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix) :].lower().replace("__", ".")
        _set_path_value(config, path, _parse_env_value(value))


def _missing_keys(config: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    for section, paths in REQUIRED_KEYS.items():
        section_data = config.get(section)
        if section_data is None:
            missing.append(f"{section} (entire section)")
            continue
        for path in paths:
            if _get_path_value(section_data, path) is None:
                missing.append(f"{section}.{path}")
    return missing


def load_config_dir(config_dir: str) -> Dict[str, Any]:
    base = Path(config_dir)
    config: Dict[str, Any] = {}
    for path in sorted(base.glob("*.yaml")):
        config[path.stem] = load_yaml(str(path))
    _apply_env_overrides(config)
    missing = _missing_keys(config)
    if missing:
        missing_list = ", ".join(missing)
        raise ValueError(f"Missing required config keys: {missing_list}")
    return config
