from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

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


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _daily_average(balances_by_date: Dict[str, List[float]]) -> Optional[float]:
    if not balances_by_date:
        return None
    daily_means = [sum(vals) / len(vals) for vals in balances_by_date.values() if vals]
    return _mean(daily_means)


def _detect_salary(transactions: List[Dict[str, Any]], keywords: List[str]) -> Tuple[Optional[float], int]:
    matches: List[float] = []
    keywords_lower = [kw.lower() for kw in keywords]
    for txn in transactions:
        narration = str(txn.get("narration", "")).lower()
        amount = txn.get("amount")
        if not isinstance(amount, (int, float)):
            continue
        if amount <= 0:
            continue
        if any(keyword in narration for keyword in keywords_lower):
            matches.append(float(amount))
    if not matches:
        return None, 0
    return float(median(matches)), len(matches)


def _detect_suspicious(transactions: List[Dict[str, Any]], keywords: List[str]) -> Tuple[int, float, float]:
    keywords_lower = [kw.lower() for kw in keywords]
    flagged = 0
    suspicious_debit = 0.0
    total_debit = 0.0

    for txn in transactions:
        narration = str(txn.get("narration", "")).lower()
        amount = txn.get("amount")
        if isinstance(amount, (int, float)) and amount < 0:
            total_debit += abs(float(amount))
        is_suspicious = any(keyword in narration for keyword in keywords_lower)
        if is_suspicious:
            flagged += 1
            if isinstance(amount, (int, float)) and amount < 0:
                suspicious_debit += abs(float(amount))

    ratio = suspicious_debit / total_debit if total_debit > 0 else 0.0
    return flagged, suspicious_debit, ratio


def run_bank_statement(payload: List[Dict[str, Any]], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    thresholds = (config.get("thresholds") or {}).get("bank")
    suspicious_cfg = config.get("suspicious_keywords") or {}

    if not thresholds:
        error = ErrorItem(
            code="missing_config",
            message="thresholds.bank not found in config",
            where="config.thresholds.bank",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="bank_statement",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Required config missing: thresholds.bank"],
            evidence=mask_sensitive({"transactions": payload}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    transactions = payload if isinstance(payload, list) else []
    txn_count = len(transactions)

    balances: List[float] = []
    balances_by_date: Dict[str, List[float]] = {}
    date_parse_ok = True

    for txn in transactions:
        balance = txn.get("balance")
        if isinstance(balance, (int, float)):
            balances.append(float(balance))
        date_value = txn.get("date")
        parsed = _parse_date(str(date_value)) if date_value else None
        if parsed:
            key = parsed.date().isoformat()
            if isinstance(balance, (int, float)):
                balances_by_date.setdefault(key, []).append(float(balance))
        else:
            if date_value:
                date_parse_ok = False

    has_balance_field = len(balances) > 0
    avg_balance = _daily_average(balances_by_date) if balances_by_date else _mean(balances)

    salary_keywords = thresholds.get("salary_keyword_list", [])
    salary_estimate, salary_match_count = _detect_salary(transactions, salary_keywords)

    suspicious_keywords = suspicious_cfg.get("keywords", [])
    flagged_count, suspicious_total, suspicious_ratio = _detect_suspicious(transactions, suspicious_keywords)

    ratio_medium = float(thresholds.get("suspicious_spend_monthly_ratio_medium", 0.0))
    ratio_high = float(thresholds.get("suspicious_spend_monthly_ratio_high", 1.0))

    if suspicious_ratio >= ratio_high:
        suspicious_grade = "high"
    elif suspicious_ratio >= ratio_medium:
        suspicious_grade = "medium"
    else:
        suspicious_grade = "low"

    missing_data: List[str] = []
    if avg_balance is None:
        missing_data.append("bank.avg_balance")
    if salary_estimate is None:
        missing_data.append("bank.salary_estimate")

    min_txns = int(thresholds.get("min_txns_for_confidence", 0))
    low_txn_warning = txn_count < min_txns

    rationale_summary = [
        f"avg_balance={avg_balance} computed from {txn_count} transactions",
        f"salary_matches={salary_match_count} using salary keywords",
        f"suspicious_ratio={suspicious_ratio:.2f} (medium={ratio_medium}, high={ratio_high})",
    ]
    if low_txn_warning:
        rationale_summary.append(f"Transaction count {txn_count} below min_txns_for_confidence={min_txns}")
    if missing_data:
        rationale_summary.append(f"Missing data: {', '.join(missing_data)}")

    confidence = 0.9
    if low_txn_warning:
        confidence = 0.6
    if missing_data:
        confidence = 0.4

    output_payload = {
        "avg_balance": avg_balance,
        "salary_estimate": salary_estimate,
        "suspicious": {
            "flagged_txns_count": flagged_count,
            "total_suspicious_debit": suspicious_total,
            "suspicious_ratio": suspicious_ratio,
            "suspicious_grade": suspicious_grade,
        },
        "data_quality": {
            "txn_count": txn_count,
            "has_balance_field": has_balance_field,
            "date_parse_ok": date_parse_ok,
        },
    }

    result = AgentResultBase(
        agent_name="bank_statement",
        status="insufficient_data" if missing_data else "ok",
        errors=[],
        missing_data=missing_data,
        rationale_summary=rationale_summary,
        evidence=mask_sensitive({"transactions_sample": transactions[:5]}),
        calculations={
            "salary_match_count": salary_match_count,
            "min_txns_for_confidence": min_txns,
        },
        confidence=confidence,
        output=output_payload,
    )
    rule_result = result.model_dump(mode="json")

    if llm_enabled(config, "bank_statement"):
        llm_result = run_llm_agent("bank_statement", mask_sensitive(payload), config, prompts)
        if isinstance(llm_result, dict) and llm_result.get("status") == "ok":
            return llm_result
    return rule_result
