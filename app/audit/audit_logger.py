"""
Audit Logging Service.
Records every workflow event as an immutable audit trail.
"""

import logging
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.database import AuditLog, WorkflowInstance

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Creates immutable audit log entries for every workflow event.
    Provides full decision traceability.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        workflow_id: str,
        workflow_type: str,
        event_type: str,
        message: str,
        step_name: Optional[str] = None,
        event_data: Optional[dict] = None,
        rule_name: Optional[str] = None,
        rule_result: Optional[bool] = None,
        rule_details: Optional[dict] = None,
        duration_ms: Optional[int] = None,
        severity: str = "INFO",
    ) -> AuditLog:
        """Create an audit log entry."""
        entry = AuditLog(
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            event_type=event_type,
            step_name=step_name,
            event_data=event_data,
            rule_name=rule_name,
            rule_result=rule_result,
            rule_details=rule_details,
            duration_ms=duration_ms,
            severity=severity,
            message=message,
        )
        self.db.add(entry)
        await self.db.flush()

        log_method = logger.error if severity == "ERROR" else logger.info
        log_method(
            f"📝 AUDIT | {workflow_id[:8]}... | {event_type} | "
            f"{step_name or '-'} | {message}"
        )
        return entry

    async def get_audit_trail(self, workflow_id: str) -> dict[str, Any]:
        """Get the complete audit trail with traceability summary."""
        # Get workflow instance
        result = await self.db.execute(
            select(WorkflowInstance).where(WorkflowInstance.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        # Get audit events
        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.workflow_id == workflow_id)
            .order_by(AuditLog.created_at.asc())
        )
        events = result.scalars().all()

        if not workflow:
            return {"error": "Workflow not found"}

        # Build traceability summary
        summary = self._build_traceability_summary(workflow, events)

        return {
            "workflow_id": workflow_id,
            "workflow_type": workflow.workflow_type,
            "workflow_status": workflow.status,
            "decision": workflow.decision,
            "total_events": len(events),
            "events": [e.to_dict() for e in events],
            "traceability_summary": summary,
        }

    def _build_traceability_summary(
        self, workflow: WorkflowInstance, events: list[AuditLog]
    ) -> dict[str, Any]:
        """Build a human-readable decision traceability summary."""
        steps_timeline = []
        rules_evaluated = []
        external_calls = []
        errors = []

        for event in events:
            if event.event_type == "step_completed":
                steps_timeline.append({
                    "step": event.step_name,
                    "duration_ms": event.duration_ms,
                    "result": event.event_data.get("result") if event.event_data else None,
                })
            elif event.event_type == "rule_evaluated":
                rules_evaluated.append({
                    "rule": event.rule_name,
                    "passed": event.rule_result,
                    "details": event.rule_details,
                })
            elif event.event_type == "external_call":
                external_calls.append({
                    "service": event.step_name,
                    "success": event.event_data.get("success") if event.event_data else None,
                    "latency_ms": event.duration_ms,
                })
            elif event.severity == "ERROR":
                errors.append({
                    "step": event.step_name,
                    "message": event.message,
                })

        return {
            "input_summary": {
                "workflow_type": workflow.workflow_type,
                "key_fields": list(workflow.input_data.keys()) if workflow.input_data else [],
            },
            "execution_path": workflow.steps_completed or [],
            "steps_timeline": steps_timeline,
            "rules_evaluated": rules_evaluated,
            "rules_passed": sum(1 for r in rules_evaluated if r["passed"]),
            "rules_failed": sum(1 for r in rules_evaluated if not r["passed"]),
            "external_calls": external_calls,
            "retry_count": workflow.retry_count,
            "errors": errors,
            "final_decision": {
                "decision": workflow.decision,
                "reason": workflow.decision_reason,
                "rules_triggered": workflow.rules_triggered or [],
            },
        }
