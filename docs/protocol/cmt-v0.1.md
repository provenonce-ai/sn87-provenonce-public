# Canonical Miner Task (CMT) v0.1 - candidate schema

**Status: candidate schema, not adopted.** Source: `SPECIFICATION_CANDIDATE.md` sections 2-4 and 6, which is a proposal and "not an approved wire schema". `sn87-cmt/0.1` names no wire object, adds no scoring, changes no profile and touches no chain or network. Code: `src/sn87_provenonce/cmt/`.

## What it is

A CMT is a reusable, versioned task specification (manifest) plus its compiled compatibility artifact. It is not one assigned job, instance, assignment or answer. `compile_cmt(task_family="IC-APPROVAL-APPLICABILITY")` reads the existing `institutional_v02` contract, the class binding and the committed, pinned profile `IC-FIRST-LIGHT-MIN-1` and returns a `CompiledCMT`:

- `manifest` (`CMTManifest`, schema `sn87-cmt/0.1`, lifecycle `draft`)
- `compatibility` (`CompatibilityReport`, schema `sn87-cmt-compat/0.1`): the bindings (canonicalizer `gra/0.1`, profile commitment, class binding, capsule and differential `institution/0.2`, bundle `sn87-evidence-bundle/0.3`), the bindings deliberately not made (`NOT_BOUND`) and diagnostics. An unresolved obligation is a diagnostic, never fabricated validity. A profile whose bytes differ from its pinned commitment, or an unknown family, raises `CMTCompileError`.

Only `IC-APPROVAL-APPLICABILITY` compiles; `TYPE-C-RELEASE` is rejected in v0.1.

## Fields (spec section 4)

| Block | Backed today | `not_in_v0_1` |
|---|---|---|
| identity | task and class id, version, canonicalization id, capsule/differential schema, source references | none |
| question | plain-language task, claim ontology (defect codes), response states, required evidence kinds, exclusions | allowed transformations, source mappings |
| disclosure | supported mode, declared limits, `private_data_embedded: false` | evidence-access policy refs, benchmark reuse grant |
| evaluation | profile id and commitment (from the committed profile), per-rule references, finding equivalence, false-positive floor, abstention state, no-valid-row behavior, applicability minimum | score/epoch/weight policy references |
| operations | resource limits with units (bytes, events, commitments), replay binding facts | time limits, instance expiry, method capabilities, authentication, lease/retry identity, feedback/reveal |
| renewal | generator reference and grammar id, baseline comparator, exposure note | holdout rules, observable-view admission tests |
| observability | identity chain source, capsule, class/profile, differential, evaluation | assignment, consumer disposition, aggregation boundaries |

Unspecified items are the literal `not_in_v0_1` (also listed in `manifest.not_in_v0_1`); nothing is invented to fill them. Profile values are copied verbatim from the committed document (decimals stay strings).

## Canonical hashing

CMT bytes are `canonical.canonical_bytes` (`gra/0.1`); there is no second canonicalizer. Duplicate keys, non-NFC text, noncanonical bytes and floats are rejected (`parse_canonical` on read). A CMT holds integers and strings only, so the `.17g` float rule of `scoring.wire` never applies. The commitment is `canonical.object_commitment(manifest, "SN87:CMT:gra/0.1")`, domain-separated from the profile, evidence and other commitments. The existing helper only accepts `SN87:<NAME>:<schema>` domains, hence this form rather than `sn87/cmt/0.1`. API: `cmt_canonical_bytes`, `cmt_commitment`, `parse_cmt`, `verify_cmt`, `compiled_bytes`. The golden vector is `tests/cmt_vectors/ic_approval_applicability.cmt.json` (fictional, public), pinned in `tests/test_cmt.py`. JSON Schemas: `protocol/v0alpha1/schemas/cmt-manifest.schema.json` and `cmt-compatibility-report.schema.json`.

## What it is NOT

Not an adopted wire schema or a mandatory object; not a new class, scorer or weighting policy; not an instance, assignment or lease; not semantic truth, author authorization, consent or access enforcement; not a signature; no hidden data, seeds or answer keys. Compilation establishes structure and reproducibility only.

## Gaps against spec section 6

Open: signatures and consent/access enforcement; time and numeric conventions beyond `gra/0.1`; instance state machine (queued, leased, completed, expired, invalid) and stale-lease fencing, which exist only in the local `service/queue.py` and are not bound; public conformance vectors beyond the one golden CMT; human task card; the v0alpha1 `AssuranceRequest`/`AssuranceResponse` models (different encoding from `institution/0.2`, reported `NOT_BOUND`); measurement of raw cost with units and missingness (profile cost coefficients stay inactive); a gap map for the remaining spec fields before any normative freeze.
