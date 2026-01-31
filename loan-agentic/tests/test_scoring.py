from agents.risk_assessment import compute_risk_score


def test_compute_risk_score():
    assert compute_risk_score(650, 650) == 0.0
    assert compute_risk_score(0, 650) == 1.0
