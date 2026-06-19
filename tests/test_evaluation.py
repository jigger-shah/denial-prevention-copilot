"""
Tests for the v1.4 golden-set evaluation framework (evaluation/).

No real Anthropic API calls happen here — run_evaluation() defaults to
live=False, which patches agents.orchestrator.validate_coverage and
validate_coding to return [] before calling run_review(). The rule layer
(rules/) runs unmodified and for real against each golden claim.
"""

from unittest.mock import patch

from rules.models import Citation, Finding
from evaluation.metrics import (
    LABEL_CATEGORY,
    compute_prf,
    normalize_finding,
    normalize_findings,
)
from evaluation.harness import load_golden_claims, run_evaluation

_CITATION = Citation(source="X", doc_id="X", section="X", edition="X")


def _finding(rule: str, severity: str = "HIGH") -> Finding:
    return Finding(
        rule=rule,
        severity=severity,
        issue="issue",
        recommendation="fix it",
        citation=_CITATION,
        confidence=0.9,
    )


# ---------------------------------------------------------------------------
# Label normalization
# ---------------------------------------------------------------------------

class TestLabelNormalization:
    def test_rule_layer_labels_map_correctly(self):
        assert normalize_finding(_finding("npi_invalid")) == "invalid_npi"
        assert normalize_finding(_finding("ncci_ptp")) == "ncci_conflict"
        assert normalize_finding(_finding("mue_unit_limit")) == "mue_limit"
        assert normalize_finding(_finding("dx_procedure_conflict")) == "diagnosis_procedure_mismatch"
        assert normalize_finding(_finding("missing_modifier_25")) == "missing_modifier_25"

    def test_agent_layer_labels_map_correctly(self):
        assert normalize_finding(_finding("coverage_validation")) == "coverage_medical_necessity"
        assert normalize_finding(_finding("coding_validation")) == "coding_defensibility"

    def test_npi_registry_has_no_normalized_label(self):
        # npi_registry only fires after a live NPPES lookup; the golden set
        # deliberately never triggers it, and normalization treats it as
        # unrecognized rather than guessing a label for it.
        assert normalize_finding(_finding("npi_registry")) is None

    def test_unknown_rule_normalizes_to_none(self):
        assert normalize_finding(_finding("some_future_rule")) is None

    def test_normalize_findings_returns_label_set(self):
        findings = [_finding("npi_invalid"), _finding("ncci_ptp"), _finding("npi_invalid")]
        assert normalize_findings(findings) == {"invalid_npi", "ncci_conflict"}

    def test_normalize_findings_empty_list_returns_empty_set(self):
        assert normalize_findings([]) == set()

    def test_normalize_findings_drops_unknown_rules(self):
        findings = [_finding("ncci_ptp"), _finding("npi_registry")]
        assert normalize_findings(findings) == {"ncci_conflict"}

    def test_every_label_has_a_category(self):
        for rule in ["npi_invalid", "ncci_ptp", "mue_unit_limit", "dx_procedure_conflict", "missing_modifier_25"]:
            label = normalize_finding(_finding(rule))
            assert LABEL_CATEGORY[label] == "Rule Engine"
        assert LABEL_CATEGORY["coverage_medical_necessity"] == "Coverage Agent"
        assert LABEL_CATEGORY["coding_defensibility"] == "Coding Agent"


# ---------------------------------------------------------------------------
# Precision / recall / F1
# ---------------------------------------------------------------------------

class TestComputePRF:
    def test_perfect_match(self):
        prf = compute_prf({"ncci_conflict"}, {"ncci_conflict"})
        assert (prf.true_positives, prf.false_positives, prf.false_negatives) == (1, 0, 0)
        assert prf.precision == prf.recall == prf.f1 == 1.0

    def test_false_positive_handling(self):
        # actual has an extra label not expected -> hurts precision, not recall
        prf = compute_prf({"ncci_conflict"}, {"ncci_conflict", "mue_limit"})
        assert prf.true_positives == 1
        assert prf.false_positives == 1
        assert prf.false_negatives == 0
        assert prf.precision == 0.5
        assert prf.recall == 1.0

    def test_false_negative_handling(self):
        # expected has a label actual is missing -> hurts recall, not precision
        prf = compute_prf({"ncci_conflict", "mue_limit"}, {"ncci_conflict"})
        assert prf.true_positives == 1
        assert prf.false_positives == 0
        assert prf.false_negatives == 1
        assert prf.precision == 1.0
        assert prf.recall == 0.5

    def test_empty_expected_and_empty_actual_is_a_perfect_clean_match(self):
        prf = compute_prf(set(), set())
        assert (prf.true_positives, prf.false_positives, prf.false_negatives) == (0, 0, 0)
        assert prf.precision == prf.recall == prf.f1 == 1.0

    def test_empty_expected_with_nonempty_actual_is_all_false_positives(self):
        prf = compute_prf(set(), {"ncci_conflict"})
        assert prf.false_positives == 1
        assert prf.true_positives == 0
        assert prf.precision == 0.0  # nothing correct was flagged
        assert prf.recall == 0.0     # no true positives to find

    def test_nonempty_expected_with_empty_actual_is_all_false_negatives(self):
        prf = compute_prf({"ncci_conflict"}, set())
        assert prf.false_negatives == 1
        assert prf.true_positives == 0
        assert prf.precision == 0.0  # no true positives to be precise about
        assert prf.recall == 0.0     # everything expected was missed

    def test_f1_is_harmonic_mean_of_precision_and_recall(self):
        prf = compute_prf({"a", "b"}, {"a", "c"})
        assert prf.precision == 0.5
        assert prf.recall == 0.5
        assert prf.f1 == 0.5


