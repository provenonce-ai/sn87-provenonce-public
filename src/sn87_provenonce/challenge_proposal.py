"""Challenge proposals: a described challenge and a verdict on whether it can be evaluated.

A proposal states the intended consumer, evidence rights, truth source, submission format,
scoring rule, baselines, resource budget and headroom argument for a new challenge. The
admissibility check reads that description and returns ADMISSIBLE, NEEDS_DECISION or
INADMISSIBLE with reason codes. It is advisory and offline. It does not register a class,
pin a profile, change a weight or touch the shadow service: a proposal is always PROPOSED.

Oracle classes are the four of ``protocol.v0alpha1.models.OracleClass``. As used in this
repository: Type A truth is fixed at build time (a planted defect list; ADR-0021), Type C is
a comparison against a reference execution (ADR-0007), Type D is a recorded adjudication that
carries measured reliability (``OracleBinding``). Type B is read here as truth from a public
source; the repository does not define it beyond the ``OracleBinding.identifier`` gloss, and
the whitepaper is not distributed here (docs/whitepaper/README.md), so that reading, and the
choice of A and B as the self-verifying classes, are decisions for the maintainers.
"""

from __future__ import annotations

import json
import re
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, ValidationError, model_validator

from sn87_provenonce import profile
from sn87_provenonce.protocol.v0alpha1.models import (
    Commitment,
    NonEmptyStr,
    OracleClass,
)
from sn87_provenonce.protocol.v0alpha1.models import StrictModel as _ProtocolStrictModel

PROPOSAL_VERSION = "sn87/challenge-proposal/0.1"
PROPOSED_UNPINNED = "PROPOSED_UNPINNED"
# Classes whose truth exists without anyone judging or re-running anything at scoring time.
# Decision for the maintainers (see module docstring): A and B.
SELF_VERIFYING_CLASSES = frozenset({OracleClass.A, OracleClass.B})
MIN_INDEPENDENT_REFERENCE_EXECUTIONS = 2  # ADR-0007


