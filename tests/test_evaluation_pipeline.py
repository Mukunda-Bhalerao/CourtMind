"""
Integration tests for EvaluationPipeline + CaseAnalysis.

Verifies:
 1. Pipeline wires StatuteEvaluator → BurdenEngine correctly
 2. CaseAnalysis bundles both results without mutating schemas
 3. Backward compatibility — raw evaluator still works independently
 4. Custom evaluator / engine injection
 5. Output serialises to dict / JSON correctly
 6. Convenience accessors return expected values
 7. Metadata contains required fields

Run:  python -m pytest tests/test_evaluation_pipeline.py -v
"""

import json
import pytest

from core.fact_matrix import (
    FactCategory,
    FactMatrix,
    FactSource,
    Severity,
)
from core.statute_engine import (
    EvaluationResult,
    IPC302Evaluator,
    Recommendation,
)
from core.burden_engine import BurdenEngine, BurdenResult, BurdenStage
from core.evaluation_pipeline import CaseAnalysis, EvaluationPipeline


# ── helpers ───────────────────────────────────────────────────────────────

def _strong_matrix() -> FactMatrix:
    """All three required IPC-302 elements satisfied at HIGH+ severity."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim died from stab wounds",
        FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused stabbed the victim repeatedly",
        FactSource.WITNESS, severity=Severity.CRITICAL, tags=["act_by_accused"],
    )
    m.add_fact(
        FactCategory.MENS_REA, "Accused planned the attack deliberately",
        FactSource.DOCUMENT, severity=Severity.HIGH,
        tags=["premeditated", "intention"],
    )
    return m


def _incomplete_matrix() -> FactMatrix:
    """Death + act present, NO mens-rea."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim was found dead",
        FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused pushed the victim",
        FactSource.WITNESS, severity=Severity.HIGH, tags=["act_by_accused"],
    )
    return m


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture()
def pipeline() -> EvaluationPipeline:
    return EvaluationPipeline()


@pytest.fixture()
def strong() -> FactMatrix:
    return _strong_matrix()


@pytest.fixture()
def incomplete() -> FactMatrix:
    return _incomplete_matrix()


# ═════════════════════════════════════════════════════════════════════════
# 1. Pipeline wires evaluator → burden correctly
# ═════════════════════════════════════════════════════════════════════════

class TestPipelineWiring:
    def test_strong_case_prima_facie(self, pipeline, strong):
        analysis = pipeline.run(strong)
        assert analysis.burden_stage == BurdenStage.PRIMA_FACIE_ESTABLISHED.value

    def test_incomplete_case_prosecution_incomplete(self, pipeline, incomplete):
        analysis = pipeline.run(incomplete)
        assert analysis.burden_stage == BurdenStage.PROSECUTION_INCOMPLETE.value

    def test_verdict_recommendation_present(self, pipeline, strong):
        analysis = pipeline.run(strong)
        assert analysis.verdict_recommendation == Recommendation.PROCEED.value


# ═════════════════════════════════════════════════════════════════════════
# 2. EvaluationResult schema NOT modified
# ═════════════════════════════════════════════════════════════════════════

class TestSchemaPreservation:
    EVAL_EXPECTED_KEYS = {
        "section", "section_title", "elements_required",
        "elements_satisfied", "elements_failed", "elements_partial",
        "elements_conflicted", "element_details",
        "verdict_recommendation", "conflicts_found",
        "exceptions_claimed", "evaluated_at",
    }

    BURDEN_EXPECTED_KEYS = {
        "burden_stage", "confidence_score",
        "required_elements_satisfied", "required_elements_total",
        "conflicted_elements", "exceptions_claimed",
        "exceptions_supported", "reasoning_flags",
    }

    def test_evaluation_result_keys(self, pipeline, strong):
        analysis = pipeline.run(strong)
        assert set(analysis.evaluation_result.keys()) == self.EVAL_EXPECTED_KEYS

    def test_burden_result_keys(self, pipeline, strong):
        analysis = pipeline.run(strong)
        assert set(analysis.burden_result.keys()) == self.BURDEN_EXPECTED_KEYS

    def test_no_cross_contamination(self, pipeline, strong):
        """burden_result must NOT leak into evaluation_result dict."""
        analysis = pipeline.run(strong)
        assert "burden_stage" not in analysis.evaluation_result
        assert "verdict_recommendation" not in analysis.burden_result


