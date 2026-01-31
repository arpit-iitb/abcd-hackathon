from typing import Dict


def compute_emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    if tenure_months <= 0 or annual_rate <= 0:
        return 0.0
    monthly_rate = annual_rate / 12.0
    factor = (1 + monthly_rate) ** tenure_months
    if factor == 1:
        return 0.0
    return principal * monthly_rate * factor / (factor - 1)


def compute_dti(monthly_obligations: float, monthly_income: float) -> float:
    if monthly_income <= 0:
        return 1.0
    return monthly_obligations / monthly_income


def compute_foir(monthly_obligations: float, emi: float, monthly_income: float) -> float:
    if monthly_income <= 0:
        return 1.0
    return (monthly_obligations + emi) / monthly_income


def normalized(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return min(value / max_value, 1.0)


def weighted_score(metrics: Dict[str, float], weights: Dict[str, float]) -> float:
    score = 0.0
    for key, value in metrics.items():
        score += value * weights.get(key, 0.0)
    return score
