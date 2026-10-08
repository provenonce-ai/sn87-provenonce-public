# Releasing

This page describes the intended release and tagging policy. It is not yet active: no release
tags exist, and none are created until a maintainer approves the first one.

## Intended policy

- A release is an annotated Git tag of the form `vMAJOR.MINOR.PATCH` on a commit that passes the
  conformance workflow on Linux and macOS.
- Each release records the weights version key it targets. Miners pin to a tag, and the tag
  states which weights version key the validator sets for that code.
- The tie between tag and weights version key starts when outside miners are weighted. Until
  then the validator is operated by Provenonce only, and a tag would imply a compatibility
  promise that nothing yet depends on.
- Tags are never moved or deleted once published. A fix is a new tag.
- Milestone tags (`milestone/<capability>-<contract-version>`) remain separate from package
  release tags, which begin with `v`.

## What a release records

- The commit and its CI result on every platform in the matrix.
- The weights version key the code sets, and the profile and scorer versions it carries.
- The attestation file that backs any run count or block number the notes cite.

## Status

Policy only. Nothing in this page changes behavior, and no tag has been created under it.
