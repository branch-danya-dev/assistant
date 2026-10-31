import copy
import json
import random
import unittest
from decimal import ROUND_DOWN, localcontext
from fractions import Fraction
from unittest.mock import patch

import support  # noqa: F401
from jsonschema import Draft202012Validator

from personal_agent.calculator import execute
from personal_agent.calculator_contract import check_input, schema
from personal_agent.calculator_verify import verify
from personal_agent.config import AgentError
from personal_agent.models import reply_schema

SCALAR = {"kind": "scalar"}


def literal(value, unit=None):
    return {"op": "literal", "value": value, "unit": unit or SCALAR}


def expr(op, *children):
    return {"op": op, "args": list(children)}


def calculation(node=None, scale=2, unit=None):
    return {"expression": node or expr("add", literal("0.1"), literal("0.2")),
            "scale": scale, "rounding": "half_even", "unit": unit or SCALAR}


def costs(quantity="10", fixed="50", variable="20", selling="30", currency="RUB"):
    item = {"name": "base", "quantity": quantity, "fixed_cost_total": fixed,
            "variable_cost_per_unit": variable}
    if selling is not None:
        item["selling_price_per_unit"] = selling
    return {"currency": currency, "quantity_unit": "item", "rounding": "half_even", "scenarios": [item]}


