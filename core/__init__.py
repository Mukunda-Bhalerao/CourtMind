"""Core components for the CourtMind deterministic legal analysis engine"""

from .ontology import (
    LegalTag,
    OPPOSITIONAL_TAG_PAIRS,
    OPPOSITION_MAP,
    SECTION_ELEMENT_ONTOLOGY,
    EXCEPTION_NEGATION_MAP,
    validate_tag,
    resolve_tag,
    get_opposing_tags,
    is_opposed,
    get_section_element_tags,
    get_element_negations,
    list_sections,
    list_tags,
)
from .fact_matrix import FactMatrix, Fact, Conflict, FactCategory, FactSource, Severity
from .statute_engine import (
    StatuteEvaluator,
    IPC302Evaluator,
    EvaluationResult,
    ElementResult,
    ElementStatus,
    Recommendation,
)
from .evaluators.ipc304 import IPC304Evaluator
from .evaluators.ipc420 import IPC420Evaluator
from .evaluators.ipc323 import IPC323Evaluator
from .burden_engine import BurdenEngine, BurdenResult, BurdenStage
from .evidence_weight_engine import EvidenceWeightEngine, EvidenceWeightResult
from .exception_engine import ExceptionEngine, ExceptionResult, ExceptionDetail
from .evaluation_pipeline import EvaluationPipeline, CaseAnalysis
from .section_registry import SectionRegistry, registry
from .section_auto_detector import SectionAutoDetector, DetectionResult, DetectedSection

__all__ = [
    'LegalTag',
    'OPPOSITIONAL_TAG_PAIRS',
    'OPPOSITION_MAP',
    'SECTION_ELEMENT_ONTOLOGY',
    'EXCEPTION_NEGATION_MAP',
    'validate_tag',
    'resolve_tag',
    'get_opposing_tags',
    'is_opposed',
    'get_section_element_tags',
    'get_element_negations',
    'list_sections',
    'list_tags',
    'FactMatrix',
    'Fact',
    'Conflict',
    'FactCategory',
    'FactSource',
    'Severity',
    'StatuteEvaluator',
    'IPC302Evaluator',
    'IPC304Evaluator',
    'IPC420Evaluator',
    'IPC323Evaluator',
    'EvaluationResult',
    'ElementResult',
    'ElementStatus',
    'Recommendation',
    'BurdenEngine',
    'BurdenResult',
    'BurdenStage',
    'EvidenceWeightEngine',
    'EvidenceWeightResult',
    'ExceptionEngine',
    'ExceptionResult',
    'ExceptionDetail',
    'EvaluationPipeline',
    'CaseAnalysis',
    'SectionRegistry',
    'registry',
    'SectionAutoDetector',
    'DetectionResult',
    'DetectedSection',
] 