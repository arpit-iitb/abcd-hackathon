import os
import pytest


AGENTS = [
    "lead_sourcing",
    "bureau",
    "bank_statement",
    "id_verification",
    "payslip",
    "fraud",
    "risk_assessment",
    "approval",
]


@pytest.fixture(autouse=True, scope="session")
def _disable_llm_for_tests():
    os.environ["LOAN_AGENTIC__llm__default_use_llm"] = "false"
    for agent in AGENTS:
        os.environ[f"LOAN_AGENTIC__llm__agents__{agent}"] = "false"
    yield
