"""
FastAPI API routes for the Workflow Decision Platform.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.services.database import get_db
from app.services.config_loader import ConfigLoader
from app.models.database import WorkflowInstance
from app.models.schemas import (
    ProcessRequestInput,
    ProcessRequestResponse,
    WorkflowStatusResponse,
    AuditLogResponse,
    WorkflowListResponse,
    HealthResponse,
)
from app.workflows.engine import WorkflowEngine
from app.audit.audit_logger import AuditLogger

logger = logging.getLogger(__name__)

workflow_router = APIRouter()
health_router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# CORE ENDPOINTS
# ─────────────────────────────────────────────────────────────────

@workflow_router.post(
    "/process-request",
    response_model=ProcessRequestResponse,
    summary="Process a workflow request",
    description="""
    Submit a request to be processed through a configurable workflow.
    
    Supports idempotency via the `X-Idempotency-Key` header or `idempotency_key` in the body.
    Duplicate requests with the same key return the original result immediately.
    """,
)
async def process_request(
    request: ProcessRequestInput,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Process a workflow request end-to-end."""
    # Idempotency key precedence: header > body
    idempotency_key = x_idempotency_key or request.idempotency_key

    try:
        engine = WorkflowEngine(db)
        result = await engine.process_request(
            workflow_type=request.workflow_type,
            payload=request.payload,
            idempotency_key=idempotency_key,
        )

        return ProcessRequestResponse(
            workflow_id=result["workflow_id"],
            status=result["status"],
            message=f"Workflow '{request.workflow_type}' {result['status']}. "
                    f"Decision: {result.get('decision', 'pending').upper()}",
            idempotent=result.get("idempotent", False),
            result=result,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error processing request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@workflow_router.get(
    "/workflow-status/{workflow_id}",
    response_model=WorkflowStatusResponse,
    summary="Get workflow execution status",
)
async def get_workflow_status(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the current status of a workflow instance."""
    result = await db.execute(
        select(WorkflowInstance).where(WorkflowInstance.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")

    return WorkflowStatusResponse(**workflow.to_dict())


@workflow_router.get(
    "/audit-log/{workflow_id}",
    response_model=AuditLogResponse,
    summary="Get complete audit trail",
    description="Returns the full immutable audit trail for a workflow, including decision traceability.",
)
async def get_audit_log(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the complete audit trail with decision traceability."""
    audit_logger = AuditLogger(db)
    trail = await audit_logger.get_audit_trail(workflow_id)

    if "error" in trail:
        raise HTTPException(status_code=404, detail=trail["error"])

    return AuditLogResponse(**trail)


# ─────────────────────────────────────────────────────────────────
# WORKFLOW MANAGEMENT
# ─────────────────────────────────────────────────────────────────

@workflow_router.get(
    "/workflows",
    response_model=WorkflowListResponse,
    summary="List available workflows",
)
async def list_workflows():
    """List all configured workflow types with their step definitions."""
    config_loader = ConfigLoader()
    workflows = config_loader.list_workflows()
    return WorkflowListResponse(workflows=workflows, total=len(workflows))


@workflow_router.post(
    "/workflows/reload",
    summary="Hot reload workflow configurations",
    description="Reloads all YAML config files without restarting the server.",
)
async def reload_configs():
    """Hot reload all workflow configurations."""
    config_loader = ConfigLoader()
    reloaded = config_loader.reload()
    return {
        "message": "Configurations reloaded successfully",
        "loaded_workflows": list(reloaded.keys()),
        "count": len(reloaded),
    }


@workflow_router.get(
    "/workflows/{workflow_type}/config",
    summary="Get workflow configuration",
)
async def get_workflow_config(workflow_type: str):
    """Get the YAML configuration for a specific workflow."""
    config_loader = ConfigLoader()
    config = config_loader.get_workflow(workflow_type)
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_type}' not found"
        )
    return {"workflow_type": workflow_type, "config": config}


@workflow_router.get(
    "/workflows/instances/list",
    summary="List workflow instances",
)
async def list_instances(
    workflow_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List workflow instances with optional filtering."""
    query = select(WorkflowInstance).order_by(
        WorkflowInstance.created_at.desc()
    ).limit(limit)

    if workflow_type:
        query = query.where(WorkflowInstance.workflow_type == workflow_type)
    if status:
        query = query.where(WorkflowInstance.status == status)

    result = await db.execute(query)
    instances = result.scalars().all()

    return {
        "instances": [i.to_dict() for i in instances],
        "total": len(instances),
        "filters": {"workflow_type": workflow_type, "status": status},
    }


# ─────────────────────────────────────────────────────────────────
# HEALTH & DIAGNOSTICS
# ─────────────────────────────────────────────────────────────────

@health_router.get(
    "/",
    response_model=HealthResponse,
    summary="Health check",
)
async def health_check(db: AsyncSession = Depends(get_db)):
    """Platform health check."""
    from datetime import datetime

    # Test DB
    try:
        await db.execute(select(WorkflowInstance).limit(1))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {e}"

    config_loader = ConfigLoader()
    configs = config_loader.get_all()

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        version="1.0.0",
        database=db_status,
        loaded_workflows=list(configs.keys()),
        timestamp=datetime.utcnow().isoformat(),
    )