class StrictModel(_ProtocolStrictModel):
    """Protocol strictness plus no type coercion: "120" is not a sample size."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


UnitFloat = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
PositiveFloat = Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
# Identifiers are rejected, not stripped, when they carry leading or trailing whitespace.
ExactId = Annotated[str, StringConstraints(min_length=1, pattern=r"^\S(?:.*\S)?$")]


class Verdict(StrEnum):
    ADMISSIBLE = "ADMISSIBLE"
    NEEDS_DECISION = "NEEDS_DECISION"
    INADMISSIBLE = "INADMISSIBLE"


class ExportDefault(StrEnum):
    NONE = "NONE"
    DERIVED_ONLY = "DERIVED_ONLY"
    RAW_RECORDS = "RAW_RECORDS"


class AgreementName(StrEnum):
    COHEN_KAPPA = "COHEN_KAPPA"
    FLEISS_KAPPA = "FLEISS_KAPPA"
    KRIPPENDORFF_ALPHA = "KRIPPENDORFF_ALPHA"
    PERCENT_AGREEMENT = "PERCENT_AGREEMENT"


class Visibility(StrictModel):
    party: NonEmptyStr
    may_see: tuple[NonEmptyStr, ...] = Field(min_length=1)


class EvidenceRights(StrictModel):
    visibility: tuple[Visibility, ...] = Field(min_length=1)
    raw_evidence_leaves_source: bool
    export_default: ExportDefault
    export_justification: NonEmptyStr | None = None


class AgreementStatistic(StrictModel):
    name: AgreementName
    value: UnitFloat


class ReliabilityBlock(StrictModel):
    method: NonEmptyStr
    sample_size: Annotated[int, Field(gt=0)]
    agreement: AgreementStatistic


class TruthSource(StrictModel):
    oracle_class: OracleClass
    description: NonEmptyStr
    claims_self_verifying: bool = False
    reliability: ReliabilityBlock | None = None
    independent_reference_executions: Annotated[int, Field(ge=0)] | None = None
    reference_executor_private: bool | None = None


class ScoringRule(StrictModel):
    reference: ExactId  # a pinned profile id, or PROPOSED_UNPINNED
    commitment: Commitment | None = None
    description: NonEmptyStr | None = None

    @model_validator(mode="after")
    def require_description_when_unpinned(self) -> Self:
        if self.reference == PROPOSED_UNPINNED and self.description is None:
            raise ValueError("a PROPOSED_UNPINNED scoring rule needs a description")
        return self


class Baseline(StrictModel):
    baseline_id: NonEmptyStr
    description: NonEmptyStr
    sees_public_contract_only: bool
    status: Literal["IMPLEMENTED", "PROPOSED"]


class ResourceBudget(StrictModel):
    compute_seconds: PositiveFloat
    wall_clock_seconds: PositiveFloat
    cost_credits: NonNegativeFloat


class PriorNull(StrictModel):
    reference: NonEmptyStr
    result: Literal["NULL_NO_HEADROOM", "BELOW_BASELINE"]
    note: NonEmptyStr


class HeadroomArgument(StrictModel):
    statement: NonEmptyStr
    prior_nulls: tuple[PriorNull, ...] = ()


class ChallengeProposal(StrictModel):
    proposal_id: NonEmptyStr
    proposal_version: NonEmptyStr
    schema_version: Literal["sn87/challenge-proposal/0.1"]
    status: Literal["PROPOSED"] = "PROPOSED"
    challenge_family: ExactId
    intended_consumer: NonEmptyStr
    evidence_rights: EvidenceRights
    truth_source: TruthSource
    submission_format: NonEmptyStr
    scoring: ScoringRule
    baselines: tuple[Baseline, ...] = ()
    resource_budget: ResourceBudget
    headroom: HeadroomArgument
    known_limitations: tuple[NonEmptyStr, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_baseline_ids(self) -> Self:
        ids = [b.baseline_id for b in self.baselines]
        if len(ids) != len(set(ids)):
            raise ValueError("baseline_id values must be unique")
        return self


class Reason(StrictModel):
    code: NonEmptyStr
    verdict: Verdict
    message: NonEmptyStr


class AdmissibilityResult(StrictModel):
    proposal_id: str
    verdict: Verdict
    reasons: tuple[Reason, ...]
    activates_nothing: Literal[True] = True


# Families the repository itself records as NULL_NO_HEADROOM (LIMITATIONS.md item 8), whatever
# a proposal says about its own history.
KNOWN_NULLS = {
    "IC-APPROVAL-APPLICABILITY": "LIMITATIONS.md item 8",
    "TYPE-C-RELEASE": "LIMITATIONS.md item 8",
}
_SELF_VERIFYING = re.compile(
    r"self[- ]?verif|verif\w* itself|self[- ]?check|objective ground[- ]truth"
)
_RAW = re.compile(r"\braw\b")


def _normalise(text: str) -> str:
    """NFKC, drop format characters (zero-width, soft hyphen), fold every dash, lower-case."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(
        "-" if unicodedata.category(c) == "Pd" or c == "\u2212" else c
        for c in text
        if unicodedata.category(c) != "Cf"
    )
    return " ".join(text.lower().split())


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [t for v in value for t in _strings(v)]
    return []


def _claims_self_verifying_text(proposal: ChallengeProposal) -> bool:
    """Best effort only: the boolean claims_self_verifying is the real gate."""
    return any(
        _SELF_VERIFYING.search(_normalise(t)) for t in _strings(proposal.model_dump(mode="json"))
    )


