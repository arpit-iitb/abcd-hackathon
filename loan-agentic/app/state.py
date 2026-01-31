from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LeadInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: Optional[str] = None
    application_id: Optional[str] = None
    name: str
    city: str
    tier: str
    loan_purpose: str
    requested_amount: float = Field(gt=0)
    product_type: str
    employment_type: str
    phone: Optional[str] = None
    email: Optional[str] = None
    aadhaar_last4: Optional[str] = Field(default=None, min_length=4, max_length=4)
    pan_masked: Optional[str] = None
    declared_income: Optional[float] = Field(default=None, gt=0)


class BureauNormalized(BaseModel):
    model_config = ConfigDict(extra="allow")

    score: Optional[int] = None
    delinquencies: Optional[int] = None


class BureauReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    raw: Dict[str, Any] = Field(default_factory=dict)
    normalized: Optional[BureauNormalized] = None


class BankTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    narration: str
    amount: float
    balance: float


class DocumentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parsed_json: Optional[Dict[str, Any]] = None
    image_base64: Optional[str] = None
    image_path: Optional[str] = None

    @model_validator(mode="after")
    def validate_payload(self) -> "DocumentPayload":
        if not self.parsed_json and not self.image_base64 and not self.image_path:
            raise ValueError("document requires parsed_json or image_base64 or image_path")
        return self


class Documents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aadhaar_doc: DocumentPayload
    pan_doc: DocumentPayload
    payslip_doc: DocumentPayload
    selfie_doc: DocumentPayload


class LoanApplicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead: LeadInfo
    bureau_report: BureauReport
    bank_statement: List[BankTransaction]
    documents: Documents


class ErrorItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    where: str
    severity: Literal["warning", "fatal"]


class AgentResultBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    status: Literal["ok", "insufficient_data", "error"]
    errors: List[ErrorItem] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    rationale_summary: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    calculations: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    output: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class RecommendedTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sanctioned_amount: Optional[float] = None
    roi: Optional[float] = None


class HumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool
    reasons: List[str] = Field(default_factory=list)
    missing_info: List[str] = Field(default_factory=list)
    recommended_action: Literal["approve", "reject", "request_more_info"]
    recommended_terms: Optional[RecommendedTerms] = None


class FinalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected", "human_review_required"]
    sanctioned_amount: Optional[float] = None
    roi: Optional[float] = None
    reasons: List[str] = Field(default_factory=list)
    human_review: Optional[HumanReview] = None


class TraceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    started_at: str
    ended_at: str
    duration_ms: float
    input_snapshot: Dict[str, Any]
    output_snapshot: Dict[str, Any]
    prompt_meta: Dict[str, Any] = Field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class RunMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    thread_id: str
    started_at: str
    completed_at: Optional[str] = None
    timestamps: Dict[str, str] = Field(default_factory=dict)


class LoanApplicationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: LoanApplicationInput
    config: Dict[str, Any] = Field(default_factory=dict)
    results: Dict[str, AgentResultBase] = Field(default_factory=dict)
    derived: Dict[str, Any] = Field(default_factory=dict)
    decision: Optional[FinalDecision] = None
    run_meta: RunMeta
    logs: Optional[List[str]] = None
    review_packet: Optional[Dict[str, Any]] = None
    traces: Dict[str, TraceItem] = Field(default_factory=dict)


def safe_result_ok(
    agent_name: str,
    output: Dict[str, Any],
    evidence: Dict[str, Any],
    calculations: Dict[str, Any],
    rationale_summary: List[str],
    confidence: float,
) -> AgentResultBase:
    return AgentResultBase(
        agent_name=agent_name,
        status="ok",
        errors=[],
        missing_data=[],
        rationale_summary=rationale_summary,
        evidence=evidence,
        calculations=calculations,
        confidence=confidence,
        output=output,
    )


def safe_result_insufficient(
    agent_name: str,
    missing_data: List[str],
    evidence: Dict[str, Any],
    calculations: Dict[str, Any],
    rationale_summary: List[str],
    confidence: float,
) -> AgentResultBase:
    return AgentResultBase(
        agent_name=agent_name,
        status="insufficient_data",
        errors=[],
        missing_data=missing_data,
        rationale_summary=rationale_summary,
        evidence=evidence,
        calculations=calculations,
        confidence=confidence,
        output={},
    )


def safe_result_error(
    agent_name: str,
    errors: List[ErrorItem],
    evidence: Dict[str, Any],
    calculations: Dict[str, Any],
    rationale_summary: List[str],
    confidence: float,
) -> AgentResultBase:
    return AgentResultBase(
        agent_name=agent_name,
        status="error",
        errors=errors,
        missing_data=[],
        rationale_summary=rationale_summary,
        evidence=evidence,
        calculations=calculations,
        confidence=confidence,
        output={},
    )
