"""Pure Decimal arithmetic on bounded exact fractions. Only display is rounded.

Numerators/denominators are Decimal integers, not binary floats. Cross products of
two <=60-digit operands fit exactly in the private 256-digit context. Reduction
and output bounds run after each operation. No code/expression-string execution.
"""
from __future__ import annotations

import hashlib
from decimal import Context, Decimal, DecimalException, Inexact, localcontext

from .calculator_contract import CURRENCY_SCALES, MAX_DIGITS, check_input, check_output
from .config import AgentError
from .storage import encode

SCALAR = {"kind": "scalar"}


def fraction(n, d=Decimal(1)):
    if not d:
        raise AgentError("calculator_zero_division")
    if d < 0:
        n, d = -n, -d
    if not n:
        return Decimal(0), Decimal(1)
    a, b = abs(n), d
    while b:
        a, b = b, a % b
    n, d = (n / a).quantize(Decimal(1)), (d / a).quantize(Decimal(1))
    if any(len(format(abs(v), "f")) > MAX_DIGITS for v in (n, d)):
        raise AgentError("calculator_budget_exhausted")
    return n, d


def literal(value):
    number = Decimal(value)
    denominator = Decimal(10) ** max(0, -number.as_tuple().exponent)
    return fraction(number * denominator, denominator)


def binary(op, left, right):
    a, b = left
    c, d = right
    if op == "add":
        return fraction(a * d + c * b, b * d)
    if op == "subtract":
        return fraction(a * d - c * b, b * d)
    if op == "multiply":
        return fraction(a * c, b * d)
    if op == "divide":
        return fraction(a * d, b * c)
    raise AgentError("calculator_invalid_input")


def evaluate(node):
    op = node["op"]
    if op == "literal":
        return literal(node["value"]), node["unit"]
    left, unit = evaluate(node["args"][0])
    if op == "negate":
        return (-left[0], left[1]), unit
    right, other = evaluate(node["args"][1])
    if op in ("add", "subtract"):
        if unit != other:
            raise AgentError("calculator_unit_mismatch")
    elif op == "multiply":
        if unit == SCALAR:
            unit = other
        elif other != SCALAR:
            raise AgentError("calculator_unit_mismatch")
    elif op == "divide":
        if unit == other:
            unit = SCALAR
        elif other != SCALAR:
            raise AgentError("calculator_unit_mismatch")
    elif op == "percent":
        if other != SCALAR:
            raise AgentError("calculator_unit_mismatch")
        product = binary("multiply", left, right)
        return binary("divide", product, (Decimal(100), Decimal(1))), unit
    return binary(op, left, right), unit


def display(value, scale):
    n, d = value
    scaled = abs(n) * (Decimal(10) ** scale)
    whole, remainder = scaled // d, scaled % d
    if remainder * 2 > d or (remainder * 2 == d and whole % 2):
        whole += 1
    if n < 0 and whole:
        whole = -whole
    return {"value": format(whole.scaleb(-scale), f".{scale}f"),
            "numerator": format(n, "f"), "denominator": format(d, "f"),
            "scale": scale, "rounding_applied": bool(remainder)}


def ratio(a, b, scale, *, percent=False):
    if not b[0]:
        return {"status": "undefined_zero_denominator"}
    value = binary("divide", a, b)
    if percent:
        value = binary("multiply", value, (Decimal(100), Decimal(1)))
    return display(value, scale)


def scenarios(arguments):
    scale = CURRENCY_SCALES[arguments["currency"]]
    rows = []
    for item in arguments["scenarios"]:
        values = {k: literal(v) for k, v in item.items() if k != "name"}
        if any(v[0] < 0 for v in values.values()):
            raise AgentError("calculator_negative_input")
        quantity = values["quantity"]
        variable = binary("multiply", quantity, values["variable_cost_per_unit"])
        total = binary("add", values["fixed_cost_total"], variable)
        row = {"name": item["name"], "variable_cost": display(variable, scale),
               "total_cost": display(total, scale), "unit_cost": ratio(total, quantity, scale),
               "revenue": None, "profit": None, "gross_margin_percent": None, "markup_percent": None}
        if "selling_price_per_unit" in values:
            revenue = binary("multiply", quantity, values["selling_price_per_unit"])
            profit = binary("subtract", revenue, total)
            row.update(revenue=display(revenue, scale), profit=display(profit, scale),
                       gross_margin_percent=ratio(profit, revenue, 6, percent=True),
                       markup_percent=ratio(profit, total, 6, percent=True))
        rows.append(row)
    return {"currency": arguments["currency"], "quantity_unit": "item", "scenarios": rows}


def execute(operation, arguments):
    check_input(operation, arguments)
    try:
        with localcontext(Context(prec=256)) as context:
            context.traps[Inexact] = True
            if operation == "calculate":
                value, unit = evaluate(arguments["expression"])
                if unit != arguments["unit"]:
                    raise AgentError("calculator_unit_mismatch")
                result = {"unit": unit, "number": display(value, arguments["scale"])}
            else:
                result = scenarios(arguments)
            receipt = {"contract": "decimal-v1", "operation": operation,
                       "input_digest": hashlib.sha256(encode(arguments).encode("utf-8")).hexdigest(),
                       "result": result}
            check_output(operation, receipt)
            return receipt
    except DecimalException:
        raise AgentError("calculator_budget_exhausted") from None