def evaluate(proposal: ChallengeProposal) -> AdmissibilityResult:
    """Apply the admissibility rules; the worst verdict among the reasons wins."""
    reasons: list[Reason] = []

    def add(code: str, verdict: Verdict, message: str) -> None:
        reasons.append(Reason(code=code, verdict=verdict, message=message))

    truth = proposal.truth_source
    cls = truth.oracle_class
    claims_sv = truth.claims_self_verifying or _claims_self_verifying_text(proposal)

    if cls is OracleClass.D:
        if truth.reliability is None:
            add("TYPE_D_RELIABILITY_MISSING", Verdict.INADMISSIBLE,
                "Type D truth is a judgement: it needs a measured-reliability block "
                "(method, sample size, agreement statistic).")
        else:
            add("TYPE_D_RELIABILITY_REVIEW", Verdict.NEEDS_DECISION,
                "Type D is never admissible from this check: a person must review the "
                "measured reliability (method, sample size, agreement). No threshold is applied.")
        if claims_sv:
            add("SELF_VERIFYING_CLAIM_ON_TYPE_D", Verdict.INADMISSIBLE,
                "Expert-adjudicated truth carries measured reliability; it is not a "
                "self-verifying result and must not be labelled as one.")
    elif claims_sv and cls not in SELF_VERIFYING_CLASSES:
        add("SELF_VERIFYING_CLAIM_ON_NON_SELF_VERIFYING_CLASS", Verdict.INADMISSIBLE,
            f"Type {cls.value} truth is not self-verifying; only Type A or B may claim it.")
    if cls is OracleClass.C:
        runs = truth.independent_reference_executions or 0
        if runs < MIN_INDEPENDENT_REFERENCE_EXECUTIONS:
            add("TYPE_C_NEEDS_INDEPENDENT_EXECUTIONS", Verdict.NEEDS_DECISION,
                f"Type C truth is a reference execution; ADR-0007 asks for at least "
                f"{MIN_INDEPENDENT_REFERENCE_EXECUTIONS} independent ones, found {runs}.")
        if truth.reference_executor_private is not True:
            add("TYPE_C_EXECUTOR_NOT_DECLARED_PRIVATE", Verdict.NEEDS_DECISION,
                "A reference executor that computes truth from the capsule must stay private "
                "(ADR-0021); otherwise the family needs published golden vectors.")

    scoring = proposal.scoring
    if scoring.reference == PROPOSED_UNPINNED:
        add("SCORING_UNPINNED", Verdict.NEEDS_DECISION,
            "The scoring rule is PROPOSED_UNPINNED; it needs a decision to pin a profile "
            "before it can be used. This check never activates it.")
    elif scoring.reference not in profile.REGISTRY:
        add("SCORING_PROFILE_UNKNOWN", Verdict.INADMISSIBLE,
            f"{scoring.reference!r} is not a pinned profile; use a registered id or "
            f"{PROPOSED_UNPINNED}.")
    else:
        family, _domain, pinned = profile.REGISTRY[scoring.reference]
        if scoring.commitment != pinned:
            add("SCORING_COMMITMENT_MISMATCH", Verdict.INADMISSIBLE,
                f"The commitment given for {scoring.reference} does not match the pinned one.")
        if family != proposal.challenge_family:
            add("SCORING_PROFILE_FAMILY_MISMATCH", Verdict.NEEDS_DECISION,
                f"{scoring.reference} is pinned for {family}, not {proposal.challenge_family}.")

    if not proposal.baselines:
        add("BASELINE_MISSING", Verdict.INADMISSIBLE,
            "No baseline to beat. Without one, headroom cannot be shown or a null result "
            "reported (LIMITATIONS.md item 8), and the challenge is not evaluable. Chosen over "
            "NEEDS_DECISION because it is a missing required input, not a judgement call.")
    else:
        if not any(b.sees_public_contract_only for b in proposal.baselines):
            add("BASELINE_NOT_PUBLIC_CONTRACT", Verdict.NEEDS_DECISION,
                "No baseline is limited to the public contract, so headroom over a matched "
                "naive method is not shown.")
        if all(b.status == "PROPOSED" for b in proposal.baselines):
            add("BASELINE_NOT_IMPLEMENTED", Verdict.NEEDS_DECISION,
                "Every baseline is only proposed; none has been run.")

    if proposal.challenge_family in KNOWN_NULLS:
        add("PRIOR_NULL_NO_HEADROOM_RECORDED", Verdict.NEEDS_DECISION,
            f"The repository records NULL_NO_HEADROOM for {proposal.challenge_family} "
            f"({KNOWN_NULLS[proposal.challenge_family]}), whatever the proposal declares.")
    elif proposal.headroom.prior_nulls:
        add("PRIOR_NULL_NO_HEADROOM", Verdict.NEEDS_DECISION,
            "Earlier results for this family were null or below baseline; the headroom "
            "argument needs a human decision, not an automatic pass.")

    rights = proposal.evidence_rights
    raw_default = rights.export_default is ExportDefault.RAW_RECORDS
    if rights.raw_evidence_leaves_source != raw_default:
        add("EVIDENCE_RIGHTS_INCONSISTENT", Verdict.INADMISSIBLE,
            "raw_evidence_leaves_source and export_default RAW_RECORDS must agree.")
    elif raw_default:
        if rights.export_justification is None:
            add("RAW_EXPORT_BY_DEFAULT", Verdict.INADMISSIBLE,
                "Raw source records leave the source by default with no stated justification.")
        else:
            add("RAW_EXPORT_JUSTIFIED", Verdict.NEEDS_DECISION,
                "Raw source records leave the source by default; the justification needs a "
                "human decision.")

    if not rights.raw_evidence_leaves_source:
        rights_text = _strings(rights.model_dump(mode="json", exclude={"export_default"}))
        if any(_RAW.search(_normalise(t)) for t in rights_text):
            add("EVIDENCE_TEXT_MENTIONS_RAW", Verdict.NEEDS_DECISION,
                "The evidence-rights text mentions raw evidence although the flags say it "
                "stays at the source; the check is structural, so a person must read it.")

    verdicts = {r.verdict for r in reasons}
    if Verdict.INADMISSIBLE in verdicts:
        overall = Verdict.INADMISSIBLE
    elif Verdict.NEEDS_DECISION in verdicts:
        overall = Verdict.NEEDS_DECISION
    else:
        overall = Verdict.ADMISSIBLE
    return AdmissibilityResult(
        proposal_id=proposal.proposal_id, verdict=overall, reasons=tuple(reasons)
    )


