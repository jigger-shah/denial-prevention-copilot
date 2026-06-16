"""
Tests for rules/ncci_loader.py and the updated rules/ncci.py file-backed lookup.

Test strategy:
  - Loader tests use a small xlsx fixture built programmatically (avoids 54-second
    real file load in the test suite). Real files are only touched by integration
    tests that explicitly opt in.
  - Rule behavior tests monkeypatch ncci_loader.load_ncci_ptp_edits to return a
    small fixture dict — no file I/O needed.
  - Each test clears the lru_cache via ncci_loader._clear_ncci_cache() to prevent
    cross-test contamination.
"""

from __future__ import annotations

import pytest

from rules import ncci_loader
from rules.ncci import check_ncci_pairs, _SYNTHETIC_EDITS
from rules.models import ClaimIn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_claim(**overrides) -> ClaimIn:
    base = dict(
        claim_id="TEST-001",
        payer="Medicare",
        npi="1234567890",
        cpt_codes=["80053", "80048"],
        icd10_codes=["I10"],
        modifiers=[],
        place_of_service="11",
        units={"80053": 1, "80048": 1},
    )
    base.update(overrides)
    return ClaimIn(**base)


def _fixture_loader(*args, **kwargs):
    return _FIXTURE_TABLE


_FIXTURE_TABLE = {
    ("80053", "80048"): {
        "modifier": "0",
        "source_file": "ccipra-v322r0-f4.xlsx",
        "pair_effective_date": "20000701",
    },
    ("99215", "99214"): {
        "modifier": "1",
        "source_file": "ccipra-v322r0-f1.xlsx",
        "pair_effective_date": "20050101",
    },
    ("12345", "67890"): {
        "modifier": "9",
        "source_file": "ccipra-v322r0-f2.xlsx",
        "pair_effective_date": "20100101",
    },
}


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the NCCI lru_cache before every test to prevent cross-test contamination."""
    ncci_loader._clear_ncci_cache()
    yield
    ncci_loader._clear_ncci_cache()


# ---------------------------------------------------------------------------
# Excel fixture builder
# ---------------------------------------------------------------------------

@pytest.fixture
def ncci_fixture_dir(tmp_path):
    """
    Create a minimal NCCI xlsx fixture matching CMS file structure.
    6-row header + 4 data rows (2 active, 1 deleted, 1 modifier-1).
    """
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    # 6-row header block (mirrors CMS format)
    ws.append(["CPT only copyright 2025 American Medical Association. All rights reserved.", None, None, None, None, None, None])
    ws.append(["Column1/Column2 Edits", None, None, None, None, None, None])
    ws.append(["Column 1", "Column 2", "*=in existence prior to 1996", "Effective Date", "Deletion Date", "Modifier", "PTP Edit Rationale"])
    ws.append([None, None, None, None, None, "0=not allowed", None])
    ws.append([None, None, None, None, "*=no data", "1=allowed", None])
    ws.append([None, None, None, None, None, "9=not applicable", None])
    # Data rows: (col1, col2, prior_1996, eff_date, del_date, modifier, rationale)
    ws.append([80053, "80048", None, 20000701, "*", 0, "CPT Manual"])    # active, mod 0
    ws.append([99215, "99214", None, 20050101, "*", 1, "CPT Manual"])    # active, mod 1
    ws.append([12345, "67890", None, 20100101, "*", 9, "CPT Manual"])    # active, mod 9
    ws.append([11111, "22222", None, 20010101, 20231231, 0, "CPT Manual"])  # deleted
    wb.save(tmp_path / "ccipra-v322r0-fixture.xlsx")
    return str(tmp_path)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

class TestDiscoverNcciFiles:
    def test_finds_four_real_xlsx_files(self):
        """Real NCCI directory should contain exactly 4 xlsx files."""
        files = ncci_loader.discover_ncci_files("data/reference/ncci")
        assert len(files) == 4
        for f in files:
            assert f.endswith(".xlsx")

    def test_returns_sorted_list(self):
        files = ncci_loader.discover_ncci_files("data/reference/ncci")
        assert files == sorted(files)

    def test_missing_directory_returns_empty(self):
        files = ncci_loader.discover_ncci_files("data/reference/nonexistent_dir")
        assert files == []

    def test_fixture_dir_returns_one_file(self, ncci_fixture_dir):
        files = ncci_loader.discover_ncci_files(ncci_fixture_dir)
        assert len(files) == 1
        assert files[0].endswith(".xlsx")


# ---------------------------------------------------------------------------
# Loader: reads xlsx files and builds lookup dict
# ---------------------------------------------------------------------------

class TestLoadNcciPtpEdits:
    def test_returns_dict_from_fixture(self, ncci_fixture_dir):
        table = ncci_loader.load_ncci_ptp_edits(ncci_fixture_dir)
        assert isinstance(table, dict)
        assert len(table) > 0

    def test_active_pair_in_fixture(self, ncci_fixture_dir):
        table = ncci_loader.load_ncci_ptp_edits(ncci_fixture_dir)
        assert ("80053", "80048") in table

    def test_deleted_pair_excluded_from_fixture(self, ncci_fixture_dir):
        table = ncci_loader.load_ncci_ptp_edits(ncci_fixture_dir)
        # (11111, 22222) has deletion_date 20231231 — should be excluded
        assert ("11111", "22222") not in table

    def test_entry_has_required_keys(self, ncci_fixture_dir):
        table = ncci_loader.load_ncci_ptp_edits(ncci_fixture_dir)
        entry = table[("80053", "80048")]
        assert "modifier" in entry
        assert "source_file" in entry
        assert "pair_effective_date" in entry

    def test_modifier_values_are_strings(self, ncci_fixture_dir):
        table = ncci_loader.load_ncci_ptp_edits(ncci_fixture_dir)
        for key, val in table.items():
            assert val["modifier"] in ("0", "1", "9"), f"Unexpected modifier {val['modifier']} for {key}"

    def test_empty_dir_returns_empty_dict(self, tmp_path):
        table = ncci_loader.load_ncci_ptp_edits(str(tmp_path))
        assert table == {}

    def test_result_is_cached(self, ncci_fixture_dir):
        t1 = ncci_loader.load_ncci_ptp_edits(ncci_fixture_dir)
        t2 = ncci_loader.load_ncci_ptp_edits(ncci_fixture_dir)
        assert t1 is t2  # same object from cache


# ---------------------------------------------------------------------------
# Lookup: pair resolution
# ---------------------------------------------------------------------------

class TestLookupNcciPair:
    def test_found_pair_returns_dict(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        result = ncci_loader.lookup_ncci_pair("80053", "80048")
        assert result is not None
        assert result["col1"] == "80053"
        assert result["col2"] == "80048"
        assert result["modifier"] == "0"

    def test_reverse_order_also_resolves(self, monkeypatch):
        """lookup_ncci_pair checks both (a,b) and (b,a)."""
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        result = ncci_loader.lookup_ncci_pair("80048", "80053")
        assert result is not None
        assert result["col1"] == "80053"
        assert result["col2"] == "80048"

    def test_unknown_pair_returns_none(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        result = ncci_loader.lookup_ncci_pair("99213", "80053")
        assert result is None

    def test_empty_table_returns_none(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", lambda *a, **kw: {})
        result = ncci_loader.lookup_ncci_pair("80053", "80048")
        assert result is None

    def test_result_includes_modifier_description(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        result = ncci_loader.lookup_ncci_pair("80053", "80048")
        assert "modifier_description" in result
        assert len(result["modifier_description"]) > 0

    def test_codes_are_normalized_to_uppercase(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        result = ncci_loader.lookup_ncci_pair(" 80053 ", " 80048 ")
        assert result is not None

    def test_modifier_1_pair_resolved(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        result = ncci_loader.lookup_ncci_pair("99215", "99214")
        assert result is not None
        assert result["modifier"] == "1"

    def test_modifier_9_pair_resolved(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        result = ncci_loader.lookup_ncci_pair("12345", "67890")
        assert result["modifier"] == "9"


# ---------------------------------------------------------------------------
# check_ncci_pairs: rule behavior
# ---------------------------------------------------------------------------

class TestCheckNcciPairsFileBacked:
    def test_bundled_pair_produces_high_finding(self, monkeypatch):
        """80053 + 80048 must produce a HIGH NCCI finding when files are loaded."""
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        findings = check_ncci_pairs(claim)
        assert len(findings) == 1
        assert findings[0].severity == "HIGH"
        assert findings[0].rule == "ncci_ptp"

    def test_finding_names_both_codes(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        findings = check_ncci_pairs(claim)
        assert "80048" in findings[0].issue
        assert "80053" in findings[0].issue

    def test_clean_pair_produces_no_finding(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["99213", "99212"])
        findings = check_ncci_pairs(claim)
        assert findings == []

    def test_finding_has_structured_citation(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert finding.citation.doc_id == ncci_loader.NCCI_DOC_ID
        assert finding.citation.edition == ncci_loader.NCCI_VERSION
        assert finding.citation.effective_date == ncci_loader.NCCI_EFFECTIVE_DATE
        assert finding.citation.excerpt is not None
        assert "80048" in finding.citation.excerpt
        assert "80053" in finding.citation.excerpt

    def test_citation_doc_id_is_file_backed(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert finding.citation.doc_id == "CMS_NCCI_PTP_v322r0"

    def test_citation_source_is_ncci(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert finding.citation.source == "NCCI"

    def test_confidence_is_high_for_file_backed(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert finding.confidence == 0.98

    def test_modifier_0_recommendation_says_no_bypass(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert "No modifier bypass" in finding.recommendation or "cannot be billed" in finding.recommendation

    def test_modifier_1_recommendation_mentions_modifier(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["99215", "99214"])
        finding = check_ncci_pairs(claim)[0]
        assert "modifier" in finding.recommendation.lower()

    def test_multiple_bundled_pairs_all_flagged(self, monkeypatch):
        """If a claim has two distinct bundled pairs, both should produce findings."""
        table = {
            ("80053", "80048"): {"modifier": "0", "source_file": "f4.xlsx", "pair_effective_date": "20000701"},
            ("99215", "99214"): {"modifier": "1", "source_file": "f1.xlsx", "pair_effective_date": "20050101"},
        }
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", lambda *a, **kw: table)
        claim = _make_claim(cpt_codes=["80053", "80048", "99215", "99214"])
        findings = check_ncci_pairs(claim)
        assert len(findings) == 2

    def test_source_is_rule_layer(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert finding.source == "rule_layer"

    def test_excerpt_contains_source_filename(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert "ccipra-v322r0-f4.xlsx" in finding.citation.excerpt

    def test_excerpt_contains_ncci_version(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert "v322r0" in finding.citation.excerpt

    def test_excerpt_contains_effective_date(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", _fixture_loader)
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert "2026-07-01" in finding.citation.excerpt


# ---------------------------------------------------------------------------
# Synthetic fallback: fires when no CMS files are available
# ---------------------------------------------------------------------------

class TestCheckNcciPairsSyntheticFallback:
    def test_fallback_fires_when_table_empty(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", lambda *a, **kw: {})
        claim = _make_claim(cpt_codes=["80053", "80048"])
        findings = check_ncci_pairs(claim)
        assert len(findings) == 1
        assert findings[0].severity == "HIGH"

    def test_fallback_doc_id_is_synthetic(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", lambda *a, **kw: {})
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert finding.citation.doc_id == "NCCI_PTP_80048_80053_SAMPLE"

    def test_fallback_excerpt_labels_itself_synthetic(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", lambda *a, **kw: {})
        claim = _make_claim(cpt_codes=["80053", "80048"])
        finding = check_ncci_pairs(claim)[0]
        assert "SYNTHETIC FALLBACK" in finding.citation.excerpt or "synthetic" in finding.citation.edition.lower()

    def test_fallback_confidence_is_lower_than_file_backed(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", lambda *a, **kw: {})
        claim = _make_claim(cpt_codes=["80053", "80048"])
        fallback_finding = check_ncci_pairs(claim)[0]
        # File-backed = 0.98, synthetic = 0.95
        assert fallback_finding.confidence < 0.98

    def test_fallback_does_not_fire_for_unrelated_codes(self, monkeypatch):
        monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", lambda *a, **kw: {})
        claim = _make_claim(cpt_codes=["99213", "99212"])
        findings = check_ncci_pairs(claim)
        assert findings == []

    def test_fallback_covers_all_synthetic_edits(self):
        """_SYNTHETIC_EDITS list should be non-empty (at minimum the 80053/80048 pair)."""
        assert len(_SYNTHETIC_EDITS) >= 1
        codes = {(e["col1"], e["col2"]) for e in _SYNTHETIC_EDITS}
        assert ("80053", "80048") in codes


# ---------------------------------------------------------------------------
# Integration: file-backed lookup with real CMS files
# ---------------------------------------------------------------------------

class TestCheckNcciPairsRealFiles:
    def test_80053_80048_found_in_real_files(self):
        """80053/80048 pair must be present in the real CMS xlsx files."""
        result = ncci_loader.lookup_ncci_pair("80053", "80048")
        assert result is not None, (
            "80053/80048 pair not found in data/reference/ncci/*.xlsx — "
            "ensure the CMS v322r0 files are present"
        )
        assert result["modifier"] == "0"

    def test_real_lookup_returns_correct_col_direction(self):
        """80053 must be col1 (comprehensive) and 80048 must be col2 (component)."""
        result = ncci_loader.lookup_ncci_pair("80053", "80048")
        if result:
            assert result["col1"] == "80053"
            assert result["col2"] == "80048"

    def test_real_files_produce_high_finding_for_worked_example(self):
        """The PRD worked example (80053 + 80048) must produce a HIGH finding from real files."""
        claim = _make_claim(cpt_codes=["99214", "80053", "80048", "36415"])
        findings = check_ncci_pairs(claim)
        ncci = [f for f in findings if f.rule == "ncci_ptp"]
        assert len(ncci) >= 1
        assert ncci[0].severity == "HIGH"
        assert ncci[0].citation.doc_id == "CMS_NCCI_PTP_v322r0"

    def test_real_citation_has_source_filename(self):
        """Citation excerpt must include the source xlsx filename."""
        claim = _make_claim(cpt_codes=["80053", "80048"])
        findings = check_ncci_pairs(claim)
        if findings:
            assert ".xlsx" in findings[0].citation.excerpt

    def test_clean_claim_no_ncci_finding(self):
        """A clean claim with no bundled codes should produce zero NCCI findings."""
        claim = _make_claim(cpt_codes=["99213"], icd10_codes=["J06.9"])
        findings = check_ncci_pairs(claim)
        assert findings == []
