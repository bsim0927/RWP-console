"""resolve -> derive -> reduce_gates: turning judge probabilities into a disposition."""

import unittest

import pytest
import yaml

from sg import gate_store, store
from sg.gate_store import validate
from sg.pipeline import code_checks, derive, load_gates, raise_flags, reduce_gates, resolve


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


@pytest.mark.usefixtures("db")
class Derive(unittest.TestCase):
    def setUp(self):
        self.gates = {g["id"]: g for g in load_gates()}  # the seeded, shipped gates

    def test_first_matching_rule_wins(self):
        rules = [{"if": "x > 0.5", "then": "A"}, {"if": "x > 0.1", "then": "B"}, {"then": "C"}]
        self.assertEqual(derive(rules, {"x": 0.9}), "A")
        self.assertEqual(derive(rules, {"x": 0.3}), "B")
        self.assertEqual(derive(rules, {"x": 0.0}), "C")

    def test_no_match_is_incomplete(self):
        self.assertEqual(derive([{"if": "x > 0.5", "then": "A"}], {"x": 0.1}), "Incomplete")

    def outcome(self, gate, **env):
        g = self.gates[gate]
        full = {"total_pct": None, "fees_disagree": False, **env}
        return derive(g["derive"], full), raise_flags(g.get("flags"), full)

    def test_qp_only_passes_with_a_flag(self):
        # Decision A2: a QP-only fund moves forward, tagged for the QP lineup.
        e = {"sufficient": 0.9, "institutions_only": 0.1}
        self.assertEqual(self.outcome("investor_eligibility", **e, qp_only=0.7), ("Pass", ["QP-only"]))
        self.assertEqual(self.outcome("investor_eligibility", **e, qp_only=0.69), ("Pass", []))

    def test_only_institutions_only_fails_eligibility(self):
        # Decision A4. Thresholds are inclusive as written.
        e = {"sufficient": 0.9, "qp_only": 0.9}
        self.assertEqual(self.outcome("investor_eligibility", **e, institutions_only=0.7), ("Fail", []))
        self.assertEqual(
            self.outcome("investor_eligibility", sufficient=0.69, qp_only=0.9, institutions_only=0.9),
            ("Incomplete", []),
        )

    def test_cost_never_fails_and_has_no_threshold(self):
        # Decisions B1 and B6: Pass or Incomplete only.
        self.assertEqual(self.outcome("total_annual_cost", sufficient=0.9, total_pct=9.5), ("Pass", []))
        self.assertEqual(self.outcome("total_annual_cost", sufficient=0.5, total_pct=1.0), ("Incomplete", []))

    def test_cost_documents_disagreeing_is_incomplete(self):
        self.assertEqual(
            self.outcome("total_annual_cost", sufficient=0.9, fees_disagree=True),
            ("Incomplete", ["Fee rates disagree across documents"]),
        )

    def test_affiliated_administrator_is_incomplete_with_a_flag(self):
        # Decision C1; custody and pricing are the analyst's checks (C3).
        e = {"sufficient": 0.9, "has_valuation_policy": 0.9}
        result, flags = self.outcome("operability", **e, affiliated_admin=0.8)
        self.assertEqual(result, "Incomplete")
        self.assertEqual(flags, ["Affiliated administrator"])
        checks = [k["id"] for k in self.gates["operability"]["checks"]]
        self.assertEqual(checks, ["custody", "pricing"])
        self.assertEqual(self.outcome("operability", **e, affiliated_admin=0.1)[0], "Pass")

    def test_missing_valuation_policy_is_incomplete(self):
        # Decision C2.
        e = {"sufficient": 0.9, "affiliated_admin": 0.1}
        self.assertEqual(self.outcome("operability", **e, has_valuation_policy=0.2)[0], "Incomplete")

    def test_track_record_never_fails(self):
        # Decisions D1 to D3: only a net, fund-level record of this manager at this fee load passes.
        good = {"sufficient": 0.8, "basis": "net", "basis_p": 0.9, "fund_level": 0.9}
        good |= {"prior_employer": 0.1, "lighter_fees": 0.1}
        self.assertEqual(self.outcome("track_record", **good), ("Pass", []))
        pro_forma = ["RWP pro forma possible"]
        self.assertEqual(self.outcome("track_record", **{**good, "basis": "gross"}), ("Incomplete", pro_forma))
        self.assertEqual(self.outcome("track_record", **{**good, "fund_level": 0.2}), ("Incomplete", pro_forma))
        self.assertEqual(self.outcome("track_record", **{**good, "prior_employer": 0.9}), ("Incomplete", pro_forma))
        self.assertEqual(
            self.outcome("track_record", **{**good, "lighter_fees": 0.9}),
            ("Incomplete", ["Restate the record at this fund's fees"]),
        )
        self.assertEqual(
            self.outcome("track_record", **{**good, "sufficient": 0.1, "basis": "not_stated"}), ("Incomplete", [])
        )

    def test_unguarded_none_comparison_raises(self):
        # Why rules on total_pct must say "total_pct is not None and ...". validate() does not catch this.
        with self.assertRaises(TypeError):
            derive([{"if": "total_pct > 3.0", "then": "A"}], {"total_pct": None})

    def test_no_builtins_in_conditions(self):
        with self.assertRaises(NameError):
            derive([{"if": "len('x') > 0", "then": "A"}], {})