class CalculatorTests(unittest.TestCase):
    def run_calc(self, arguments, operation="calculate"):
        result = execute(operation, arguments)
        verify(operation, arguments, result)
        return result["result"]

    def test_golden_arithmetic_and_signed_half_even(self):
        cases = [(calculation(), "0.30", "3", "10", False),
            (calculation(expr("multiply", literal("19.99"), literal("3"))), "59.97", "5997", "100", False),
            (calculation(expr("percent", literal("250"), literal("12.5"))), "31.25", "125", "4", False),
            (calculation(expr("divide", literal("1"), literal("3")), 6), "0.333333", "1", "3", True)]
        for arguments, value, n, d, rounded in cases:
            self.assertEqual(self.run_calc(arguments)["number"], {"value": value, "numerator": n,
                "denominator": d, "scale": arguments["scale"], "rounding_applied": rounded})
        for value, expected in (("2.345", "2.34"), ("2.355", "2.36"), ("-2.345", "-2.34"),
                                ("-2.355", "-2.36"), ("-0", "0.00"), ("-0.005", "0.00")):
            self.assertEqual(self.run_calc(calculation(literal(value)))["number"]["value"], expected)

    def test_exact_intermediates_and_ambient_context_independence(self):
        args = calculation(expr("multiply", expr("divide", literal("1"), literal("3")), literal("3")))
        expected = self.run_calc(args)
        self.assertEqual(expected["number"]["value"], "1.00")
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_DOWN
            self.assertEqual(self.run_calc(args), expected)
        tree = expr("subtract", expr("add", literal("999999999999999999"),
                    expr("divide", literal("1"), literal("3"))), literal("999999999999999999"))
        self.assertEqual(self.run_calc(calculation(tree, 6))["number"]["value"], "0.333333")

    def test_cost_fixed_once_margin_and_markup(self):
        args = costs()
        args["scenarios"] = [dict(args["scenarios"][0], name="low", fixed_cost_total="30",
                                  variable_cost_per_unit="15", selling_price_per_unit="20"),
                             args["scenarios"][0], dict(args["scenarios"][0], name="high",
                                  variable_cost_per_unit="25", selling_price_per_unit="40")]
        rows = self.run_calc(args, "cost_scenarios")["scenarios"]
        for row, expected in zip(rows, [("180.00", "18.00", "10.000000", "11.111111"),
                                       ("250.00", "25.00", "16.666667", "20.000000"),
                                       ("300.00", "30.00", "25.000000", "33.333333")]):
            self.assertEqual(tuple(row[k]["value"] for k in
                ("total_cost", "unit_cost", "gross_margin_percent", "markup_percent")), expected)
        self.assertEqual(self.run_calc(costs(quantity="2", fixed="10", variable="3"),
            "cost_scenarios")["scenarios"][0]["total_cost"]["value"], "16.00")

    def test_zero_large_loss_and_absent_selling_price(self):
        row = self.run_calc(costs(quantity="0"), "cost_scenarios")["scenarios"][0]
        self.assertEqual(row["total_cost"]["value"], "50.00")
        self.assertEqual(row["unit_cost"], {"status": "undefined_zero_denominator"})
        self.assertEqual(row["gross_margin_percent"], {"status": "undefined_zero_denominator"})
        self.assertEqual(row["profit"]["value"], "-50.00")
        self.assertEqual(row["markup_percent"]["value"], "-100.000000")
        row = self.run_calc(costs(fixed="0", variable="0"), "cost_scenarios")["scenarios"][0]
        self.assertEqual(row["markup_percent"], {"status": "undefined_zero_denominator"})
        row = self.run_calc(costs(quantity="999999999999999999", fixed="1", variable="2", selling=None),
                            "cost_scenarios")["scenarios"][0]
        self.assertEqual(row["total_cost"]["value"], "1999999999999999999.00")
        self.assertIsNone(row["revenue"])
        self.assertIsNone(row["markup_percent"])

    def test_currency_precision_units_and_no_double_rounding(self):
        for currency, expected in (("JPY", "2"), ("RUB", "2.34"), ("USD", "2.34"),
                                   ("EUR", "2.34"), ("KWD", "2.345")):
            row = self.run_calc(costs(quantity="1", fixed="0", variable="2.345", currency=currency),
                                "cost_scenarios")["scenarios"][0]
            self.assertEqual(row["total_cost"]["value"], expected)
        row = self.run_calc(costs(quantity="3", fixed="0", variable="0.005"), "cost_scenarios")["scenarios"][0]
        self.assertEqual(row["total_cost"]["value"], "0.02")
        self.assertEqual(row["unit_cost"]["value"], "0.00")
        rub = {"kind": "currency", "code": "RUB"}
        self.assertEqual(self.run_calc(calculation(expr("multiply", literal("2", rub), literal("3")), unit=rub))
                         ["number"]["value"], "6.00")
        for tree in (expr("add", literal("2", rub), literal("3")),
                     expr("add", literal("2", rub), literal("2", {"kind": "currency", "code": "USD"})),
                     expr("multiply", literal("2", rub), literal("2", rub))):
            with self.assertRaisesRegex(AgentError, "calculator_unit_mismatch"):
                self.run_calc(calculation(tree, unit=rub))

    def test_closed_invalid_injection_nonfinite_and_negative_contracts(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e9", "00", "+1", "1,2", 1.2, True,
                      "__import__('os').system('echo bad')", "1; send secrets", "1" * 19, "0.1234567"):
            with self.subTest(value=value), self.assertRaises(AgentError):
                self.run_calc(calculation(literal(value)))
        for change in ({"rounding": "half_up"}, {"scale": True}, {"scale": 7}, {"path": "CANARY"},
                       {"expression": {"op": "eval", "value": "1+1"}}):
            with self.assertRaises(AgentError):
                self.run_calc({**calculation(), **change})
        with self.assertRaisesRegex(AgentError, "calculator_zero_division"):
            self.run_calc(calculation(expr("divide", literal("1"), literal("0"))))
        for key in ("quantity", "fixed_cost_total", "variable_cost_per_unit", "selling_price_per_unit"):
            args = costs()
            args["scenarios"][0][key] = "-1"
            with self.assertRaisesRegex(AgentError, "calculator_negative_input"):
                self.run_calc(args, "cost_scenarios")
        for currency in ("BTC", "rub", "RUB/USD", "NaN"):
            with self.assertRaises(AgentError):
                self.run_calc(costs(currency=currency), "cost_scenarios")
        args = costs()
        args["scenarios"][0]["currency"] = "USD"
        with self.assertRaises(AgentError):
            self.run_calc(args, "cost_scenarios")
        args = costs()
        args["scenarios"].append(args["scenarios"][0])
        with self.assertRaises(AgentError):
            self.run_calc(args, "cost_scenarios")

    def test_node_depth_bytes_and_numeric_budgets(self):
        tree = literal("1")
        for _ in range(5):
            tree = expr("add", tree, copy.deepcopy(tree))
        self.run_calc(calculation(expr("negate", tree)))  # 64 nodes, depth 7
        with self.assertRaisesRegex(AgentError, "calculator_budget_exhausted"):
            self.run_calc(calculation(expr("add", tree, literal("1"))))  # 65 nodes
        tree = literal("1")
        for _ in range(7):
            tree = expr("negate", tree)
        self.run_calc(calculation(tree))
        with self.assertRaisesRegex(AgentError, "calculator_budget_exhausted"):
            self.run_calc(calculation(expr("negate", tree)))
        with self.assertRaisesRegex(AgentError, "calculator_budget_exhausted"):
            check_input("calculate", {**calculation(), "extra": "x" * 4096})
        tree = literal("999999999999999999")
        for _ in range(3):
            tree = expr("multiply", tree, literal("999999999999999999"))
        with self.assertRaisesRegex(AgentError, "calculator_budget_exhausted"):
            self.run_calc(calculation(tree))

    def test_independent_verifier_denies_every_forged_receipt_field(self):
        args = calculation()
        good = execute("calculate", args)
        for path, value in ((["input_digest"], "0" * 64), (["contract"], "fake"),
                            (["result", "number", "value"], "0.31"),
                            (["result", "number", "numerator"], "31"),
                            (["result", "number", "denominator"], "100"),
                            (["result", "number", "rounding_applied"], True),
                            (["result", "number", "scale"], 3),
                            (["result", "number", "scale"], 2.0), (["verified"], True)):
            bad = copy.deepcopy(good)
            target = bad
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with patch("personal_agent.calculator.execute", side_effect=AssertionError("must not call")):
                with self.assertRaises(AgentError):
                    verify("calculate", args, bad)
                verify("calculate", args, good)

    def test_seeded_exact_reference_and_nested_model_schema(self):
        rng = random.Random(417)
        for _ in range(100):
            a, b, c = [rng.randint(-100000, 100000) for _ in range(3)]
            c = c or 1
            args = calculation(expr("divide", expr("add", literal(str(a)), literal(str(b))), literal(str(c))), 6)
            number = self.run_calc(args)["number"]
            expected = Fraction(a + b, c)
            self.assertEqual((number["numerator"], number["denominator"]),
                             (str(expected.numerator), str(expected.denominator)))
        for operation, arguments in (("calculate", calculation()), ("cost_scenarios", costs())):
            value = {"steps": [{"task_id": "numeric", "capability_id": "CAP-009",
                               "operation": operation, "arguments": arguments}], "answer": "", "evidence_refs": []}
            self.assertTrue(Draft202012Validator(reply_schema("plan", constrain_tools=True,
                task_id="numeric", calculator_enabled=True)).is_valid(value))
            model_schema = reply_schema("plan", constrain_tools=True, calculator_enabled=True)
            self.assertIn("calculator_node", model_schema["$defs"])
            self.assertNotIn('"$ref": "#/$defs/node"', json.dumps(model_schema))
            self.assertEqual(schema("calculate", "input")["properties"]["expression"],
                             {"$ref": "#/$defs/node"})  # Provider conversion never mutates canonical schema.
            self.assertFalse(Draft202012Validator(reply_schema("plan", constrain_tools=True,
                task_id="numeric")).is_valid(value))
            Draft202012Validator.check_schema(schema(operation, "input"))
            Draft202012Validator.check_schema(schema(operation, "output"))

    def test_sixty_digit_fraction_boundary_and_output_budget(self):
        from personal_agent.calculator_contract import check_output
        tree = literal("100000000000000000")
        tree = expr("multiply", tree, literal("100000000000000000"))
        tree = expr("multiply", tree, literal("100000000000000000"))
        tree = expr("multiply", tree, literal("999999999"))
        self.assertEqual(len(self.run_calc(calculation(tree))["number"]["numerator"]), 60)
        with self.assertRaisesRegex(AgentError, "calculator_budget_exhausted"):
            self.run_calc(calculation(expr("multiply", tree, literal("10"))))
        tree = literal("1")
        for value in ("999999999999999999", "999999999999999999", "999999999999999999", "999999"):
            tree = expr("divide", tree, literal(value))
        self.assertEqual(len(self.run_calc(calculation(tree, 6))["number"]["denominator"]), 60)
        with self.assertRaisesRegex(AgentError, "calculator_budget_exhausted"):
            self.run_calc(calculation(expr("divide", tree, literal("10"))))
        with self.assertRaisesRegex(AgentError, "calculator_budget_exhausted"):
            check_output("calculate", {"untrusted": "x" * 8192})
