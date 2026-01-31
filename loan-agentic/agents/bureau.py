from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.state import AgentResultBase, ErrorItem
from app.llm_runner import llm_enabled, run_llm_agent
from app.utils.masking import mask_sensitive


DATE_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]


def _parse_date(value: str) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _reference_date(data: Dict[str, Any]) -> datetime:
    for key in ("as_of_date", "report_date", "report_generated_date"):
        parsed = _parse_date(str(data.get(key, "")))
        if parsed:
            return parsed
    return datetime.now(timezone.utc)


def _parse_dpd_value(value: Any) -> Optional[int]:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"STD", "STANDARD", "NA", "N/A", "XXX", "X", "-", ""}:
            return 0
        match = re.search(r"\d+", normalized)
        if match:
            return int(match.group(0))
    return None


def _collect_dpd_values(obj: Any) -> List[int]:
    values: List[int] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = key.lower()
            if any(token in key_lower for token in ("dpd", "delinq", "repayment", "days_past_due")):
                values.extend(_extract_from_value(value))
            elif key_lower in {"accounts", "tradelines", "loans"} and isinstance(value, list):
                for item in value:
                    values.extend(_collect_dpd_values(item))
            elif isinstance(value, (dict, list)):
                values.extend(_collect_dpd_values(value))
    elif isinstance(obj, list):
        for item in obj:
            values.extend(_collect_dpd_values(item))

    return values


def _extract_from_value(value: Any) -> List[int]:
    values: List[int] = []
    if isinstance(value, list):
        for item in value:
            parsed = _parse_dpd_value(item)
            if parsed is not None:
                values.append(parsed)
            elif isinstance(item, (dict, list)):
                values.extend(_collect_dpd_values(item))
    elif isinstance(value, dict):
        values.extend(_collect_dpd_values(value))
    elif isinstance(value, str):
        numbers = re.findall(r"\d+", value)
        if numbers:
            values.extend(int(num) for num in numbers)
        else:
            parsed = _parse_dpd_value(value)
            if parsed is not None:
                values.append(parsed)
    else:
        parsed = _parse_dpd_value(value)
        if parsed is not None:
            values.append(parsed)
    return values


def extract_enquiry_count(data: Dict[str, Any], window_days: int) -> Optional[int]:
    direct_keys = [
        "enquiry_count",
        "inquiry_count",
        f"enquiry_count_{window_days}",
        f"enquiry_count_{window_days}d",
        f"enquiry_count_{window_days}_days",
        f"enquiries_{window_days}_days",
        f"inquiries_{window_days}_days",
        "num_enquiries",
    ]
    for key in direct_keys:
        if key in data and isinstance(data[key], (int, float)):
            return int(data[key])

    for key in ("enquiry_history", "enquiries", "inquiries"):
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            if match:
                return int(match.group(0))
        if isinstance(value, list):
            reference = _reference_date(data)
            count = 0
            for item in value:
                if isinstance(item, dict):
                    date_val = item.get("date") or item.get("enquiry_date") or item.get("inquiry_date")
                    days_ago = item.get("days_ago") or item.get("age_days")
                    if isinstance(days_ago, (int, float)):
                        if days_ago <= window_days:
                            count += 1
                        continue
                    parsed = _parse_date(str(date_val)) if date_val else None
                    if parsed:
                        delta_days = (reference - parsed).days
                        if delta_days <= window_days:
                            count += 1
            return count

    return None


def extract_dpd_values(data: Dict[str, Any]) -> List[int]:
    values = _collect_dpd_values(data)
    return values


def _grade_from_enquiries(count: int, max_low: int, max_medium: int) -> str:
    if count <= max_low:
        return "low"
    if count <= max_medium:
        return "medium"
    return "high"


def _grade_from_dpd(count: int, medium_threshold: int, high_threshold: int) -> str:
    if count >= high_threshold:
        return "high"
    if count >= medium_threshold:
        return "medium"
    return "low"