class FeeChecks(unittest.TestCase):
    GATE = {
        "extractor": {
            "fields": [
                {"name": "management_fee", "recurring": True},
                {"name": "servicing_fee", "recurring": True},
                {"name": "incentive_fee"},
            ]
        }
    }

    def fact(self, field, value):
        return {"field": field, "value": value}

    def test_counted_layers_are_summed_once(self):
        facts = [
            self.fact("management_fee", "1.25% of NAV"),
            self.fact("management_fee", "1.25 %"),
            self.fact("servicing_fee", "0.50%"),
            self.fact("incentive_fee", "12.5% over 6%"),
        ]
        self.assertEqual(
            code_checks(self.GATE, facts), {"total_pct": 1.75, "fees_disagree": False, "fee_conflicts": {}}
        )

    def test_two_rates_for_one_layer_is_a_disagreement(self):
        # e.g. the term sheet and the PPM quote different management fees.
        facts = [self.fact("management_fee", "1.35%"), self.fact("management_fee", "1.55%")]
        self.assertEqual(
            code_checks(self.GATE, facts),
            {"total_pct": None, "fees_disagree": True, "fee_conflicts": {"management_fee": [1.35, 1.55]}},
        )

    def test_no_counted_rate_means_no_total(self):
        facts = [self.fact("management_fee", "see PPM")]
        self.assertEqual(code_checks(self.GATE, facts)["total_pct"], None)


class Flags(unittest.TestCase):
    def test_every_holding_flag_in_order_and_unconditional_always(self):
        flags = [{"if": "x > 0.5", "flag": "A"}, {"flag": "B"}, {"if": "x > 0.9", "flag": "C"}]
        self.assertEqual(raise_flags(flags, {"x": 0.7}), ["A", "B"])
        self.assertEqual(raise_flags(None, {}), [])


@pytest.mark.usefixtures("db")
class ShippedGates(unittest.TestCase):
    def test_every_gate_validates(self):
        for g in gate_store.current():
            with self.subTest(gate=g["file"]):
                err, _ = validate(yaml.safe_load(g["text"]), own_file=g["file"])
                self.assertEqual(err, [])

    def test_every_automated_gate_has_the_same_shape(self):
        for g in load_gates():
            if g.get("static_result"):
                continue
            with self.subTest(gate=g["id"]):
                required = {"id", "version", "extractor", "questions", "derive", "flags"}
                self.assertLessEqual(required, set(g))
                self.assertLessEqual(set(g), required | {"checks", "review_if"})
                self.assertLessEqual({r["then"] for r in g["derive"]}, set(gate_store.RESULTS))

    def test_fields_that_keep_a_gate_open_say_what_to_ask_for(self):
        asks = {
            g["id"]: [f["name"] for f in g["extractor"]["fields"] if f.get("ask")]
            for g in load_gates()
            if g.get("extractor")
        }
        self.assertEqual(
            asks,
            {
                "investor_eligibility": ["investor_standard"],
                "total_annual_cost": ["management_fee"],
                "operability": ["administrator", "auditor", "valuation_policy"],
                "track_record": ["net_return"],
            },
        )

    def test_the_seeded_gates_are_kept_in_history(self):
        # The screen-decisions migration replaced four gates; their seeded versions stay restorable.
        kept = {(h["id"], h["version"]) for h in gate_store.history()}
        for gid in ("investor_eligibility", "total_annual_cost", "operability", "track_record"):
            self.assertIn((gid, 2), kept)
        for g in gate_store.current():
            with self.subTest(gate=g["id"]):
                self.assertEqual(yaml.safe_load(g["text"])["version"], g["version"])  # the row and its YAML agree


