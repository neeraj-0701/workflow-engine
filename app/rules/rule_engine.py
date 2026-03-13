"""
Rule Evaluation Engine.

Evaluates rules/conditions against workflow payload data.
Supports: comparisons, logical operators (AND/OR), nested rules,
          custom functions, and detailed tracing.

Rule config format:
  rules:
    - name: "minimum_salary"
      field: "salary"
      operator: "gte"
      value: 50000
      
    - name: "credit_check"
      type: "composite"
      logic: "AND"
      conditions:
        - field: "credit_score"
          operator: "gte"
          value: 650
        - field: "debt_ratio"
          operator: "lte"
          value: 0.43
"""

import logging
import re
from typing import Any
from dataclasses import dataclass, field as dc_field

logger = logging.getLogger(__name__)

# Supported operators
OPERATORS = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: float(a) > float(b),
    "gte": lambda a, b: float(a) >= float(b),
    "lt": lambda a, b: float(a) < float(b),
    "lte": lambda a, b: float(a) <= float(b),
    "in": lambda a, b: a in (b if isinstance(b, list) else [b]),
    "not_in": lambda a, b: a not in (b if isinstance(b, list) else [b]),
    "contains": lambda a, b: str(b).lower() in str(a).lower(),
    "starts_with": lambda a, b: str(a).startswith(str(b)),
    "ends_with": lambda a, b: str(a).endswith(str(b)),
    "is_true": lambda a, _: bool(a) is True,
    "is_false": lambda a, _: bool(a) is False,
    "is_null": lambda a, _: a is None,
    "not_null": lambda a, _: a is not None,
    "between": lambda a, b: float(b[0]) <= float(a) <= float(b[1]),
    "regex": lambda a, b: bool(re.match(str(b), str(a))),
}


@dataclass
class RuleResult:
    """Result of a single rule evaluation."""
    rule_name: str
    passed: bool
    field: str = ""
    operator: str = ""
    expected: Any = None
    actual: Any = None
    message: str = ""
    sub_results: list["RuleResult"] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rule_name": self.rule_name,
            "passed": self.passed,
            "field": self.field,
            "operator": self.operator,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
            "sub_results": [r.to_dict() for r in self.sub_results],
        }


@dataclass
class RuleEvaluationSummary:
    """Summary of all rule evaluations for a workflow step."""
    all_passed: bool
    results: list[RuleResult]
    logic: str = "AND"  # AND = all must pass, OR = at least one must pass

    def to_dict(self) -> dict:
        return {
            "all_passed": self.all_passed,
            "logic": self.logic,
            "results": [r.to_dict() for r in self.results],
            "passed_count": sum(1 for r in self.results if r.passed),
            "failed_count": sum(1 for r in self.results if not r.passed),
        }


class RuleEngine:
    """
    Evaluates rule sets against a data payload.
    Supports simple, composite, and nested rules.
    """

    def evaluate_rules(
        self,
        rules: list[dict],
        data: dict[str, Any],
        logic: str = "AND",
    ) -> RuleEvaluationSummary:
        """
        Evaluate a list of rules against data.
        
        Args:
            rules: List of rule definitions from workflow config
            data: The payload data to evaluate against
            logic: "AND" (all must pass) or "OR" (any must pass)
        """
        results = []

        for rule_config in rules:
            result = self._evaluate_single_rule(rule_config, data)
            results.append(result)
            logger.debug(f"Rule '{result.rule_name}': {'✅ PASS' if result.passed else '❌ FAIL'} | {result.message}")

        if logic == "OR":
            all_passed = any(r.passed for r in results)
        else:  # AND (default)
            all_passed = all(r.passed for r in results)

        return RuleEvaluationSummary(
            all_passed=all_passed,
            results=results,
            logic=logic,
        )

    def _evaluate_single_rule(self, rule: dict, data: dict[str, Any]) -> RuleResult:
        """Evaluate a single rule (simple or composite)."""
        rule_name = rule.get("name", "unnamed_rule")
        rule_type = rule.get("type", "simple")

        try:
            if rule_type == "composite":
                return self._evaluate_composite_rule(rule_name, rule, data)
            else:
                return self._evaluate_simple_rule(rule_name, rule, data)
        except Exception as e:
            logger.error(f"Rule evaluation error [{rule_name}]: {e}")
            return RuleResult(
                rule_name=rule_name,
                passed=False,
                message=f"Evaluation error: {str(e)}",
            )

    def _evaluate_simple_rule(self, rule_name: str, rule: dict, data: dict) -> RuleResult:
        """Evaluate a simple field-operator-value rule."""
        field_path = rule.get("field", "")
        operator = rule.get("operator", "eq")
        expected = rule.get("value")
        required = rule.get("required", True)

        # Get field value (supports dot notation: "address.city")
        actual = self._get_field_value(data, field_path)

        # Handle missing fields
        if actual is None and required:
            return RuleResult(
                rule_name=rule_name,
                passed=False,
                field=field_path,
                operator=operator,
                expected=expected,
                actual=None,
                message=f"Required field '{field_path}' is missing",
            )

        if actual is None and not required:
            return RuleResult(
                rule_name=rule_name,
                passed=True,
                field=field_path,
                operator=operator,
                expected=expected,
                actual=None,
                message=f"Optional field '{field_path}' not present, skipping",
            )

        # Evaluate operator
        op_func = OPERATORS.get(operator)
        if not op_func:
            return RuleResult(
                rule_name=rule_name,
                passed=False,
                message=f"Unknown operator: {operator}",
            )

        try:
            passed = op_func(actual, expected)
        except (ValueError, TypeError) as e:
            passed = False
            return RuleResult(
                rule_name=rule_name,
                passed=False,
                field=field_path,
                operator=operator,
                expected=expected,
                actual=actual,
                message=f"Type error during evaluation: {e}",
            )

        message = (
            f"{field_path} ({actual}) {operator} {expected} → {'PASS' if passed else 'FAIL'}"
        )
        if not passed and "fail_message" in rule:
            message = rule["fail_message"].format(actual=actual, expected=expected)

        return RuleResult(
            rule_name=rule_name,
            passed=passed,
            field=field_path,
            operator=operator,
            expected=expected,
            actual=actual,
            message=message,
        )

    def _evaluate_composite_rule(self, rule_name: str, rule: dict, data: dict) -> RuleResult:
        """Evaluate a composite rule (nested conditions with AND/OR logic)."""
        conditions = rule.get("conditions", [])
        logic = rule.get("logic", "AND")
        sub_results = []

        for condition in conditions:
            sub_rule_name = condition.get("name", f"{rule_name}_sub")
            sub_result = self._evaluate_simple_rule(sub_rule_name, condition, data)
            sub_results.append(sub_result)

        if logic == "OR":
            passed = any(r.passed for r in sub_results)
        else:
            passed = all(r.passed for r in sub_results)

        failed = [r for r in sub_results if not r.passed]
        message = (
            f"Composite [{logic}]: {len(sub_results) - len(failed)}/{len(sub_results)} passed"
        )

        return RuleResult(
            rule_name=rule_name,
            passed=passed,
            message=message,
            sub_results=sub_results,
        )

    def _get_field_value(self, data: dict, field_path: str) -> Any:
        """
        Get value from nested dict using dot notation.
        E.g., "applicant.address.city" -> data["applicant"]["address"]["city"]
        """
        if not field_path:
            return None
        
        parts = field_path.split(".")
        current = data
        
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        
        return current