# ---------------------------------------------------------------------------
# Evaluation runner behavior
# ---------------------------------------------------------------------------

class TestRunEvaluation:
    def test_golden_claims_file_loads_and_has_required_fields(self):
        claims = load_golden_claims()
        assert len(claims) >= 10
        for claim in claims:
            assert "claim_id" in claim
            assert "expected_findings" in claim
            assert "cpt_codes" in claim
            assert "icd10_codes" in claim

    def test_run_evaluation_offline_makes_no_agent_calls(self):
        with patch("agents.orchestrator.validate_coverage") as mock_coverage, \
             patch("agents.orchestrator.validate_coding") as mock_coding:
            run_evaluation()
            mock_coverage.assert_not_called()
            mock_coding.assert_not_called()

    def test_run_evaluation_default_mode_is_offline(self):
        report = run_evaluation()
        assert report.mode == "offline"

    def test_run_evaluation_returns_one_result_per_claim(self):
        claims = load_golden_claims()
        report = run_evaluation(golden_claims=claims)
        assert len(report.claim_results) == len(claims)
        assert {r.claim_id for r in report.claim_results} == {c["claim_id"] for c in claims}

    def test_clean_claim_is_a_true_negative_not_a_false_positive(self):
        report = run_evaluation()
        clean = next(r for r in report.claim_results if r.expected == set())
        assert clean.actual == set()
        assert clean.prf.false_positives == 0

    def test_rule_layer_claims_score_perfectly_offline(self):
        # Claims whose expected_findings are all Rule Engine labels don't
        # depend on the mocked agents, so they should match exactly offline.
        report = run_evaluation()
        for r in report.claim_results:
            if r.expected and all(label in LABEL_CATEGORY and LABEL_CATEGORY[label] == "Rule Engine" for label in r.expected):
                assert r.actual == r.expected, r.claim_id

    def test_offline_agent_only_claim_is_a_false_negative_not_an_error(self):
        report = run_evaluation()
        agent_only = next(
            r for r in report.claim_results
            if r.expected == {"coverage_medical_necessity"}
        )
        assert agent_only.actual == set()
        assert agent_only.prf.false_negatives == 1
        assert agent_only.prf.false_positives == 0

    def test_by_category_keys_match_expected_categories(self):
        report = run_evaluation()
        assert set(report.by_category.keys()) == {"Rule Engine", "Coverage Agent", "Coding Agent"}

    def test_rule_engine_category_is_perfect_offline(self):
        # The rule layer is never mocked, so its category score is a real
        # measurement, not an artifact of offline mode.
        report = run_evaluation()
        rule_prf = report.by_category["Rule Engine"]
        assert rule_prf.precision == 1.0
        assert rule_prf.recall == 1.0

    def test_overall_metrics_are_aggregated_across_claims(self):
        report = run_evaluation()
        total_tp = sum(r.prf.true_positives for r in report.claim_results)
        total_fp = sum(r.prf.false_positives for r in report.claim_results)
        total_fn = sum(r.prf.false_negatives for r in report.claim_results)
        assert report.overall.true_positives == total_tp
        assert report.overall.false_positives == total_fp
        assert report.overall.false_negatives == total_fn

    def test_run_evaluation_accepts_custom_claim_list(self):
        custom_claims = [{
            "claim_id": "TEST-CUSTOM-001",
            "payer": "Test Payer",
            "npi": "",
            "cpt_codes": ["99213"],
            "icd10_codes": ["J06.9"],
            "modifiers": [],
            "units": {},
            "expected_findings": [],
        }]
        report = run_evaluation(golden_claims=custom_claims)
        assert len(report.claim_results) == 1
        assert report.claim_results[0].claim_id == "TEST-CUSTOM-001"
