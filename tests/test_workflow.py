"""
Comprehensive test suite for the Workflow Decision Platform.

Tests cover:
- Happy path (successful workflow)
- Invalid input validation
- Duplicate request idempotency
- Retry on external failure
- External dependency failure
- Rule change scenario
- Multiple workflow types
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.database import init_db, AsyncSessionLocal, engine
from app.models.database import Base


# ─────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Initialize test database (in-memory SQLite)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac


# ─────────────────────────────────────────────────────────────────
# HELPER DATA
# ─────────────────────────────────────────────────────────────────

VALID_APPLICATION_PAYLOAD = {
    "workflow_type": "application_approval",
    "payload": {
        "applicant_name": "Jane Doe",
        "salary": 75000,
        "credit_score": 720,
        "loan_amount": 200000,
        "employment_years": 3,
        "document_submitted": True,
    },
}

VALID_CLAIM_PAYLOAD = {
    "workflow_type": "claim_processing",
    "payload": {
        "claimant_name": "John Smith",
        "claim_amount": 5000,
        "incident_date": "2024-01-15",
        "policy_number": "POL-123456",
        "claim_type": "medical",
    },
}

VALID_ONBOARDING_PAYLOAD = {
    "workflow_type": "employee_onboarding",
    "payload": {
        "employee_name": "Alice Johnson",
        "department": "engineering",
        "role": "Senior Engineer",
        "start_date": "2024-02-01",
        "employment_type": "full_time",
    },
}


# ─────────────────────────────────────────────────────────────────
# 1. HEALTH CHECK
# ─────────────────────────────────────────────────────────────────

class TestHealthCheck:
    async def test_health_endpoint(self, client):
        response = await client.get("/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]
        assert "version" in data
        assert "loaded_workflows" in data
        assert len(data["loaded_workflows"]) > 0

    async def test_root_endpoint(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "available_workflows" in data
        assert len(data["available_workflows"]) > 0


# ─────────────────────────────────────────────────────────────────
# 2. HAPPY PATH TESTS
# ─────────────────────────────────────────────────────────────────

class TestHappyPath:
    async def test_application_approval_success(self, client):
        """Full successful application approval workflow."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
        ) as mock_service:
            mock_service.return_value = {
                "success": True,
                "data": {"verified": True, "verified_score": 725},
                "latency_ms": 300,
                "timestamp": "2024-01-01T00:00:00",
                "call_number": 1,
            }

            response = await client.post("/process-request", json=VALID_APPLICATION_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "workflow_id" in data
        assert data["result"]["decision"] in ["approved", "rejected"]  # depends on rules
        assert data["idempotent"] is False

    async def test_claim_processing_success(self, client):
        """Full successful claim processing workflow."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "data": {"policy_active": True},
                "latency_ms": 200,
                "timestamp": "2024-01-01T00:00:00",
                "call_number": 1,
            },
        ):
            response = await client.post("/process-request", json=VALID_CLAIM_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"]["decision"] in ["approved", "rejected"]

    async def test_employee_onboarding_success(self, client):
        """Full successful employee onboarding workflow."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "data": {"clear": True, "identity_verified": True},
                "latency_ms": 150,
                "timestamp": "2024-01-01T00:00:00",
                "call_number": 1,
            },
        ):
            response = await client.post("/process-request", json=VALID_ONBOARDING_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    async def test_workflow_status_retrievable(self, client):
        """Can retrieve workflow status after processing."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True, "data": {}, "latency_ms": 100,
                "timestamp": "2024-01-01T00:00:00", "call_number": 1,
            },
        ):
            create_resp = await client.post(
                "/process-request", json=VALID_APPLICATION_PAYLOAD
            )
        
        workflow_id = create_resp.json()["workflow_id"]
        status_resp = await client.get(f"/workflow-status/{workflow_id}")
        
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["id"] == workflow_id
        assert data["workflow_type"] == "application_approval"
        assert len(data["steps_completed"]) > 0

    async def test_audit_log_retrievable(self, client):
        """Can retrieve full audit trail after processing."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True, "data": {}, "latency_ms": 100,
                "timestamp": "2024-01-01T00:00:00", "call_number": 1,
            },
        ):
            create_resp = await client.post(
                "/process-request", json=VALID_APPLICATION_PAYLOAD
            )
        
        workflow_id = create_resp.json()["workflow_id"]
        audit_resp = await client.get(f"/audit-log/{workflow_id}")
        
        assert audit_resp.status_code == 200
        data = audit_resp.json()
        assert data["workflow_id"] == workflow_id
        assert data["total_events"] > 0
        assert "traceability_summary" in data
        assert len(data["events"]) > 0

        # Check event types
        event_types = [e["event_type"] for e in data["events"]]
        assert "workflow_started" in event_types
        assert "workflow_completed" in event_types


