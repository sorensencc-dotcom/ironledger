"""Pydantic schemas with strict minor-unit integer conventions for IronLedger Web API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ironledger.conventions import (
    ConventionError,
    currency_scale,
    validate_account_name,
    validate_amount_minor_units,
    validate_currency,
)


class StrictBaseModel(BaseModel):
    """Base model that disallows extra attributes and enforces strict types."""

    model_config = ConfigDict(extra="forbid", strict=True)


class PostingSchema(BaseModel):
    """Posting with strict integer minor-unit amount enforcement."""

    model_config = ConfigDict(extra="forbid")

    account: str
    currency: str
    minor_units: int
    scale: int
    role: Optional[str] = None

    @field_validator("minor_units", mode="before")
    @classmethod
    def validate_minor_units_type(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("minor_units must be an int, not float or bool")
        return v

    @field_validator("scale", mode="before")
    @classmethod
    def validate_scale_type(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("scale must be an int, not float or bool")
        return v

    @model_validator(mode="after")
    def validate_conventions(self) -> PostingSchema:
        try:
            validate_account_name(self.account)
            validate_currency(self.currency)
            validate_amount_minor_units(self.minor_units, self.currency, self.scale)
        except ConventionError as exc:
            raise ValueError(str(exc)) from exc
        return self


class StagedTransactionResponse(BaseModel):
    """Staged transaction returned in review and workbench registers."""

    model_config = ConfigDict(extra="ignore")

    staged_id: str
    source_document_id: str
    source_record_id: str
    date: str
    payee: str
    narration: str
    currency: str
    minor_units: int
    scale: int
    postings: List[PostingSchema] = Field(default_factory=list)
    status: str = "pending"
    confidence_score: Optional[float] = None
    matched_rule_id: Optional[str] = None
    notes: Optional[str] = None
    external_id: Optional[str] = None
    raw_payload_ref: Optional[str] = None
    provenance: Optional[str] = None

    @field_validator("minor_units", mode="before")
    @classmethod
    def validate_minor_units_type(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("minor_units must be an int, not float or bool")
        return v

    @field_validator("scale", mode="before")
    @classmethod
    def validate_scale_type(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("scale must be an int, not float or bool")
        return v


class AttachCandidateSchema(BaseModel):
    staged_id: str
    payee: str
    date: str
    minor_units: int
    category_account: Optional[str] = None


class AttachProposalResponse(BaseModel):
    proposal_id: str
    kind: str
    status: str
    pdf_description: str
    date: str
    currency: str
    minor_units: int
    scale: int
    source_document_id: str
    source_record_id: str
    candidates: List[AttachCandidateSchema]
    item_type: str = "attach"


class AttachConfirmRequest(BaseModel):
    chosen_staged_id: str


class StagedSplitRequest(BaseModel):
    """Request to split a staged transaction across multiple postings."""

    model_config = ConfigDict(extra="forbid")

    postings: List[PostingSchema]


class StagedApproveRequest(BaseModel):
    """Optional payload when approving a staged transaction."""

    model_config = ConfigDict(extra="forbid")

    target_account: Optional[str] = None
    notes: Optional[str] = None


class RuleResponse(BaseModel):
    """Rule entity for management and editor."""

    model_config = ConfigDict(extra="ignore")

    rule_id: str
    payee_pattern: str
    narration_pattern: Optional[str] = None
    target_account: str
    priority: int = 100
    active: bool = True


class RuleCreateRequest(BaseModel):
    """Payload to create or update an auto-categorization rule."""

    model_config = ConfigDict(extra="forbid")

    payee_pattern: str
    narration_pattern: Optional[str] = None
    target_account: str
    priority: int = 100
    active: bool = True

    @field_validator("target_account")
    @classmethod
    def validate_account(cls, v: str) -> str:
        try:
            return validate_account_name(v)
        except ConventionError as exc:
            raise ValueError(str(exc)) from exc


class RuleCandidateRequest(BaseModel):
    """Payload to generate a rule candidate from a staged transaction."""

    model_config = ConfigDict(extra="forbid")

    staged_id: str
    pattern_type: str = "exact"
    payee: Optional[str] = None


class RuleCandidateResponse(BaseModel):
    """Suggested rule candidate with retroactive hit estimation."""

    model_config = ConfigDict(extra="ignore")

    suggested_pattern: str
    target_account: str
    confidence: float
    retroactive_matches: int


class RuleDriftResponse(BaseModel):
    """Hit Confidence Trend (HCT) and drift status for a rule."""

    model_config = ConfigDict(extra="ignore")

    rule_id: str
    rule_name: str
    total_hits: int
    recent_hits: int
    override_count: int
    override_rate: float
    confidence_trend: float
    drift_status: str  # 'healthy' | 'warning' | 'stale'


class BalanceItemResponse(BaseModel):
    """Account balance item from projection."""

    model_config = ConfigDict(extra="ignore")

    account: str
    currency: str
    minor_units: int
    scale: int
    formatted_amount: str


class FreshnessResponse(BaseModel):
    """Freshness latency indicators for projection and ledger."""

    model_config = ConfigDict(extra="ignore")

    is_fresh: bool
    latency_seconds: float
    last_compile_timestamp: Optional[str] = None
    last_projection_timestamp: Optional[str] = None
    status: str  # 'fresh' | 'stale' | 'critical'


class SafeModeStatusResponse(BaseModel):
    """Safe mode system state and token status."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool
    token_required: bool
    token_active: bool
    token_expires_at: Optional[str] = None


