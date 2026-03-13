"""
Pydantic schemas for API request/response validation.
"""

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ProcessRequestInput(BaseModel):
    """Input schema for triggering a workflow."""
    workflow_type: str = Field(
        ...,
        description="Name of the workflow to execute (must match a config)",
        examples=["application_approval", "claim_processing"]
    )
    idempotency_key: Optional[str] = Field(
        None,
        description="Unique key to prevent duplicate processing",
        examples=["req-abc-123"]
    )
    payload: dict[str, Any] = Field(
        ...,
        description="Input data for the workflow",
        examples=[{"applicant_name": "Jane Doe", "salary": 75000, "credit_score": 720}]
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "workflow_type": "application_approval",
                    "idempotency_key": "app-2024-001",
                    "payload": {
                        "applicant_name": "Jane Doe",
                        "salary": 75000,
                        "credit_score": 720,
                        "employment_years": 3,
                        "loan_amount": 200000,
                        "document_submitted": True
                    }
                }
            ]
        }
    }


class WorkflowStatusResponse(BaseModel):
    """Response schema for workflow status queries."""
    id: str
    workflow_type: str
    status: str
    current_step: Optional[str]
    steps_completed: list[str]
    decision: Optional[str]
    decision_reason: Optional[str]
    rules_triggered: list[dict]
    retry_count: int
    last_error: Optional[str]
    input_data: dict[str, Any]
    output_data: Optional[dict[str, Any]]
    created_at: str
    updated_at: Optional[str]
    completed_at: Optional[str]


class ProcessRequestResponse(BaseModel):
    """Response schema for process-request endpoint."""
    workflow_id: str
    status: str
    message: str
    idempotent: bool = False
    result: Optional[dict[str, Any]] = None


class AuditEventResponse(BaseModel):
    """Single audit event."""
    id: str
    workflow_id: str
    workflow_type: str
    event_type: str
    step_name: Optional[str]
    event_data: Optional[dict]
    rule_name: Optional[str]
    rule_result: Optional[bool]
    rule_details: Optional[dict]
    duration_ms: Optional[int]
    severity: str
    message: Optional[str]
    created_at: str


class AuditLogResponse(BaseModel):
    """Full audit trail for a workflow."""
    workflow_id: str
    workflow_type: str
    workflow_status: str
    decision: Optional[str]
    total_events: int
    events: list[AuditEventResponse]
    
    # Decision traceability summary
    traceability_summary: dict[str, Any]


class WorkflowListResponse(BaseModel):
    """List of available workflow types."""
    workflows: list[dict[str, Any]]
    total: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    database: str
    loaded_workflows: list[str]
    timestamp: str
