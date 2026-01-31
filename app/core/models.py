from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    field: str = ""


class AgentOutputBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    status: Literal["ok", "insufficient_data", "error"]
    rationale_summary: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    calculations: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    errors: List[ErrorDetail] = Field(default_factory=list)


class LeadInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    first_name: str
    last_name: str
    phone: str
    email: str
    requested_amount: float
    tenure_months: int


class IdInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    aadhaar: str
    pan: str
    full_name: str


class BureauInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    score: int
    delinquencies: int


class BankInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    avg_monthly_balance: float
    monthly_income: float
    monthly_obligations: float


class PayslipInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    net_salary: float
    employer_name: str
    employment_tenure_months: int


class ApplicationInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    lead: LeadInput
    id: IdInput
    bureau: BureauInput
    bank: BankInput
    payslip: PayslipInput


class LeadSourcingOutput(AgentOutputBase):
    model_config = ConfigDict(extra="forbid")

    normalized_lead: Dict[str, Any] = Field(default_factory=dict)


class SalesAgentOutput(AgentOutputBase):
    model_config = ConfigDict(extra="forbid")

    route: Literal["proceed", "stop"] = "proceed"


class FraudOutput(AgentOutputBase):
    model_config = ConfigDict(extra="forbid")

    fraud_score: float = 0.0
    name_mismatch: float = 0.0
    address_mismatch: float = 0.0


class RiskOutput(AgentOutputBase):
    model_config = ConfigDict(extra="forbid")

    dti: float = 0.0
    foir: float = 0.0
    approval_score: float = 0.0
    risk_score: float = 1.0


class ApprovalOutput(AgentOutputBase):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "decline", "insufficient_data"] = "insufficient_data"
    approved_amount: Optional[float] = None
