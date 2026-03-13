"""
Database models for workflow state, audit logs, and idempotency keys.
Uses SQLAlchemy with SQLite (easily switchable to PostgreSQL).
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, Integer, Text, Boolean, Index
from sqlalchemy.orm import DeclarativeBase


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class WorkflowInstance(Base):
    """Represents a running or completed workflow instance."""
    __tablename__ = "workflow_instances"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    idempotency_key = Column(String(255), unique=True, nullable=True, index=True)
    workflow_type = Column(String(100), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")
    # pending | running | completed | failed | rejected
    
    current_step = Column(String(100), nullable=True)
    steps_completed = Column(JSON, default=list)
    input_data = Column(JSON, nullable=False)
    output_data = Column(JSON, nullable=True)
    
    # Decision tracking
    decision = Column(String(50), nullable=True)  # approved | rejected | pending
    decision_reason = Column(Text, nullable=True)
    rules_triggered = Column(JSON, default=list)
    
    # Retry tracking
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    last_error = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_workflow_status", "status"),
        Index("idx_workflow_type_status", "workflow_type", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "idempotency_key": self.idempotency_key,
            "workflow_type": self.workflow_type,
            "status": self.status,
            "current_step": self.current_step,
            "steps_completed": self.steps_completed or [],
            "input_data": self.input_data,
            "output_data": self.output_data,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "rules_triggered": self.rules_triggered or [],
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class AuditLog(Base):
    """Immutable audit trail for every workflow event."""
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workflow_id = Column(String(36), nullable=False, index=True)
    workflow_type = Column(String(100), nullable=False)
    
    event_type = Column(String(100), nullable=False)
    # workflow_started | step_started | step_completed | step_failed |
    # rule_evaluated | external_call | decision_made | workflow_completed | workflow_failed
    
    step_name = Column(String(100), nullable=True)
    event_data = Column(JSON, nullable=True)
    
    # Rule evaluation details
    rule_name = Column(String(100), nullable=True)
    rule_result = Column(Boolean, nullable=True)
    rule_details = Column(JSON, nullable=True)
    
    # Timing
    duration_ms = Column(Integer, nullable=True)
    
    severity = Column(String(20), default="INFO")  # INFO | WARN | ERROR
    message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_audit_workflow_id", "workflow_id"),
        Index("idx_audit_event_type", "event_type"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "workflow_type": self.workflow_type,
            "event_type": self.event_type,
            "step_name": self.step_name,
            "event_data": self.event_data,
            "rule_name": self.rule_name,
            "rule_result": self.rule_result,
            "rule_details": self.rule_details,
            "duration_ms": self.duration_ms,
            "severity": self.severity,
            "message": self.message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class IdempotencyRecord(Base):
    """Tracks processed idempotency keys to prevent duplicate processing."""
    __tablename__ = "idempotency_records"

    key = Column(String(255), primary_key=True)
    workflow_id = Column(String(36), nullable=False)
    workflow_type = Column(String(100), nullable=False)
    response_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "workflow_id": self.workflow_id,
            "workflow_type": self.workflow_type,
            "response_data": self.response_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