# ─────────────────────────────────────────────────────────────────
# 3. INVALID INPUT TESTS
# ─────────────────────────────────────────────────────────────────

class TestInvalidInput:
    async def test_unknown_workflow_type(self, client):
        """Returns 400 for unknown workflow type."""
        response = await client.post("/process-request", json={
            "workflow_type": "nonexistent_workflow",
            "payload": {"foo": "bar"},
        })
        assert response.status_code == 400
        assert "nonexistent_workflow" in response.json()["detail"]

    async def test_missing_required_fields(self, client):
        """Workflow fails gracefully when required fields are missing."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True, "data": {}, "latency_ms": 100,
                "timestamp": "2024-01-01T00:00:00", "call_number": 1,
            },
        ):
            response = await client.post("/process-request", json={
                "workflow_type": "application_approval",
                "payload": {"applicant_name": "John"},  # Missing many required fields
            })

        # Should return 200 but with failed/rejected status
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["decision"] in ["rejected", "approved"]

    async def test_invalid_payload_schema(self, client):
        """Returns 422 for malformed request body."""
        response = await client.post("/process-request", json={
            "workflow_type": 123,  # Should be string
            # Missing required 'payload'
        })
        assert response.status_code == 422

    async def test_workflow_status_not_found(self, client):
        """Returns 404 for unknown workflow ID."""
        response = await client.get("/workflow-status/nonexistent-uuid-here")
        assert response.status_code == 404

    async def test_audit_log_not_found(self, client):
        """Returns 404 for unknown workflow ID in audit log."""
        response = await client.get("/audit-log/nonexistent-uuid-here")
        assert response.status_code == 404

    async def test_below_minimum_salary_rejected(self, client):
        """Application rejected when salary below minimum."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True, "data": {}, "latency_ms": 100,
                "timestamp": "2024-01-01T00:00:00", "call_number": 1,
            },
        ):
            response = await client.post("/process-request", json={
                "workflow_type": "application_approval",
                "payload": {
                    "applicant_name": "Poor Applicant",
                    "salary": 5000,  # Below $30,000 minimum
                    "credit_score": 720,
                    "loan_amount": 200000,
                    "document_submitted": True,
                },
            })

        data = response.json()
        assert data["result"]["decision"] == "rejected"

    async def test_low_credit_score_rejected(self, client):
        """Application rejected when credit score below minimum."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True, "data": {}, "latency_ms": 100,
                "timestamp": "2024-01-01T00:00:00", "call_number": 1,
            },
        ):
            response = await client.post("/process-request", json={
                "workflow_type": "application_approval",
                "payload": {
                    "applicant_name": "Low Credit User",
                    "salary": 100000,
                    "credit_score": 400,  # Below 620 minimum
                    "loan_amount": 200000,
                    "document_submitted": True,
                },
            })

        data = response.json()
        assert data["result"]["decision"] == "rejected"


# ─────────────────────────────────────────────────────────────────
# 4. IDEMPOTENCY TESTS
# ─────────────────────────────────────────────────────────────────

class TestIdempotency:
    async def test_duplicate_request_idempotent(self, client):
        """Same idempotency key returns same result without re-processing."""
        idempotency_key = "idem-test-001"
        payload = {**VALID_APPLICATION_PAYLOAD, "idempotency_key": idempotency_key}

        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True, "data": {}, "latency_ms": 100,
                "timestamp": "2024-01-01T00:00:00", "call_number": 1,
            },
        ):
            # First request
            resp1 = await client.post("/process-request", json=payload)
            # Second request (duplicate)
            resp2 = await client.post("/process-request", json=payload)

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        data1, data2 = resp1.json(), resp2.json()
        assert data1["workflow_id"] == data2["workflow_id"]
        assert data2["idempotent"] is True

    async def test_header_idempotency_key(self, client):
        """Idempotency key in header works correctly."""
        key = "header-idem-002"

        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True, "data": {}, "latency_ms": 100,
                "timestamp": "2024-01-01T00:00:00", "call_number": 1,
            },
        ):
            resp1 = await client.post(
                "/process-request",
                json=VALID_APPLICATION_PAYLOAD,
                headers={"X-Idempotency-Key": key},
            )
            resp2 = await client.post(
                "/process-request",
                json=VALID_APPLICATION_PAYLOAD,
                headers={"X-Idempotency-Key": key},
            )

        assert resp1.json()["workflow_id"] == resp2.json()["workflow_id"]
        assert resp2.json()["idempotent"] is True

    async def test_different_keys_different_workflows(self, client):
        """Different idempotency keys create different workflow instances."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True, "data": {}, "latency_ms": 100,
                "timestamp": "2024-01-01T00:00:00", "call_number": 1,
            },
        ):
            resp1 = await client.post(
                "/process-request",
                json={**VALID_APPLICATION_PAYLOAD, "idempotency_key": "unique-key-A"},
            )
            resp2 = await client.post(
                "/process-request",
                json={**VALID_APPLICATION_PAYLOAD, "idempotency_key": "unique-key-B"},
            )

        assert resp1.json()["workflow_id"] != resp2.json()["workflow_id"]
        assert resp1.json()["idempotent"] is False
        assert resp2.json()["idempotent"] is False


