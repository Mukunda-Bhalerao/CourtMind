"""
CourtMind — LLM-based Fact Extraction via Ollama

Extracts structured legal facts from raw case narrative text using
an Ollama-hosted LLM, then converts the output into a populated
:class:`FactMatrix`.

**Design constraints**

*   The LLM is used **only** for extraction — all downstream legal
    reasoning remains deterministic.
*   Graceful fallback: if Ollama is unreachable the module returns a
    ``FactMatrix`` built from simple heuristic keyword extraction so
    the pipeline never breaks.
*   Thread-safe.  No shared mutable state.

Usage
-----
    from core.fact_extractor import extract_facts

    fm = extract_facts("Ravi stabbed Mohan with a knife …")
    print(fm.summary())
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from core.fact_matrix import FactCategory, FactMatrix, FactSource, Severity
from core.ontology import LegalTag

log = logging.getLogger(__name__)

# ── Ollama configuration ─────────────────────────────────────────────────
DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2"

_EXTRACTION_PROMPT = """\
You are a legal fact extractor for Indian criminal cases under the Indian Penal Code (IPC).

Extract structured legal facts from the following case narrative.

Return ONLY valid JSON with these keys (each value is a list of short factual phrases):

{
  "actus_reus": [],
  "mens_rea": [],
  "harm": [],
  "context": [],
  "evidence": [],
  "exceptions": []
}

Rules:
- actus_reus: Physical acts committed (stabbing, hitting, deceiving, etc.)
- mens_rea: Mental state indicators (intent to kill, premeditation, knowledge, dishonest intent, etc.)
- harm: Outcomes (death, injury, financial loss, etc.)
- context: Circumstances (fight, argument, business deal, provocation, etc.)
- evidence: Physical/documentary evidence mentioned (weapon, witness, CCTV, medical report, etc.)
- exceptions: Legal defenses mentioned (self-defense, provocation, accident, etc.)

Be exhaustive. Extract every relevant factual phrase. Do NOT invent facts not present in the narrative.

Case narrative:
{case_text}

