# Lane One transparent toy simulation

This executable slice tests SN87's local evaluation shape without creating hidden
benchmark truth or fixing production incentive economics. It is implementation code, not a
preregistration, testnet run, or assurance result.

Run both deterministic paths:

```bash
uv run sn87-provenonce simulate-lane-one
uv run sn87-provenonce simulate-lane-one --force-no-valid-row
uv run sn87-provenonce simulate-lane-one --output-dir ./evidence/run-001
uv run sn87-provenonce verify-simulation-bundle ./evidence/run-001
```

The ordinary path evaluates four deliberately visible Type A toy cases (planted defect,
clean control, equivalent mutation, and insufficient Evidence) against four deterministic
miner behaviors. Every response validates against the existing v0alpha1 Differential
model. The report includes per-case scoring facts, a stable ranking, a local weight intent,
and its own domain-separated commitment.

The forced path supplies a disclosed `FORCED_BOUNDARY_VECTOR` in which no score exceeds the
local eligibility floor. The report records those exact weight-intent input scores separately
from the ordinary miner results, so the resulting `NO_VALID_WEIGHT_ROW` and `weights: null`
decision is reproducible. It never creates equal weights, epsilon weights, a wallet payload,
or a broadcast-capable object.

The optional evidence-bundle path creates exactly two deterministic files: the canonical
simulation report and a manifest containing its raw-byte hash and semantic commitment. Bundle
creation refuses to overwrite any existing destination. Creation and verification retain one
directory descriptor and both file descriptors through bounded double-snapshot checks. The
verifier rejects links, path substitution, membership changes, changed report bytes, commitment
mismatches, or unsupported bundle versions. Generated bundles are runtime evidence and are not
committed to this repository by default.

## Boundary

Every scoring constant is labeled `LOCAL_PROVISIONAL_NON_NORMATIVE`. The fixtures are
transparent and therefore unsuitable for measuring miner performance. The module makes no
network calls and owns no Bittensor, wallet, validator, source-system, tenant, or production
integration. Hidden challenge generation and answer custody remain outside this repository.

The released protocol specification may replace the score components,
penalties, eligibility floor, transform, challenge mix, and acceptance thresholds. Those
changes are isolated from the protocol models and require new versioned evidence before any
testnet weight behavior can be claimed.