class CompileRequest(BaseModel):
    """Request to compile approved transactions or simulate."""

    model_config = ConfigDict(extra="forbid")

    ledger_dir: Optional[str] = None
    dry_run: bool = False
    rebuild_projection: bool = True
    safe_mode_token: Optional[str] = None


class CompileResponse(BaseModel):
    """Result of compile or dry-run simulation."""

    model_config = ConfigDict(extra="ignore")

    success: bool
    message: str
    run_id: Optional[str] = None
    dry_run: bool = False
    entries_compiled: int = 0
    postings_compiled: int = 0
    diff_preview: Optional[str] = None


class TaxTermSummary(BaseModel):
    realized_gain_minor: int
    realized_gain_display: str
    proceeds_minor: int
    proceeds_display: str
    cost_basis_minor: int
    cost_basis_display: str


class CapitalGainsSummaryResponse(BaseModel):
    ledger_id: str
    functional_currency: str
    tax_year: Optional[int]
    term_filter: Literal["ALL", "SHORT_TERM", "LONG_TERM"]
    total_realized_gain_minor: int
    total_realized_gain_display: str
    total_proceeds_minor: int
    total_proceeds_display: str
    total_cost_basis_minor: int
    total_cost_basis_display: str
    short_term: TaxTermSummary
    long_term: TaxTermSummary
    disposal_count: int


class OpenTaxLotResponse(BaseModel):
    lot_key: str
    account: str
    commodity: str
    acquisition_date: str
    remaining_units_minor: int
    unit_scale: int
    quantity_display: str
    functional_currency: str
    unit_cost_numerator: int
    unit_cost_denominator: int
    current_basis_minor: int
    current_basis_display: str
    market_price_numerator: Optional[int]
    market_price_denominator: Optional[int]
    market_value_minor: Optional[int]
    market_value_display: Optional[str]
    unrealized_gain_loss_minor: Optional[int]
    unrealized_gain_loss_display: Optional[str]
    lot_label: Optional[str]


class OpenTaxLotsResponse(BaseModel):
    lots: List[OpenTaxLotResponse]
    count: int


class UnrealizedPositionResponse(BaseModel):
    commodity: str
    total_units_minor: int
    unit_scale: int
    quantity_display: str
    functional_currency: str
    cost_basis_minor: int
    cost_basis_display: str
    latest_price_numerator: int
    latest_price_denominator: int
    latest_price_display: str
    market_value_minor: int
    market_value_display: str
    unrealized_gain_minor: int
    unrealized_gain_display: str


class UnrealizedGainsResponse(BaseModel):
    ledger_id: str
    functional_currency: str
    total_cost_basis_minor: int
    total_cost_basis_display: str
    total_market_value_minor: int
    total_market_value_display: str
    total_unrealized_gain_minor: int
    total_unrealized_gain_display: str
    positions: List[UnrealizedPositionResponse]


class DisposalPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_id: str = "default"
    commodity: str = Field(min_length=1)
    quantity: Decimal | str
    proceeds_rate: Decimal | str
    strategy: Literal["FIFO", "LIFO", "HIFO"] = "FIFO"
    disposal_date: Optional[str] = None
    account: Optional[str] = None


class DisposalAllocationResponse(BaseModel):
    open_lot_key: str
    acquisition_date: str
    disposal_date: str
    units_disposed_minor: int
    units_disposed_display: str
    holding_period_days: int
    term_classification: Literal["SHORT_TERM", "LONG_TERM"]
    functional_proceeds_minor: int
    functional_proceeds_display: str
    functional_cost_basis_minor: int
    functional_cost_basis_display: str
    functional_realized_gain_minor: int
    functional_realized_gain_display: str


class RemainingTaxLotResponse(BaseModel):
    lot_key: str
    account: str
    commodity: str
    acquisition_date: str
    remaining_units_minor: int
    remaining_units_display: str
    remaining_basis_minor: int
    remaining_basis_display: str


class DisposalPreviewResponse(BaseModel):
    simulation_status: Literal["SUCCESS"]
    ledger_id: str
    commodity: str
    strategy: Literal["FIFO", "LIFO", "HIFO"]
    disposal_date: str
    units_disposed_minor: int
    units_disposed_display: str
    total_proceeds_minor: int
    total_proceeds_display: str
    total_cost_basis_minor: int
    total_cost_basis_display: str
    total_realized_gain_minor: int
    total_realized_gain_display: str
    short_term_gain_minor: int
    short_term_gain_display: str
    long_term_gain_minor: int
    long_term_gain_display: str
    allocations: List[DisposalAllocationResponse]
    remaining_lots: List[RemainingTaxLotResponse]

