"""Independent verifier: Fraction/integer arithmetic, no executor imports/calls.

Shared JSON contracts define admissibility. Evaluation, dimensional rules, cost
formulas and half-even display are independently recomputed here, not attested by
an executor/model-controlled boolean. Decimal's ambient context is irrelevant.
"""
from __future__ import annotations

import hashlib
from fractions import Fraction

from .calculator_contract import CURRENCY_SCALES, MAX_DIGITS, check_input, check_output
from .config import AgentError
from .storage import encode


def bounded(value):
    if max(len(str(abs(value.numerator))), len(str(value.denominator))) > MAX_DIGITS:
        raise AgentError("calculator_budget_exhausted")
    return value


def walk(node):
    operation = node["op"]
    if operation == "literal":
        return bounded(Fraction(node["value"])), node["unit"]
    operands = [walk(child) for child in node["args"]]
    x, xu = operands[0]
    if operation == "negate":
        return -x, xu
    y, yu = operands[1]
    scalar = {"kind": "scalar"}
    if operation in {"add", "subtract"}:
        if xu != yu:
            raise AgentError("calculator_unit_mismatch")
        value, unit = (x + y if operation == "add" else x - y), xu
    elif operation == "multiply":
        if xu != scalar and yu != scalar:
            raise AgentError("calculator_unit_mismatch")
        value, unit = x * y, yu if xu == scalar else xu
    elif operation == "divide":
        if xu != yu and yu != scalar:
            raise AgentError("calculator_unit_mismatch")
        value, unit = x / y, scalar if xu == yu else xu
    else:
        if yu != scalar:
            raise AgentError("calculator_unit_mismatch")
        value, unit = bounded(x * y) / 100, xu
    return bounded(value), unit


def render(value, places):
    bounded(value)
    scaled = abs(value.numerator) * 10 ** places
    integer, remainder = divmod(scaled, value.denominator)
    comparison = remainder * 2 - value.denominator
    integer += int(comparison > 0 or (comparison == 0 and integer % 2 == 1))
    digits = str(integer).zfill(places + 1)
    text = digits if places == 0 else digits[:-places] + "." + digits[-places:]
    if value < 0 and integer:
        text = "-" + text
    return {"value": text, "numerator": str(value.numerator), "denominator": str(value.denominator),
            "scale": places, "rounding_applied": remainder != 0}


def quotient(numerator, denominator, places, multiplier=1):
    if denominator == 0:
        return {"status": "undefined_zero_denominator"}
    value = bounded(numerator / denominator)
    return render(bounded(value * multiplier), places)


def verify(operation, arguments, receipt):
    check_input(operation, arguments)
    check_output(operation, receipt)
    try:
        if operation == "calculate":
            number, unit = walk(arguments["expression"])
            if unit != arguments["unit"]:
                raise AgentError("calculator_unit_mismatch")
            expected = {"unit": unit, "number": render(number, arguments["scale"])}
        else:
            rows = []
            places = CURRENCY_SCALES[arguments["currency"]]
            for scenario in arguments["scenarios"]:
                inputs = {k: Fraction(v) for k, v in scenario.items() if k != "name"}
                if any(v < 0 for v in inputs.values()):
                    raise AgentError("calculator_negative_input")
                q = inputs["quantity"]
                variable = bounded(q * inputs["variable_cost_per_unit"])
                cost = bounded(variable + inputs["fixed_cost_total"])
                row = {"name": scenario["name"], "variable_cost": render(variable, places),
                       "total_cost": render(cost, places), "unit_cost": quotient(cost, q, places),
                       "revenue": None, "profit": None, "gross_margin_percent": None, "markup_percent": None}
                if "selling_price_per_unit" in inputs:
                    revenue = bounded(q * inputs["selling_price_per_unit"])
                    profit = bounded(revenue - cost)
                    row["revenue"] = render(revenue, places)
                    row["profit"] = render(profit, places)
                    row["gross_margin_percent"] = quotient(profit, revenue, 6, 100)
                    row["markup_percent"] = quotient(profit, cost, 6, 100)
                rows.append(row)
            expected = {"currency": arguments["currency"], "quantity_unit": "item", "scenarios": rows}
        complete = {"contract": "decimal-v1", "operation": operation,
                    "input_digest": hashlib.sha256(encode(arguments).encode("utf-8")).hexdigest(),
                    "result": expected}
        if encode(receipt) != encode(complete):
            raise AgentError("calculator_verification_failed")
    except ZeroDivisionError:
        raise AgentError("calculator_zero_division") from None
