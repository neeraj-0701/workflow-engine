"""
Core Workflow Engine.

Orchestrates multi-step workflow execution with:
- Config-driven step execution
- Rule evaluation at each step
- External service calls with retry
- State persistence
- Comprehensive audit logging
- Failure handling and recovery
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.database import WorkflowInstance, IdempotencyRecord
from app.services.config_loader import ConfigLoader
from app.services.external_service import ExternalServiceSimulator
from app.rules.rule_engine import RuleEngine
from app.audit.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    The core engine that processes workflow requests.
    
    Execution flow:
    1. Idempotency check → 2. Load config → 3. Create instance →
    4. Execute steps → 5. Evaluate rules → 6. Call externals →
    7. Make decision → 8. Persist state → 9. Return result
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.config_loader = ConfigLoader()
        self.rule_engine = RuleEngine()
        self.external_sim = ExternalServiceSimulator()
        self.audit = AuditLogger(db)

    # ─────────────────────────────────────────────────────────────
    # PUBLIC: Process a new workflow request
    # ─────────────────────────────────────────────────────────────

    async def process_request(
        self,
        workflow_type: str,
        payload: dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Main entry point. Process a workflow request end-to-end.
        Returns a result dict with workflow_id, status, decision.
        """

        # ── 1. IDEMPOTENCY CHECK ──────────────────────────────────
        if idempotency_key:
            existing = await self._check_idempotency(idempotency_key)
            if existing:
                logger.info(f"♻️  Idempotent request detected: {idempotency_key}")
                return {**existing.response_data, "idempotent": True}

        # ── 2. LOAD WORKFLOW CONFIG ───────────────────────────────
        config = self.config_loader.get_workflow(workflow_type)
        if not config:
            raise ValueError(f"Unknown workflow type: '{workflow_type}'. "
                             f"Available: {list(self.config_loader.get_all().keys())}")

        # ── 3. CREATE WORKFLOW INSTANCE ───────────────────────────
        workflow_id = str(uuid.uuid4())
        max_retries = config.get("max_retries", 3)
        
        instance = WorkflowInstance(
            id=workflow_id,
            idempotency_key=idempotency_key,
            workflow_type=workflow_type,
            status="running",
            input_data=payload,
            steps_completed=[],
            rules_triggered=[],
            max_retries=max_retries,
        )
        self.db.add(instance)
        await self.db.flush()

        await self.audit.log(
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            event_type="workflow_started",
            message=f"Workflow '{workflow_type}' started",
            event_data={
                "payload_keys": list(payload.keys()),
                "idempotency_key": idempotency_key,
                "max_retries": max_retries,
            },
        )

        # ── 4. EXECUTE WORKFLOW ───────────────────────────────────
        try:
            result = await self._execute_workflow(instance, config, payload)
            
            # ── 5. STORE IDEMPOTENCY RECORD ───────────────────────
            if idempotency_key:
                await self._save_idempotency_record(
                    idempotency_key, workflow_id, workflow_type, result
                )

            await self.db.commit()
            return result

        except Exception as e:
            logger.error(f"Workflow {workflow_id} failed with unexpected error: {e}")
            instance.status = "failed"
            instance.last_error = str(e)
            instance.updated_at = datetime.utcnow()
            await self.audit.log(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                event_type="workflow_failed",
                message=f"Unexpected failure: {str(e)}",
                severity="ERROR",
            )
            await self.db.commit()
            raise

    # ─────────────────────────────────────────────────────────────
    # WORKFLOW EXECUTION
    # ─────────────────────────────────────────────────────────────

    async def _execute_workflow(
        self,
        instance: WorkflowInstance,
        config: dict,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute all steps in the workflow."""
        steps = config.get("steps", [])
        workflow_context = {**payload, "_workflow_id": instance.id}
        rules_triggered = []

        for step_config in steps:
            # Normalize step config
            if isinstance(step_config, str):
                step_config = {"name": step_config}

            step_name = step_config.get("name", "unknown_step")
            step_type = step_config.get("type", "process")

            logger.info(f"▶️  Step: {step_name} | workflow: {instance.id[:8]}...")
            instance.current_step = step_name
            instance.updated_at = datetime.utcnow()
            await self.db.flush()

            await self.audit.log(
                workflow_id=instance.id,
                workflow_type=instance.workflow_type,
                event_type="step_started",
                step_name=step_name,
                message=f"Starting step: {step_name}",
            )

            step_start = time.time()

            try:
                step_result = await self._execute_step(
                    step_name=step_name,
                    step_config=step_config,
                    step_type=step_type,
                    instance=instance,
                    context=workflow_context,
                    config=config,
                )

                duration_ms = int((time.time() - step_start) * 1000)

                # Merge step output into context for subsequent steps
                if isinstance(step_result, dict):
                    workflow_context.update(step_result.get("data", {}))
                    if step_result.get("rules_triggered"):
                        rules_triggered.extend(step_result["rules_triggered"])

                # Track completed steps
                steps_completed = instance.steps_completed or []
                steps_completed.append(step_name)
                instance.steps_completed = steps_completed

                await self.audit.log(
                    workflow_id=instance.id,
                    workflow_type=instance.workflow_type,
                    event_type="step_completed",
                    step_name=step_name,
                    message=f"Step '{step_name}' completed",
                    duration_ms=duration_ms,
                    event_data={"result": step_result.get("status", "ok")},
                )

                # Check for early termination (e.g., hard reject)
                if step_result.get("terminate"):
                    logger.info(f"⛔ Workflow terminated at step '{step_name}': "
                                f"{step_result.get('reason')}")
                    break

            except StepFailureException as e:
                duration_ms = int((time.time() - step_start) * 1000)
                logger.warning(f"Step '{step_name}' failed: {e}")
                
                await self.audit.log(
                    workflow_id=instance.id,
                    workflow_type=instance.workflow_type,
                    event_type="step_failed",
                    step_name=step_name,
                    message=str(e),
                    duration_ms=duration_ms,
                    severity="ERROR",
                )

                # Check if step is required
                if step_config.get("required", True):
                    instance.status = "failed"
                    instance.last_error = str(e)
                    instance.decision = "rejected"
                    instance.decision_reason = f"Step '{step_name}' failed: {str(e)}"
                    instance.updated_at = datetime.utcnow()
                    
                    await self.audit.log(
                        workflow_id=instance.id,
                        workflow_type=instance.workflow_type,
                        event_type="workflow_failed",
                        message=f"Workflow failed at required step '{step_name}'",
                        severity="ERROR",
                    )
                    break
                else:
                    logger.info(f"Step '{step_name}' is optional, continuing...")
                    steps_completed = instance.steps_completed or []
                    steps_completed.append(f"{step_name}:skipped")
                    instance.steps_completed = steps_completed

        # ── FINAL DECISION ─────────────────────────────────────────
        final_result = await self._make_final_decision(
            instance=instance,
            config=config,
            context=workflow_context,
            rules_triggered=rules_triggered,
        )

        return final_result

    async def _execute_step(
        self,
        step_name: str,
        step_config: dict,
        step_type: str,
        instance: WorkflowInstance,
        context: dict,
        config: dict,
    ) -> dict[str, Any]:
        """Dispatch a step to the appropriate handler."""

        if step_type == "validate":
            return await self._step_validate(step_name, step_config, context)

        elif step_type == "rule_check":
            return await self._step_rule_check(step_name, step_config, instance, context, config)

        elif step_type == "external_call":
            return await self._step_external_call(step_name, step_config, instance, context)

        elif step_type == "decision":
            return await self._step_decision(step_name, step_config, instance, context, config)

        elif step_type == "notification":
            return await self._step_notification(step_name, step_config, context)

        elif step_type == "process":
            return await self._step_process(step_name, step_config, context)

        else:
            # Default: process step
            return await self._step_process(step_name, step_config, context)

    # ─────────────────────────────────────────────────────────────
    # STEP HANDLERS
    # ─────────────────────────────────────────────────────────────

    async def _step_validate(
        self, step_name: str, step_config: dict, context: dict
    ) -> dict:
        """Validate required fields are present and of correct type."""
        required_fields = step_config.get("required_fields", [])
        missing = []
        
        for field_def in required_fields:
            if isinstance(field_def, str):
                field_name, field_type = field_def, None
            else:
                field_name = field_def.get("name")
                field_type = field_def.get("type")

            if field_name not in context or context[field_name] is None:
                missing.append(field_name)
            elif field_type:
                value = context[field_name]
                if field_type == "number" and not isinstance(value, (int, float)):
                    missing.append(f"{field_name} (expected number, got {type(value).__name__})")
                elif field_type == "boolean" and not isinstance(value, bool):
                    missing.append(f"{field_name} (expected boolean)")
                elif field_type == "string" and not isinstance(value, str):
                    missing.append(f"{field_name} (expected string)")

        if missing:
            raise StepFailureException(f"Validation failed: Missing/invalid fields: {missing}")

        return {"status": "validated", "data": {}}

    async def _step_rule_check(
        self,
        step_name: str,
        step_config: dict,
        instance: WorkflowInstance,
        context: dict,
        config: dict,
    ) -> dict:
        """Evaluate rules defined in the step or global config."""
        # Rules can be inline in step or referenced from global config
        rules = step_config.get("rules") or config.get("rules", [])
        logic = step_config.get("logic", config.get("rule_logic", "AND"))
        
        if not rules:
            return {"status": "no_rules", "data": {}}

        evaluation = self.rule_engine.evaluate_rules(rules, context, logic)
        
        rules_triggered = []
        for r in evaluation.results:
            rule_info = r.to_dict()
            rules_triggered.append(rule_info)
            
            await self.audit.log(
                workflow_id=instance.id,
                workflow_type=instance.workflow_type,
                event_type="rule_evaluated",
                step_name=step_name,
                rule_name=r.rule_name,
                rule_result=r.passed,
                rule_details=rule_info,
                message=r.message,
                severity="INFO" if r.passed else "WARN",
            )

        # Update instance
        existing_rules = instance.rules_triggered or []
        existing_rules.extend(rules_triggered)
        instance.rules_triggered = existing_rules

        if not evaluation.all_passed:
            failed_rules = [r.rule_name for r in evaluation.results if not r.passed]
            if step_config.get("fail_on_rule_failure", True):
                raise StepFailureException(
                    f"Rule check failed. Failed rules: {failed_rules}"
                )

        return {
            "status": "passed" if evaluation.all_passed else "failed",
            "rules_triggered": rules_triggered,
            "data": {"rule_evaluation": evaluation.to_dict()},
            "terminate": not evaluation.all_passed and step_config.get("fail_on_rule_failure", True),
            "reason": f"Rules failed: {[r.rule_name for r in evaluation.results if not r.passed]}" if not evaluation.all_passed else None,
        }

    async def _step_external_call(
        self,
        step_name: str,
        step_config: dict,
        instance: WorkflowInstance,
        context: dict,
    ) -> dict:
        """Make an external service call with retry logic."""
        service = step_config.get("service", step_name)
        max_retries = step_config.get("max_retries", instance.max_retries or 3)
        retry_delay = step_config.get("retry_delay_seconds", 1.0)
        backoff_multiplier = step_config.get("backoff_multiplier", 2.0)

        last_error = None
        attempt = 0

        while attempt <= max_retries:
            if attempt > 0:
                delay = retry_delay * (backoff_multiplier ** (attempt - 1))
                logger.info(f"🔁 Retry {attempt}/{max_retries} for '{service}' "
                            f"after {delay:.1f}s delay...")
                
                await self.audit.log(
                    workflow_id=instance.id,
                    workflow_type=instance.workflow_type,
                    event_type="step_retry",
                    step_name=step_name,
                    message=f"Retrying {service} (attempt {attempt}/{max_retries})",
                    event_data={"attempt": attempt, "delay_seconds": delay, "last_error": str(last_error)},
                    severity="WARN",
                )
                instance.retry_count = (instance.retry_count or 0) + 1
                await asyncio.sleep(delay)

            call_start = time.time()
            result = await self.external_sim.call_service(
                service_name=service,
                payload=context,
                config=step_config,
            )
            call_duration = int((time.time() - call_start) * 1000)

            await self.audit.log(
                workflow_id=instance.id,
                workflow_type=instance.workflow_type,
                event_type="external_call",
                step_name=service,
                message=(
                    f"External call to '{service}': "
                    f"{'SUCCESS' if result['success'] else 'FAILED - ' + result.get('error', '')}"
                ),
                duration_ms=call_duration,
                event_data=result,
                severity="INFO" if result["success"] else "WARN",
            )

            if result["success"]:
                return {
                    "status": "success",
                    "data": result.get("data", {}),
                    "external_result": result,
                }

            last_error = result.get("error", "Unknown error")
            attempt += 1

        # All retries exhausted
        raise StepFailureException(
            f"External service '{service}' failed after {max_retries + 1} attempts. "
            f"Last error: {last_error}"
        )

    async def _step_decision(
        self,
        step_name: str,
        step_config: dict,
        instance: WorkflowInstance,
        context: dict,
        config: dict,
    ) -> dict:
        """Make a workflow decision based on accumulated context."""
        # Run decision rules if specified
        decision_rules = step_config.get("rules") or config.get("decision_rules")
        
        if decision_rules:
            evaluation = self.rule_engine.evaluate_rules(
                decision_rules, context,
                logic=step_config.get("logic", "AND")
            )
            decision = "approved" if evaluation.all_passed else "rejected"
            reason_parts = []
            for r in evaluation.results:
                if not r.passed:
                    reason_parts.append(r.message)
        else:
            # Use status from context
            decision = context.get("_decision", "approved")
            reason_parts = [context.get("_decision_reason", "Automated decision")]

        reason = "; ".join(reason_parts) if reason_parts else step_config.get(
            "default_reason", "All conditions met"
        )

        instance.decision = decision
        instance.decision_reason = reason

        await self.audit.log(
            workflow_id=instance.id,
            workflow_type=instance.workflow_type,
            event_type="decision_made",
            step_name=step_name,
            message=f"Decision: {decision.upper()} | Reason: {reason}",
            event_data={"decision": decision, "reason": reason},
        )

        return {
            "status": decision,
            "data": {"decision": decision, "reason": reason},
        }

    async def _step_notification(
        self, step_name: str, step_config: dict, context: dict
    ) -> dict:
        """Simulate sending a notification (email, SMS, etc.)."""
        channel = step_config.get("channel", "email")
        template = step_config.get("template", "default")
        
        # Simulate notification sending (async, non-blocking)
        await asyncio.sleep(0.05)
        
        logger.info(f"📧 Notification sent via {channel} using template '{template}'")
        return {
            "status": "sent",
            "data": {"channel": channel, "template": template},
        }

    async def _step_process(
        self, step_name: str, step_config: dict, context: dict
    ) -> dict:
        """Generic processing step - data transformation, enrichment, etc."""
        # Apply any data transformations defined in config
        transforms = step_config.get("transforms", {})
        output = {}
        
        for key, expr in transforms.items():
            try:
                if isinstance(expr, str) and expr.startswith("$"):
                    # Simple field reference: "$field_name"
                    field = expr[1:]
                    output[key] = context.get(field)
                else:
                    output[key] = expr
            except Exception:
                pass

        # Simulate processing time
        delay = step_config.get("processing_delay", 0.05)
        await asyncio.sleep(delay)

        return {"status": "processed", "data": output}

    # ─────────────────────────────────────────────────────────────
    # FINAL DECISION
    # ─────────────────────────────────────────────────────────────

    async def _make_final_decision(
        self,
        instance: WorkflowInstance,
        config: dict,
        context: dict,
        rules_triggered: list,
    ) -> dict[str, Any]:
        """Finalize the workflow decision and update instance."""
        
        # If decision was already set (by a decision step or failure)
        if instance.decision:
            final_decision = instance.decision
            decision_reason = instance.decision_reason
        elif instance.status == "failed":
            final_decision = "rejected"
            decision_reason = instance.last_error or "Workflow failed"
        else:
            final_decision = "approved"
            decision_reason = "All workflow steps completed successfully"

        # Final rule evaluation (if configured)
        final_rules = config.get("final_rules", [])
        if final_rules and final_decision != "rejected":
            evaluation = self.rule_engine.evaluate_rules(final_rules, context)
            if not evaluation.all_passed:
                final_decision = "rejected"
                failed = [r.rule_name for r in evaluation.results if not r.passed]
                decision_reason = f"Final checks failed: {failed}"

        # Update instance to final state
        instance.status = "completed" if final_decision == "approved" else (
            "failed" if instance.status == "failed" else "completed"
        )
        instance.decision = final_decision
        instance.decision_reason = decision_reason
        instance.completed_at = datetime.utcnow()
        instance.updated_at = datetime.utcnow()
        instance.output_data = {
            "decision": final_decision,
            "reason": decision_reason,
            "steps_completed": instance.steps_completed,
            "rules_evaluated": len(rules_triggered),
        }

        await self.audit.log(
            workflow_id=instance.id,
            workflow_type=instance.workflow_type,
            event_type="workflow_completed",
            message=(
                f"Workflow completed | Decision: {final_decision.upper()} | "
                f"Steps: {len(instance.steps_completed or [])} | "
                f"Retries: {instance.retry_count}"
            ),
            event_data={
                "decision": final_decision,
                "reason": decision_reason,
                "steps_completed": instance.steps_completed,
            },
        )

        return {
            "workflow_id": instance.id,
            "workflow_type": instance.workflow_type,
            "status": instance.status,
            "decision": final_decision,
            "decision_reason": decision_reason,
            "steps_completed": instance.steps_completed or [],
            "rules_triggered": rules_triggered,
            "retry_count": instance.retry_count,
            "idempotent": False,
        }

    # ─────────────────────────────────────────────────────────────
    # IDEMPOTENCY
    # ─────────────────────────────────────────────────────────────

    async def _check_idempotency(self, key: str) -> Optional[IdempotencyRecord]:
        result = await self.db.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        )
        return result.scalar_one_or_none()

    async def _save_idempotency_record(
        self,
        key: str,
        workflow_id: str,
        workflow_type: str,
        response_data: dict,
    ):
        record = IdempotencyRecord(
            key=key,
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            response_data=response_data,
        )
        self.db.add(record)
        await self.db.flush()


class StepFailureException(Exception):
    """Raised when a workflow step fails and cannot be recovered."""
    pass