JSON output:
"""


# ── Negation detection ────────────────────────────────────────────────────

_NEGATION_RE = re.compile(
    r"\b(?:no|not|never|without|didn'?t|did not|wasn'?t|were not|isn'?t|"  # noqa: E501
    r"aren'?t|don'?t|does not|has not|have not|hadn'?t|cannot|can'?t|"  # noqa: E501
    r"denies|denied|absence of|lack of|neither)\b",
    re.IGNORECASE,
)


def _is_negated(sentence: str, keyword_match_start: int) -> bool:
    """Return True if the keyword match is preceded by a negation word within the same clause."""
    prefix = sentence[:keyword_match_start].lower()
    # Only look at the closest 60 characters before the match
    prefix = prefix[-60:]
    return bool(_NEGATION_RE.search(prefix))


# ── Keyword → tag mappings for heuristic fallback AND tag enrichment ─────

_ACTUS_REUS_KEYWORDS: List[Tuple[str, List[str], str]] = [
    # (keyword_pattern, tags, severity)
    (r"\bstabb(?:ed|ing)\b", [LegalTag.STABBING.value, LegalTag.ACT_BY_ACCUSED.value, LegalTag.VIOLENCE.value], Severity.CRITICAL.value),
    (r"\bshot\b|\bshooting\b|\bgunshot\b", [LegalTag.SHOOTING.value, LegalTag.ACT_BY_ACCUSED.value, LegalTag.VIOLENCE.value], Severity.CRITICAL.value),
    (r"\bstrangl(?:ed|ing|ation)\b", [LegalTag.STRANGULATION.value, LegalTag.ACT_BY_ACCUSED.value, LegalTag.VIOLENCE.value], Severity.CRITICAL.value),
    (r"\bpoison(?:ed|ing)\b", [LegalTag.POISONING.value, LegalTag.ACT_BY_ACCUSED.value], Severity.CRITICAL.value),
    (r"\bassault(?:ed)?\b|\battack(?:ed)?\b", [LegalTag.ASSAULT.value, LegalTag.ACT_BY_ACCUSED.value, LegalTag.VIOLENCE.value], Severity.HIGH.value),
    (r"\bstruck\b", [LegalTag.ACT_BY_ACCUSED.value, LegalTag.VIOLENCE.value], Severity.HIGH.value),
    (r"\bslapp(?:ed|ing)\b|\bpunch(?:ed|ing)\b|\bkick(?:ed|ing)\b|\bbeat(?:en|ing)?\b", [LegalTag.ACT_BY_ACCUSED.value, LegalTag.SIMPLE_HURT.value], Severity.MEDIUM.value),
    (r"\bhit\b", [LegalTag.ACT_BY_ACCUSED.value, LegalTag.VIOLENCE.value], Severity.MEDIUM.value),
    (r"\bdeceiv(?:ed|ing)\b|\bfraud\b|\bcheating\b|\bmisrepresent", [LegalTag.DECEPTION.value, LegalTag.ACT_BY_ACCUSED.value], Severity.HIGH.value),
    (r"\bfalse (?:statements?|promises?|representations?|documents?|claims?)\b", [LegalTag.DECEPTION.value, LegalTag.ACT_BY_ACCUSED.value], Severity.HIGH.value),
    (r"\bconvinced\b|\bpersuade\b|\blured\b|\binduced\b", [LegalTag.DISHONEST_INDUCEMENT.value, LegalTag.ACT_BY_ACCUSED.value], Severity.HIGH.value),
    (r"\bpush(?:ed|ing)\b", [LegalTag.ACT_BY_ACCUSED.value, LegalTag.VIOLENCE.value], Severity.MEDIUM.value),
]

_HARM_KEYWORDS: List[Tuple[str, List[str], str]] = [
    (r"\bdied\b|\bdeath\b|\bkilled\b|\bdead\b|\bdeceased\b|\bfatal\b|\bhomicide\b", [LegalTag.DEATH.value, LegalTag.DEATH_CAUSED.value, LegalTag.VICTIM_DEAD.value], Severity.CRITICAL.value),
    (r"\bhurt\b|\binjur(?:y|ed|ies)\b|\bbruise\b|\bpain\b|\bbodily harm\b|\bminor injury\b", [LegalTag.SIMPLE_HURT.value], Severity.MEDIUM.value),
    (r"\bfinancial loss\b|\bmonetary loss\b|\bwrongful loss\b|\blost money\b|\bembezzl", [LegalTag.WRONGFUL_LOSS.value], Severity.HIGH.value),
    (r"\bnever returned\b|\bstopped responding\b|\babsconded\b|\bvanished\b|\bfled\b", [LegalTag.WRONGFUL_LOSS.value], Severity.HIGH.value),
    (r"\btransfer(?:red)? money\b|\bwithdrew\b|\bwithdrawal\b", [LegalTag.WRONGFUL_GAIN.value], Severity.HIGH.value),
    (r"\bwrongful gain\b|\bmonetary gain\b|\bstolen funds\b|\bmisappropriat", [LegalTag.WRONGFUL_GAIN.value], Severity.HIGH.value),
]

_MENS_REA_KEYWORDS: List[Tuple[str, List[str], str]] = [
    (r"\bpremeditat(?:ed|ion)\b|\bplanned\b|\bdeliberat(?:e|ely)\b", [LegalTag.PREMEDITATED.value, LegalTag.INTENTION.value, LegalTag.INTENTIONAL.value], Severity.CRITICAL.value),
    (r"\bintent(?:ion|ional|ionally)?\b|\bwillful(?:ly)?\b|\bwith intent\b", [LegalTag.INTENTION.value, LegalTag.INTENTIONAL.value, LegalTag.INTENT.value], Severity.HIGH.value),
    (r"\bmotive\b", [LegalTag.MOTIVE.value, LegalTag.INTENTION.value], Severity.HIGH.value),
    (r"\bknew\b|\bknowledge\b|\baware\b|\bknowing(?:ly)?\b", [LegalTag.KNOWLEDGE.value], Severity.MEDIUM.value),
    (r"\bknew likely\b|\blikely to cause death\b|\bknowledge of death\b", [LegalTag.KNOWLEDGE_LIKELY_DEATH.value], Severity.HIGH.value),
    (r"\bno intent to kill\b|\bwithout intention\b|\bnot premeditated\b|\bunintention", [LegalTag.NO_INTENT_TO_KILL.value, LegalTag.KNOWLEDGE_LIKELY_DEATH.value], Severity.MEDIUM.value),
    (r"\bheat of (?:the )?(?:moment|passion)\b|\bsudden\b|\bimpulsi(?:ve|vely)\b", [LegalTag.SPONTANEOUS.value, LegalTag.NO_INTENT_TO_KILL.value], Severity.MEDIUM.value),
    (r"\bdishonest(?:ly)?\b|\bindu(?:ced|cement)\b|\blured\b|\btricked\b", [LegalTag.DISHONEST_INDUCEMENT.value], Severity.HIGH.value),
    (r"\bpromis(?:ed|es|ing)\b.*\b(?:return|profit|gain|money)\b", [LegalTag.DISHONEST_INDUCEMENT.value], Severity.HIGH.value),
    (r"\bguaranteed?\b.*\b(?:return|profit)\b", [LegalTag.DISHONEST_INDUCEMENT.value, LegalTag.DECEPTION.value], Severity.HIGH.value),
    (r"\bmultiple stab(?:s|bing)?\b|\brepeated(?:ly)?\b|\bvital organ\b", [LegalTag.PREMEDITATED.value, LegalTag.INTENTION.value], Severity.CRITICAL.value),
]

_EVIDENCE_KEYWORDS: List[Tuple[str, List[str], str]] = [
    (r"\bweapon\b|\bknife\b|\bgun\b|\bfirearm\b|\biron rod\b|\bbat\b", [LegalTag.WEAPON.value], Severity.HIGH.value),
    (r"\bwitness\b|\btestimon(?:y|ies)\b|\beyewitness\b", [LegalTag.WITNESS.value], Severity.HIGH.value),
    (r"\bforensic\b|\bautopsy\b|\bpost-mortem\b|\bpost mortem\b", [LegalTag.FORENSIC.value, LegalTag.AUTOPSY.value], Severity.HIGH.value),
    (r"\bcctv\b|\bfootage\b|\bvideo\b|\bcamera\b", [LegalTag.CCTV.value], Severity.HIGH.value),
    (r"\bdna\b|\bfingerprint\b", [LegalTag.DNA.value, LegalTag.FINGERPRINT.value], Severity.HIGH.value),
    (r"\bblood\b|\bbloodstain\b", [LegalTag.BLOOD.value], Severity.MEDIUM.value),
    (r"\bmedical report\b|\bdoctor\b|\bhospital\b", [LegalTag.FORENSIC.value], Severity.MEDIUM.value),
    (r"\bbank (?:transfer|record|statement|account)\b", ["document_evidence"], Severity.HIGH.value),
    (r"\bmessage(?:s)?\b|\bemail\b|\bchat\b|\bcorrespondence\b", ["document_evidence"], Severity.MEDIUM.value),
    (r"\brecord(?:s)?\b.*\b(?:show|confirm|prove)\b", ["document_evidence"], Severity.MEDIUM.value),
]

_EXCEPTION_KEYWORDS: List[Tuple[str, List[str], str]] = [
    (r"\bself[- ]defen[sc]e\b", [LegalTag.SELF_DEFENSE.value], Severity.HIGH.value),
    (r"\bprovoc(?:ation|ed)\b", [LegalTag.PROVOCATION.value], Severity.HIGH.value),
    (r"\baccident(?:al|ally)?\b", [LegalTag.ACCIDENT.value], Severity.HIGH.value),
    (r"\binsanity\b|\bmental(?:ly)? (?:ill|unstabl|disord)", [LegalTag.INSANITY.value], Severity.HIGH.value),
    (r"\bduress\b|\bunder threat\b|\bcoerced\b", [LegalTag.DURESS.value], Severity.HIGH.value),
    (r"\balibi\b", [LegalTag.ALIBI.value], Severity.HIGH.value),
    (r"\bmistaken identity\b|\bwrong person\b", [LegalTag.MISTAKEN_IDENTITY.value], Severity.HIGH.value),
    (r"\bconsent\b", [LegalTag.CONSENT.value], Severity.MEDIUM.value),
]


# ═════════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════════

def extract_facts(
    case_text: str,
    *,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
) -> FactMatrix:
    """
    Extract structured legal facts from *case_text*.

    Attempts LLM extraction via Ollama first; falls back to keyword
    heuristics if Ollama is unreachable.

    Parameters
    ----------
    case_text : str
        Raw case narrative.
    ollama_url : str
        Ollama API generate endpoint.
    model : str
        Model name to use.
    timeout : int
        HTTP timeout in seconds.

    Returns
    -------
    FactMatrix
        Populated with extracted facts and enriched tags.
    """
    case_text = case_text.strip()
    if not case_text:
        return FactMatrix()

    # Try LLM extraction
    llm_data = _call_ollama(case_text, ollama_url, model, timeout)

    if llm_data:
        fm = _build_matrix_from_llm(llm_data, case_text)
    else:
        log.info("Ollama unavailable — using keyword heuristic extraction")
        fm = _build_matrix_from_keywords(case_text)

    # Always enrich with keyword-derived tags regardless of source
    _enrich_tags(fm, case_text)

    return fm


def extract_facts_keyword_only(case_text: str) -> FactMatrix:
    """
    Keyword-only extraction (no LLM).  Useful for testing and
    environments without Ollama.
    """
    case_text = case_text.strip()
    if not case_text:
        return FactMatrix()
    fm = _build_matrix_from_keywords(case_text)
    _enrich_tags(fm, case_text)
    return fm


# ═════════════════════════════════════════════════════════════════════════
# Ollama interaction
# ═════════════════════════════════════════════════════════════════════════

def _call_ollama(
    case_text: str,
    url: str,
    model: str,
    timeout: int,
) -> Optional[Dict[str, Any]]:
    """Call Ollama and parse the JSON response.  Returns ``None`` on any failure."""
    import urllib.request

    prompt = _EXTRACTION_PROMPT.replace("{case_text}", case_text)
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
        raw_text = body.get("response", "")
        return _parse_llm_json(raw_text)
    except Exception:
        log.warning("Ollama call failed", exc_info=True)
        return None


def _parse_llm_json(raw: str) -> Optional[Dict[str, Any]]:
    """Robust JSON extraction from LLM response text."""
    raw = raw.strip()
    # Try direct parse
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Try extracting JSON block from markdown
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { ... }
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ═════════════════════════════════════════════════════════════════════════
# FactMatrix builders
# ═════════════════════════════════════════════════════════════════════════

def _build_matrix_from_llm(
    llm_data: Dict[str, Any],
    case_text: str,
) -> FactMatrix:
    """Convert LLM JSON output to FactMatrix."""
    fm = FactMatrix()

    # Map LLM keys to FactCategory + source
    mapping = {
        "actus_reus": (FactCategory.ACTUS_REUS.value, FactSource.CASE_FILE.value),
        "mens_rea": (FactCategory.MENS_REA.value, FactSource.CASE_FILE.value),
        "harm": (FactCategory.ACTUS_REUS.value, FactSource.CASE_FILE.value),  # harm is part of actus_reus
        "context": (FactCategory.ACTUS_REUS.value, FactSource.CASE_FILE.value),
        "evidence": (FactCategory.EVIDENCE.value, FactSource.DOCUMENT.value),
        "exceptions": (FactCategory.EXCEPTIONS_CLAIMED.value, FactSource.CASE_FILE.value),
    }

    for llm_key, (category, source) in mapping.items():
        items = llm_data.get(llm_key, [])
        if not isinstance(items, list):
            items = [str(items)] if items else []
        for item in items:
            stmt = str(item).strip()
            if not stmt:
                continue
            severity = _infer_severity(stmt, category)
            tags = _infer_tags_for_statement(stmt)
            fm.add_fact(
                category, stmt, source,
                severity=severity,
                tags=tags,
            )

    return fm


def _match_with_negation(pattern: str, sentence: str) -> bool:
    """Return True if *pattern* matches in *sentence* without being negated."""
    m = re.search(pattern, sentence, re.IGNORECASE)
    if not m:
        return False
    return not _is_negated(sentence, m.start())


def _build_matrix_from_keywords(case_text: str) -> FactMatrix:
    """Build FactMatrix entirely from keyword pattern matching."""
    fm = FactMatrix()

    # Extract sentences for context
    sentences = re.split(r'[.!?]+', case_text)
    sentences = [s.strip() for s in sentences if s.strip()]

    # Process each keyword group
    for pattern, tags, severity in _ACTUS_REUS_KEYWORDS:
        for sent in sentences:
            if _match_with_negation(pattern, sent):
                fm.add_fact(
                    FactCategory.ACTUS_REUS.value, sent,
                    FactSource.CASE_FILE.value,
                    severity=severity, tags=tags,
                )

    for pattern, tags, severity in _HARM_KEYWORDS:
        for sent in sentences:
            if _match_with_negation(pattern, sent):
                fm.add_fact(
                    FactCategory.ACTUS_REUS.value, sent,
                    FactSource.CASE_FILE.value,
                    severity=severity, tags=tags,
                )

    for pattern, tags, severity in _MENS_REA_KEYWORDS:
        for sent in sentences:
            if _match_with_negation(pattern, sent):
                fm.add_fact(
                    FactCategory.MENS_REA.value, sent,
                    FactSource.CASE_FILE.value,
                    severity=severity, tags=tags,
                )

    for pattern, tags, severity in _EVIDENCE_KEYWORDS:
        for sent in sentences:
            if _match_with_negation(pattern, sent):
                fm.add_fact(
                    FactCategory.EVIDENCE.value, sent,
                    FactSource.DOCUMENT.value,
                    severity=severity, tags=tags,
                )

    for pattern, tags, severity in _EXCEPTION_KEYWORDS:
        for sent in sentences:
            if _match_with_negation(pattern, sent):
                fm.add_fact(
                    FactCategory.EXCEPTIONS_CLAIMED.value, sent,
                    FactSource.CASE_FILE.value,
                    severity=severity, tags=tags,
                )

    # If nothing matched at all add the full text as actus_reus so the pipeline has something
    if fm.count() == 0:
        fm.add_fact(
            FactCategory.ACTUS_REUS.value,
            case_text[:500],
            FactSource.USER_INPUT.value,
            severity=Severity.MEDIUM.value,
        )

    return fm


# ═════════════════════════════════════════════════════════════════════════
# Tag enrichment — runs on ALL matrices regardless of extraction source
# ═════════════════════════════════════════════════════════════════════════

def _enrich_tags(fm: FactMatrix, case_text: str) -> None:
    """Add ontology-aligned tags to facts based on keyword patterns in statements."""
    all_keyword_maps = [
        (FactCategory.ACTUS_REUS.value, _ACTUS_REUS_KEYWORDS + _HARM_KEYWORDS),
        (FactCategory.MENS_REA.value, _MENS_REA_KEYWORDS),
        (FactCategory.EVIDENCE.value, _EVIDENCE_KEYWORDS),
        (FactCategory.EXCEPTIONS_CLAIMED.value, _EXCEPTION_KEYWORDS),
    ]

    for category, keyword_list in all_keyword_maps:
        facts = fm.get_facts(category)
        for fact in facts:
            existing_tags = set(fact.tags)
            stmt = fact.statement
            for pattern, tags, _ in keyword_list:
                if _match_with_negation(pattern, stmt):
                    for tag in tags:
                        if tag not in existing_tags:
                            fact.tags.append(tag)
                            existing_tags.add(tag)


def _infer_severity(statement: str, category: str) -> str:
    """Infer severity from statement content."""
    stmt = statement.lower()

    # Critical indicators
    if any(w in stmt for w in ("died", "death", "killed", "murder", "fatal", "premeditated")):
        return Severity.CRITICAL.value
    if any(w in stmt for w in ("stabbed", "shot", "strangled", "poisoned")):
        return Severity.CRITICAL.value

    # High indicators
    if any(w in stmt for w in ("intent", "deliberate", "planned", "weapon", "assault",
                                "fraud", "deception", "motive")):
        return Severity.HIGH.value

    # Medium indicators
    if any(w in stmt for w in ("witness", "evidence", "injury", "hurt", "punch",
                                "slap", "kick", "knowledge", "aware")):
        return Severity.MEDIUM.value

    return Severity.MEDIUM.value


def _infer_tags_for_statement(statement: str) -> List[str]:
    """Infer tags from a single statement using all keyword maps."""
    tags: List[str] = []
    seen: set = set()
    stmt = statement.lower()

    all_maps = _ACTUS_REUS_KEYWORDS + _HARM_KEYWORDS + _MENS_REA_KEYWORDS + \
               _EVIDENCE_KEYWORDS + _EXCEPTION_KEYWORDS

    for pattern, tag_list, _ in all_maps:
        if re.search(pattern, stmt, re.IGNORECASE):
            for tag in tag_list:
                if tag not in seen:
                    tags.append(tag)
                    seen.add(tag)

    return tags
