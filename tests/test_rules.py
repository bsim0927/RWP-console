"""resolve -> derive -> reduce_gates: turning judge probabilities into a disposition."""

import unittest

import yaml

from sg.gate_store import validate
from sg.pipeline import ROOT, derive, load_gates, reduce_gates, resolve

POLICY = yaml.safe_load((ROOT / "policy.yaml").read_text())
GATES = {g["id"]: g for g in load_gates()}


def bool_q(qid):
    return {"id": qid, "type": "bool", "q": "?"}


class Resolve(unittest.TestCase):
    def test_bool_is_probability_of_true(self):
        env, conf = resolve([bool_q("ok")], {"ok": {"true": 0.2, "false": 0.8}})
        self.assertEqual(env, {"ok": 0.2})
        self.assertEqual(conf, {"ok": 0.8})  # confidence is the top answer's probability

    def test_bool_without_true_key_is_zero(self):
        env, _ = resolve([bool_q("ok")], {"ok": {"false": 1.0}})
        self.assertEqual(env["ok"], 0.0)

    def test_choice_gives_top_option_and_its_probability(self):
        q = {"id": "basis", "type": "choice", "options": ["net", "gross"]}
        env, conf = resolve([q], {"basis": {"net": 0.3, "gross": 0.7}})
        self.assertEqual(env, {"basis": "gross", "basis_p": 0.7})
        self.assertEqual(conf, {"basis": 0.7})


class Derive(unittest.TestCase):
    def test_first_matching_rule_wins(self):
        rules = [{"if": "x > 0.5", "then": "A"}, {"if": "x > 0.1", "then": "B"}, {"then": "C"}]
        self.assertEqual(derive(rules, {"x": 0.9}), "A")
        self.assertEqual(derive(rules, {"x": 0.3}), "B")
        self.assertEqual(derive(rules, {"x": 0.0}), "C")

    def test_no_match_is_incomplete(self):
        self.assertEqual(derive([{"if": "x > 0.5", "then": "A"}], {"x": 0.1}), "Incomplete")

    def test_thresholds_are_inclusive_as_written(self):
        rules = GATES["investor_eligibility"]["derive"]
        self.assertEqual(derive(rules, {"sufficient": 0.7, "qp_only": 0.7}), "Fail")
        self.assertEqual(derive(rules, {"sufficient": 0.69, "qp_only": 0.9}), "Incomplete")
        self.assertEqual(derive(rules, {"sufficient": 0.9, "qp_only": 0.69}), "Pass")

    def test_cost_gate_without_a_percentage(self):
        rules = GATES["total_annual_cost"]["derive"]
        self.assertEqual(derive(rules, {"sufficient": 0.9, "total_pct": None}), "Pass")
        self.assertEqual(derive(rules, {"sufficient": 0.9, "total_pct": 3.5}), "Route with disclosure")
        self.assertEqual(derive(rules, {"sufficient": 0.9, "total_pct": 3.0}), "Pass")

    def test_unguarded_none_comparison_raises(self):
        # Why the shipped rules say "total_pct is not None and ...". validate() does not catch this.
        with self.assertRaises(TypeError):
            derive([{"if": "total_pct > 3.0", "then": "A"}], {"total_pct": None})

    def test_track_record_needs_net_basis(self):
        rules = GATES["track_record"]["derive"]
        self.assertEqual(derive(rules, {"basis": "net", "basis_p": 0.9, "sufficient": 0.8}), "Pass")
        self.assertEqual(derive(rules, {"basis": "gross", "basis_p": 0.9, "sufficient": 0.8}), "Fail")
        self.assertEqual(derive(rules, {"basis": "net", "basis_p": 0.9, "sufficient": 0.5}), "Fail")

    def test_no_builtins_in_conditions(self):
        with self.assertRaises(NameError):
            derive([{"if": "len('x') > 0", "then": "A"}], {})


class ShippedGates(unittest.TestCase):
    def test_every_gate_validates(self):
        for path in sorted((ROOT / "gates").glob("*.yaml")):
            with self.subTest(gate=path.name):
                err, _ = validate(yaml.safe_load(path.read_text()), own_file=path.name)
                self.assertEqual(err, [])


class Reduce(unittest.TestCase):
    def r(self, *results, review=()):
        return [{"result": res, "review": i in review} for i, res in enumerate(results)]

    def test_all_pass(self):
        self.assertEqual(reduce_gates(POLICY, self.r("Pass", "Pass"))[0], "Coverable, subject to conditions")

    def test_fail_alone(self):
        self.assertTrue(reduce_gates(POLICY, self.r("Pass", "Fail"))[0].startswith("Reviewed and not covered"))

    def test_incomplete_outranks_fail(self):
        d, flags = reduce_gates(POLICY, self.r("Fail", "Incomplete"))
        self.assertTrue(d.startswith("Under review (gates that cannot"))
        self.assertTrue(flags["any_fail"] and flags["any_incomplete"])

    def test_not_yet_run_counts_as_incomplete(self):
        self.assertTrue(reduce_gates(POLICY, self.r("Pass", "Not yet run"))[0].startswith("Under review (gates"))

    def test_review_outranks_everything(self):
        self.assertTrue(
            reduce_gates(POLICY, self.r("Fail", "Incomplete", review=(0,)))[0].startswith("Under review (analyst")
        )

    def test_no_rule_matches(self):
        self.assertEqual(
            reduce_gates({"rules": [{"when": "any_fail", "disposition": "X"}]}, self.r("Pass"))[0], "Under review"
        )


if __name__ == "__main__":
    unittest.main()