def _invalid(proposal_id: str, detail: str) -> AdmissibilityResult:
    return AdmissibilityResult(
        proposal_id=proposal_id,
        verdict=Verdict.INADMISSIBLE,
        reasons=(Reason(code="SCHEMA_INVALID", verdict=Verdict.INADMISSIBLE, message=detail),),
    )


def check_proposal_text(text: str) -> AdmissibilityResult:
    """Parse JSON text and evaluate it; a schema failure is INADMISSIBLE, not an exception."""
    try:
        data: Any = json.loads(text)
        pid = str(data.get("proposal_id", "UNKNOWN")) if isinstance(data, dict) else "UNKNOWN"
    except RecursionError:
        return _invalid("UNKNOWN", "JSON is nested too deeply")
    except ValueError as exc:
        return _invalid("UNKNOWN", f"not valid JSON: {exc}")
    try:
        proposal = ChallengeProposal.model_validate_json(text)
    except RecursionError:
        return _invalid(pid, "JSON is nested too deeply")
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return _invalid(pid, detail)
    return evaluate(proposal)


def check_proposal_file(path: Path) -> AdmissibilityResult:
    """Raises OSError or UnicodeDecodeError when the file cannot be read as UTF-8 text."""
    return check_proposal_text(path.read_text(encoding="utf-8"))


EXIT_CODES = {Verdict.ADMISSIBLE: 0, Verdict.INADMISSIBLE: 1, Verdict.NEEDS_DECISION: 3}


def render(result: AdmissibilityResult) -> str:
    lines = [f"{result.proposal_id}: {result.verdict.value}"]
    lines += [f"  [{r.verdict.value}] {r.code}: {r.message}" for r in result.reasons]
    lines.append("This check activates nothing: no class, profile, weight or service is changed.")
    return "\n".join(lines)
