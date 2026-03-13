"""
External Dependency Simulator.

Simulates external API calls with:
- Configurable success/failure rates
- Realistic latency
- Intermittent failures (for retry testing)
- Different service types (credit check, KYC, background check, etc.)
"""

import asyncio
import logging
import random
from typing import Any
from datetime import datetime

logger = logging.getLogger(__name__)


class ExternalServiceSimulator:
    """
    Simulates external service calls with realistic behavior.
    Used to demonstrate retry logic, failure handling, and timeouts.
    """

    # Simulated service registry
    SERVICES = {
        "credit_bureau": {
            "success_rate": 0.90,
            "latency_range": (0.2, 0.8),
            "description": "Credit score verification service",
        },
        "kyc_verification": {
            "success_rate": 0.85,
            "latency_range": (0.5, 1.5),
            "description": "Know Your Customer identity verification",
        },
        "background_check": {
            "success_rate": 0.92,
            "latency_range": (1.0, 2.0),
            "description": "Background screening service",
        },
        "document_verification": {
            "success_rate": 0.88,
            "latency_range": (0.3, 1.0),
            "description": "Document authenticity verification",
        },
        "sanctions_screening": {
            "success_rate": 0.95,
            "latency_range": (0.1, 0.5),
            "description": "OFAC sanctions list screening",
        },
        "employment_verification": {
            "success_rate": 0.87,
            "latency_range": (0.4, 1.2),
            "description": "Employment history verification",
        },
        "insurance_check": {
            "success_rate": 0.91,
            "latency_range": (0.3, 0.9),
            "description": "Insurance policy validation",
        },
        "tax_verification": {
            "success_rate": 0.93,
            "latency_range": (0.5, 1.0),
            "description": "Tax record verification",
        },
    }

    def __init__(self, force_fail: bool = False, force_success: bool = False):
        self.force_fail = force_fail
        self.force_success = force_success
        self._call_counts: dict[str, int] = {}

    async def call_service(
        self,
        service_name: str,
        payload: dict[str, Any],
        config: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """
        Simulate an external service call.
        
        Returns a dict with:
          - success: bool
          - data: response data (if success)
          - error: error message (if failure)
          - latency_ms: simulated latency
          - service: service name
          - timestamp: call timestamp
        """
        config = config or {}
        service_config = self.SERVICES.get(service_name, {
            "success_rate": 0.90,
            "latency_range": (0.3, 1.0),
            "description": service_name,
        })

        # Simulate network latency
        latency = random.uniform(*service_config["latency_range"])
        await asyncio.sleep(latency)

        # Track call count (for intermittent failure simulation)
        call_key = f"{service_name}"
        self._call_counts[call_key] = self._call_counts.get(call_key, 0) + 1

        # Determine success/failure
        if self.force_fail:
            success = False
        elif self.force_success:
            success = True
        else:
            success = random.random() < service_config["success_rate"]

        timestamp = datetime.utcnow().isoformat()
        latency_ms = int(latency * 1000)

        if not success:
            error_types = [
                "SERVICE_UNAVAILABLE",
                "TIMEOUT",
                "RATE_LIMIT_EXCEEDED",
                "INTERNAL_SERVER_ERROR",
            ]
            error = random.choice(error_types)
            logger.warning(
                f"🌐 External call FAILED | service={service_name} | "
                f"error={error} | latency={latency_ms}ms"
            )
            return {
                "success": False,
                "service": service_name,
                "error": error,
                "error_message": f"{service_config['description']} returned {error}",
                "latency_ms": latency_ms,
                "timestamp": timestamp,
                "call_number": self._call_counts[call_key],
            }

        # Generate realistic response data based on service type
        response_data = self._generate_response(service_name, payload, config)
        
        logger.info(
            f"🌐 External call SUCCESS | service={service_name} | "
            f"latency={latency_ms}ms"
        )

        return {
            "success": True,
            "service": service_name,
            "data": response_data,
            "latency_ms": latency_ms,
            "timestamp": timestamp,
            "call_number": self._call_counts[call_key],
        }

    def _generate_response(
        self, service_name: str, payload: dict, config: dict
    ) -> dict[str, Any]:
        """Generate realistic mock response data for each service type."""

        if service_name == "credit_bureau":
            base_score = payload.get("credit_score", random.randint(580, 820))
            return {
                "verified_score": base_score + random.randint(-10, 10),
                "score_band": self._credit_band(base_score),
                "bureau": random.choice(["Equifax", "Experian", "TransUnion"]),
                "report_id": f"CR-{random.randint(100000, 999999)}",
                "derogatory_marks": random.randint(0, 3),
                "verified": True,
            }

        elif service_name == "kyc_verification":
            return {
                "identity_verified": True,
                "risk_level": random.choice(["LOW", "MEDIUM"]),
                "verification_id": f"KYC-{random.randint(10000, 99999)}",
                "checks_passed": ["ID_MATCH", "LIVENESS", "DOCUMENT_SCAN"],
                "country": payload.get("country", "US"),
            }

        elif service_name == "background_check":
            return {
                "clear": True,
                "criminal_record": False,
                "adverse_media": False,
                "report_id": f"BGC-{random.randint(10000, 99999)}",
                "completed_at": datetime.utcnow().isoformat(),
            }

        elif service_name == "document_verification":
            return {
                "document_authentic": True,
                "document_type": payload.get("document_type", "PASSPORT"),
                "ocr_confidence": round(random.uniform(0.85, 0.99), 2),
                "verification_id": f"DOC-{random.randint(10000, 99999)}",
                "tamper_detected": False,
            }

        elif service_name == "sanctions_screening":
            return {
                "sanctioned": False,
                "pep_status": False,
                "lists_checked": ["OFAC", "EU", "UN", "HMT"],
                "screening_id": f"SANC-{random.randint(10000, 99999)}",
            }

        elif service_name == "employment_verification":
            salary = payload.get("salary", random.randint(40000, 120000))
            return {
                "employed": True,
                "employer_verified": True,
                "verified_salary": salary,
                "employment_months": payload.get("employment_years", 2) * 12,
                "position": payload.get("position", "Employee"),
            }

        elif service_name == "insurance_check":
            return {
                "policy_active": True,
                "coverage_amount": payload.get("claim_amount", 10000) * 2,
                "policy_number": f"POL-{random.randint(100000, 999999)}",
                "claim_history": random.randint(0, 3),
            }

        elif service_name == "tax_verification":
            return {
                "tax_compliant": True,
                "last_filing_year": datetime.now().year - 1,
                "verification_id": f"TAX-{random.randint(10000, 99999)}",
                "outstanding_liabilities": 0,
            }

        else:
            return {
                "verified": True,
                "service": service_name,
                "reference_id": f"REF-{random.randint(10000, 99999)}",
            }

    def _credit_band(self, score: int) -> str:
        if score >= 800:
            return "EXCEPTIONAL"
        elif score >= 740:
            return "VERY_GOOD"
        elif score >= 670:
            return "GOOD"
        elif score >= 580:
            return "FAIR"
        else:
            return "POOR"