def run_bureau(payload: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    bureau_config = (config.get("thresholds") or {}).get("bureau")
    if not bureau_config:
        error = ErrorItem(
            code="missing_config",
            message="thresholds.bureau not found in config",
            where="config.thresholds.bureau",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="bureau",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Required config missing: thresholds.bureau"],
            evidence=mask_sensitive({"bureau": payload}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    bureau_data = payload.get("raw", payload)
    normalized = payload.get("normalized", {})

    window_days = int(bureau_config.get("enquiry_desperation_window_days", 30))
    max_low = int(bureau_config.get("max_enquiries_low_risk", 0))
    max_medium = int(bureau_config.get("max_enquiries_medium_risk", 0))
    dpd_bad_threshold = int(bureau_config.get("dpd_bad_threshold", 0))
    dpd_count_bad_medium = int(bureau_config.get("dpd_count_bad_medium", 0))
    dpd_count_bad_high = int(bureau_config.get("dpd_count_bad_high", 0))

    enquiry_count = extract_enquiry_count({**bureau_data, **normalized}, window_days)
    dpd_values = extract_dpd_values({**bureau_data, **normalized})

    missing_data: List[str] = []
    if enquiry_count is None:
        missing_data.append("bureau.enquiry_count")
    if not dpd_values:
        missing_data.append("bureau.dpd_values")

    bad_dpd_count = sum(1 for value in dpd_values if value >= dpd_bad_threshold) if dpd_values else 0
    worst_dpd = max(dpd_values) if dpd_values else 0
    on_time_ratio = None
    if dpd_values:
        on_time_ratio = sum(1 for value in dpd_values if value == 0) / len(dpd_values)

    grades: List[str] = []
    if enquiry_count is not None:
        grades.append(_grade_from_enquiries(enquiry_count, max_low, max_medium))
    if dpd_values:
        grades.append(_grade_from_dpd(bad_dpd_count, dpd_count_bad_medium, dpd_count_bad_high))

    if grades:
        bureau_risk_grade = "high" if "high" in grades else "medium" if "medium" in grades else "low"
    else:
        bureau_risk_grade = "medium"

    desperate_flag = False
    if enquiry_count is not None:
        desperate_flag = enquiry_count > max_medium

    calculations = {
        "enquiry_count": enquiry_count,
        "enquiry_window_days": window_days,
        "enquiry_grade": grades[0] if enquiry_count is not None else None,
        "dpd_bad_threshold": dpd_bad_threshold,
        "bad_dpd_count": bad_dpd_count,
        "dpd_grade": grades[-1] if dpd_values else None,
    }

    rationale_summary = [
        f"enquiry_count={enquiry_count} over {window_days} days (max_low={max_low}, max_medium={max_medium})",
        f"bad_dpd_count={bad_dpd_count} with dpd_bad_threshold={dpd_bad_threshold} (medium={dpd_count_bad_medium}, high={dpd_count_bad_high})",
    ]
    if missing_data:
        rationale_summary.append(f"Missing data: {', '.join(missing_data)}")

    if not missing_data and llm_enabled(config, "bureau"):
        return run_llm_agent("bureau", mask_sensitive(payload), config, prompts)

    output_payload = {
        "bureau_risk_grade": bureau_risk_grade,
        "enquiry_summary": {
            "window_days": window_days,
            "enquiry_count": enquiry_count,
            "desperate_flag": desperate_flag,
        },
        "repayment_summary": {
            "bad_dpd_count": bad_dpd_count,
            "worst_dpd": worst_dpd,
            "on_time_ratio": on_time_ratio,
        },
    }

    result = AgentResultBase(
        agent_name="bureau",
        status="insufficient_data" if missing_data else "ok",
        errors=[],
        missing_data=missing_data,
        rationale_summary=rationale_summary,
        evidence=mask_sensitive({"bureau": payload}),
        calculations=calculations,
        confidence=0.9 if not missing_data else 0.4,
        output=output_payload,
    )
    return result.model_dump(mode="json")
