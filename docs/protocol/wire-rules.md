# Wire rules

## One canonicalizer

`gra/0.1`, implemented once in `sn87_provenonce/canonical.py`. It is strict:

- UTF-8, NFC text only; non-NFC text is rejected, not normalized.
- Sorted keys, no insignificant whitespace.
- Floats rejected. Integers only, bounded.
- Duplicate keys rejected. Noncanonical input bytes rejected (parse, re-emit, compare).

Every signed, committed or weight-bearing object uses it. The bundle names it by ID
(`canonicalizer_id: "gra/0.1"`).

## No mapping from v0alpha1

The legacy `src/sn87_provenonce/protocol/v0alpha1/canonical.py` normalizes to NFC and accepts floats. It is unchanged,
kept only for the `runtime/` and `simulation/` research readers of historical evidence. There is no
semantic v0alpha1 to gra mapping. Weight paths accept only strict `gra/0.1` objects; v0alpha1
objects are rejected at that boundary.

## Numbers at the report boundary

Rows, scores and weights are decimal strings. One emitter produces them: `format(x, ".17g")`.

- That is the 17-significant-digit round-trip of a binary64 value, not exact decimal arithmetic.
  `0.16000000000000003` is correct output for that double.
- Value domain: finite binary64 in [0, 1] for weights.
- Consumers parse with `Decimal`. The chain dry run quantizes each string to u16 with `Decimal`
  and cross-checks against the SDK's float path; this is why a lossless round-trip was chosen.
- Counts (`admitted`, `evaluable`) are integers.

## NA is not 0

An inactive, inapplicable or unmeasured value is the string `"NA"`, never `0`, never omitted. A
measured zero differs from missing: `"0"` with `missing: null`, versus `"NA"` with a reason such
as `NOT_MEASURED`. Eq. 11 is the one exception in raw records: eta = 1 stays numeric (all cost
coefficients 0, status `INACTIVE`).