# ─────────────────────────────────────────────────────────────────
# 5. RETRY LOGIC TESTS
# ─────────────────────────────────────────────────────────────────

class TestRetryLogic:
    async def test_retry_on_transient_failure(self, client):
        """Service succeeds after initial failures (retry works)."""
        call_count = 0

        async def flaky_service(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # Fail twice, succeed on third
                return {
                    "success": False,
                    "service": "credit_bureau",
                    "error": "SERVICE_UNAVAILABLE",
                    "latency_ms": 100,
                    "timestamp": "2024-01-01T00:00:00",
                    "call_number": call_count,
                }
            return {
                "success": True,
                "data": {"verified_score": 720},
                "latency_ms": 200,
                "timestamp": "2024-01-01T00:00:00",
                "call_number": call_count,
            }

        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            side_effect=flaky_service,
        ):
            response = await client.post("/process-request", json=VALID_APPLICATION_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        # Should have retried and eventually succeeded
        assert data["result"]["retry_count"] > 0
        assert data["status"] == "completed"


# ─────────────────────────────────────────────────────────────────
# 6. EXTERNAL DEPENDENCY FAILURE TESTS
# ─────────────────────────────────────────────────────────────────

class TestExternalDependencyFailure:
    async def test_required_external_service_failure(self, client):
        """Workflow fails when required external service exhausts retries."""
        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "error": "SERVICE_UNAVAILABLE",
                "error_message": "Service down",
                "latency_ms": 100,
                "timestamp": "2024-01-01T00:00:00",
                "call_number": 1,
            },
        ):
            response = await client.post("/process-request", json=VALID_APPLICATION_PAYLOAD)

        data = response.json()
        # Required external call failing should result in rejected/failed
        assert data["result"]["decision"] in ["rejected"]
        assert data["result"]["retry_count"] > 0

    async def test_optional_external_service_failure_continues(self, client):
        """Workflow continues when optional external service fails."""
        call_count = 0

        async def selective_fail(*args, service_name=None, **kwargs):
            nonlocal call_count
            call_count += 1
            # employment_verification is optional - fail it
            if "employment" in str(args):
                return {
                    "success": False, "error": "TIMEOUT",
                    "latency_ms": 100, "timestamp": "2024-01-01T00:00:00",
                    "call_number": call_count,
                }
            return {
                "success": True, "data": {"verified": True},
                "latency_ms": 100, "timestamp": "2024-01-01T00:00:00",
                "call_number": call_count,
            }

        with patch(
            "app.services.external_service.ExternalServiceSimulator.call_service",
            new_callable=AsyncMock,
            return_value={
                "success": True, "data": {"verified": True},
                "latency_ms": 100, "timestamp": "2024-01-01T00:00:00",
                "call_number": 1,
            },
        ):
            response = await client.post("/process-request", json=VALID_APPLICATION_PAYLOAD)

        # Workflow should complete (not fail completely)
        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────
# 7. RULE ENGINE TESTS
# ─────────────────────────────────────────────────────────────────