@pytest.mark.usefixtures("db")
class Validate(unittest.TestCase):
    GATE = {
        "id": "x_gate",
        "extractor": {"keywords": ["k"], "fields": [{"name": "f"}]},
        "questions": [{"id": "ok", "type": "bool", "q": "?"}],
    }

    def errors(self, **over):
        return validate({**self.GATE, **over})[0]

    def test_results_are_pass_fail_or_incomplete(self):
        self.assertEqual(self.errors(derive=[{"then": "Pass"}]), [])
        err = self.errors(derive=[{"if": "ok > 0.5", "then": "Route with disclosure"}, {"then": "Pass"}])
        self.assertEqual(err, ["rule 1: the result must be Pass, Fail or Incomplete; say anything more with a flag"])

    def test_flags_need_text_and_known_names(self):
        err = self.errors(derive=[{"then": "Pass"}], flags=[{"if": "ok > 0.5"}, {"if": "nope", "flag": "N"}])
        self.assertEqual(err[0], "flag 1 needs its text")
        self.assertTrue(err[1].startswith("flag 2: unknown name nope"))
        self.assertEqual(self.errors(derive=[{"then": "Pass"}], flags=[{"if": "fees_disagree", "flag": "F"}]), [])

    def test_manual_checks_need_unique_ids_and_questions(self):
        ok = [{"id": "custody", "q": "Can it be custodied?"}]
        self.assertEqual(self.errors(derive=[{"then": "Pass"}], checks=ok), [])
        self.assertEqual(
            self.errors(derive=[{"then": "Pass"}], checks=ok + ok),
            ["every manual check needs a unique id in lowercase_with_underscores"],
        )
        self.assertEqual(
            self.errors(derive=[{"then": "Pass"}], checks=[{"id": "x", "q": " "}]),
            ["every manual check needs its question"],
        )


@pytest.mark.usefixtures("db")
class Reduce(unittest.TestCase):
    def setUp(self):
        self.policy = yaml.safe_load(store.policy()["yaml"])  # the seeded, shipped policy

    def r(self, *results, review=()):
        return [{"result": res, "review": i in review} for i, res in enumerate(results)]

    def test_all_pass(self):
        self.assertEqual(reduce_gates(self.policy, self.r("Pass", "Pass"))[0], "Coverable, subject to conditions")

    def test_fail_alone(self):
        self.assertTrue(reduce_gates(self.policy, self.r("Pass", "Fail"))[0].startswith("Reviewed and not covered"))

    def test_incomplete_outranks_fail(self):
        d, flags = reduce_gates(self.policy, self.r("Fail", "Incomplete"))
        self.assertTrue(d.startswith("Under review (gates that cannot"))
        self.assertTrue(flags["any_fail"] and flags["any_incomplete"])

    def test_not_yet_run_counts_as_incomplete(self):
        self.assertTrue(reduce_gates(self.policy, self.r("Pass", "Not yet run"))[0].startswith("Under review (gates"))

    def test_review_outranks_everything(self):
        self.assertTrue(
            reduce_gates(self.policy, self.r("Fail", "Incomplete", review=(0,)))[0].startswith("Under review (analyst")
        )

    def test_no_rule_matches(self):
        self.assertEqual(
            reduce_gates({"rules": [{"when": "any_fail", "disposition": "X"}]}, self.r("Pass"))[0], "Under review"
        )


if __name__ == "__main__":
    unittest.main()
