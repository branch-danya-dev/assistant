"""Closed numeric contracts and budgets; no evaluator or authority in this module."""
from __future__ import annotations

from jsonschema import Draft202012Validator

from .config import AgentError, specification
from .storage import encode

CURRENCY_SCALES = {"RUB": 2, "USD": 2, "EUR": 2, "JPY": 0, "KWD": 3}
OPERATIONS = ("calculate", "cost_scenarios")
MAX_INPUT = 4096
MAX_OUTPUT = 8192
MAX_DIGITS = 60


def schema(operation, direction):
    if operation not in OPERATIONS:
        raise AgentError("unregistered_operation")
    return specification(f"schemas/{operation.replace('_', '-')}-{direction}.schema.json")


def check_input(operation, arguments):
    try:
        if len(encode(arguments).encode("utf-8")) > MAX_INPUT:
            raise AgentError("calculator_budget_exhausted")
        # Bound traversal before invoking recursive JSON Schema validation.
        if operation == "calculate":
            count, pending = 0, [(arguments.get("expression"), 1)]
            while pending:
                node, depth = pending.pop()
                count += 1
                if depth > 8 or count > 64:
                    raise AgentError("calculator_budget_exhausted")
                if isinstance(node, dict) and isinstance(node.get("args"), list):
                    pending.extend((n, depth + 1) for n in node["args"])
        if not Draft202012Validator(schema(operation, "input")).is_valid(arguments):
            raise AgentError("calculator_invalid_input")
        if operation == "calculate":
            if type(arguments["scale"]) is not int:
                raise AgentError("calculator_invalid_input")
            unit = arguments["unit"]
            if unit["kind"] == "currency" and arguments["scale"] != CURRENCY_SCALES[unit["code"]]:
                raise AgentError("calculator_unit_mismatch")
        else:
            names = [s["name"] for s in arguments["scenarios"]]
            if len(names) != len(set(names)):
                raise AgentError("calculator_invalid_input")
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise AgentError("calculator_invalid_input") from None


def check_output(operation, result):
    try:
        if len(encode(result).encode("utf-8")) > MAX_OUTPUT:
            raise AgentError("calculator_budget_exhausted")
        if not Draft202012Validator(schema(operation, "output")).is_valid(result):
            raise AgentError("calculator_invalid_output")
    except (ValueError, TypeError, RecursionError):
        raise AgentError("calculator_invalid_output") from None


def descriptors():
    return tuple(dict(id="CAP-009", version="1.0", operation=operation,
        side_effect="read", scope="owner_task_scope", timeout_seconds=5,
        approval_required=False, input_schema=schema(operation, "input"),
        output_schema=schema(operation, "output"), verifier="independent_exact_rational",
        idempotent=True, retry_policy="explicit_resume_max_2", effect_resolver="m1_closed_registry")
        for operation in OPERATIONS)