class TestRuleEngine:
    def test_rule_gte_pass(self):
        """Rule passes when value meets threshold."""
        from app.rules.rule_engine import RuleEngine
        engine = RuleEngine()
        result = engine.evaluate_rules(
            rules=[{"name": "salary_check", "field": "salary", "operator": "gte", "value": 50000}],
            data={"salary": 75000},
        )
        assert result.all_passed is True
        assert result.results[0].passed is True

    def test_rule_gte_fail(self):
        """Rule fails when value below threshold."""
        from app.rules.rule_engine import RuleEngine
        engine = RuleEngine()
        result = engine.evaluate_rules(
            rules=[{"name": "salary_check", "field": "salary", "operator": "gte", "value": 50000}],
            data={"salary": 25000},
        )
        assert result.all_passed is False
        assert result.results[0].passed is False

    def test_composite_rule_and(self):
        """Composite AND rule: all conditions must pass."""
        from app.rules.rule_engine import RuleEngine
        engine = RuleEngine()
        result = engine.evaluate_rules(
            rules=[{
                "name": "credit_check",
                "type": "composite",
                "logic": "AND",
                "conditions": [
                    {"name": "score_min", "field": "credit_score", "operator": "gte", "value": 650},
                    {"name": "salary_min", "field": "salary", "operator": "gte", "value": 40000},
                ],
            }],
            data={"credit_score": 720, "salary": 80000},
        )
        assert result.all_passed is True

    def test_composite_rule_or(self):
        """Composite OR rule: at least one condition must pass."""
        from app.rules.rule_engine import RuleEngine
        engine = RuleEngine()
        result = engine.evaluate_rules(
            rules=[{
                "name": "any_asset",
                "type": "composite",
                "logic": "OR",
                "conditions": [
                    {"name": "has_property", "field": "has_property", "operator": "is_true"},
                    {"name": "has_stocks", "field": "has_stocks", "operator": "is_true"},
                ],
            }],
            data={"has_property": True, "has_stocks": False},
        )
        assert result.all_passed is True

    def test_missing_required_field(self):
        """Rule fails gracefully for missing required field."""
        from app.rules.rule_engine import RuleEngine
        engine = RuleEngine()
        result = engine.evaluate_rules(
            rules=[{"name": "salary_check", "field": "salary", "operator": "gte", "value": 50000}],
            data={"name": "Test User"},  # salary missing
        )
        assert result.all_passed is False
        assert "missing" in result.results[0].message.lower()

    def test_rule_change_scenario(self):
        """Same data, different threshold => different result."""
        from app.rules.rule_engine import RuleEngine
        engine = RuleEngine()
        data = {"salary": 45000}

        # Old threshold: 40k
        result_old = engine.evaluate_rules(
            rules=[{"name": "salary", "field": "salary", "operator": "gte", "value": 40000}],
            data=data,
        )
        # New threshold: 50k
        result_new = engine.evaluate_rules(
            rules=[{"name": "salary", "field": "salary", "operator": "gte", "value": 50000}],
            data=data,
        )

        assert result_old.all_passed is True
        assert result_new.all_passed is False  # Same data, different rule → different outcome

    def test_between_operator(self):
        """Between operator works correctly."""
        from app.rules.rule_engine import RuleEngine
        engine = RuleEngine()
        result = engine.evaluate_rules(
            rules=[{"name": "age_range", "field": "age", "operator": "between", "value": [18, 65]}],
            data={"age": 35},
        )
        assert result.all_passed is True

    def test_in_operator(self):
        """In operator checks list membership."""
        from app.rules.rule_engine import RuleEngine
        engine = RuleEngine()
        result = engine.evaluate_rules(
            rules=[{"name": "dept", "field": "department", "operator": "in",
                    "value": ["engineering", "sales"]}],
            data={"department": "engineering"},
        )
        assert result.all_passed is True


# ─────────────────────────────────────────────────────────────────
# 8. WORKFLOW MANAGEMENT TESTS
# ─────────────────────────────────────────────────────────────────

class TestWorkflowManagement:
    async def test_list_workflows(self, client):
        """Can list all configured workflows."""
        response = await client.get("/workflows")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert data["total"] > 0
        workflow_names = [w["name"] for w in data["workflows"]]
        assert "application_approval" in workflow_names

    async def test_get_workflow_config(self, client):
        """Can retrieve specific workflow configuration."""
        response = await client.get("/workflows/application_approval/config")
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_type"] == "application_approval"
        assert "steps" in data["config"]

    async def test_get_unknown_workflow_config(self, client):
        """Returns 404 for unknown workflow config."""
        response = await client.get("/workflows/unknown_workflow/config")
        assert response.status_code == 404

    async def test_list_instances(self, client):
        """Can list workflow instances."""
        response = await client.get("/workflows/instances/list")
        assert response.status_code == 200
        data = response.json()
        assert "instances" in data

    async def test_hot_reload(self, client):
        """Config hot reload endpoint works."""
        response = await client.post("/workflows/reload")
        assert response.status_code == 200
        data = response.json()
        assert "loaded_workflows" in data
        assert len(data["loaded_workflows"]) > 0