# ═════════════════════════════════════════════════════════════════════════
# 3. Backward compatibility — raw evaluator works independently
# ═════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    def test_raw_evaluator_still_works(self, strong):
        evaluator = IPC302Evaluator()
        result = evaluator.evaluate(strong)
        assert isinstance(result, EvaluationResult)
        assert result.verdict_recommendation == Recommendation.PROCEED.value

    def test_raw_burden_still_works(self, strong):
        evaluator = IPC302Evaluator()
        engine = BurdenEngine()
        er = evaluator.evaluate(strong)
        br = engine.evaluate(er, strong)
        assert isinstance(br, BurdenResult)
        assert br.burden_stage == BurdenStage.PRIMA_FACIE_ESTABLISHED.value


# ═════════════════════════════════════════════════════════════════════════
# 4. Custom evaluator / engine injection
# ═════════════════════════════════════════════════════════════════════════

class TestCustomInjection:
    def test_default_evaluator_is_ipc302(self, pipeline):
        assert isinstance(pipeline.evaluator, IPC302Evaluator)

    def test_default_burden_engine(self, pipeline):
        assert isinstance(pipeline.burden_engine, BurdenEngine)

    def test_custom_evaluator_accepted(self):
        custom = IPC302Evaluator()
        p = EvaluationPipeline(evaluator=custom)
        assert p.evaluator is custom

    def test_custom_burden_engine_accepted(self):
        custom = BurdenEngine()
        p = EvaluationPipeline(burden_engine=custom)
        assert p.burden_engine is custom


# ═════════════════════════════════════════════════════════════════════════
# 5. Serialisation
# ═════════════════════════════════════════════════════════════════════════

class TestSerialisation:
    def test_to_dict_top_level_keys(self, pipeline, strong):
        d = pipeline.run(strong).to_dict()
        assert set(d.keys()) == {
            "evaluation_result", "burden_result", "metadata",
            "evidence_weight_result", "exception_result",
        }

    def test_to_json_parseable(self, pipeline, strong):
        analysis = pipeline.run(strong)
        parsed = json.loads(analysis.to_json())
        assert parsed["burden_result"]["burden_stage"] == \
            BurdenStage.PRIMA_FACIE_ESTABLISHED.value

    def test_roundtrip_preserves_values(self, pipeline, strong):
        analysis = pipeline.run(strong)
        parsed = json.loads(analysis.to_json())
        assert parsed["evaluation_result"]["section"] == "302 IPC"
        assert parsed["burden_result"]["confidence_score"] == 1.0


# ═════════════════════════════════════════════════════════════════════════
# 6. Convenience accessors
# ═════════════════════════════════════════════════════════════════════════

class TestConvenienceAccessors:
    def test_burden_stage(self, pipeline, strong):
        a = pipeline.run(strong)
        assert a.burden_stage == BurdenStage.PRIMA_FACIE_ESTABLISHED.value

    def test_confidence_score(self, pipeline, strong):
        a = pipeline.run(strong)
        assert a.confidence_score == 1.0

    def test_verdict_recommendation(self, pipeline, strong):
        a = pipeline.run(strong)
        assert a.verdict_recommendation == Recommendation.PROCEED.value

    def test_confidence_type(self, pipeline, strong):
        a = pipeline.run(strong)
        assert isinstance(a.confidence_score, float)


# ═════════════════════════════════════════════════════════════════════════
# 7. Metadata
# ═════════════════════════════════════════════════════════════════════════

class TestMetadata:
    def test_metadata_has_required_fields(self, pipeline, strong):
        m = pipeline.run(strong).metadata
        assert "pipeline_version" in m
        assert "section_evaluated" in m
        assert "section_title" in m
        assert "evaluated_at" in m

    def test_section_evaluated(self, pipeline, strong):
        m = pipeline.run(strong).metadata
        assert m["section_evaluated"] == "302 IPC"
        assert m["section_title"] == "Murder"

    def test_pipeline_version(self, pipeline, strong):
        m = pipeline.run(strong).metadata
        assert m["pipeline_version"] == "1.0.0"
