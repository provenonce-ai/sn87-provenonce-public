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

## From change notes to a release

Release notes are written as the work happens, one short note per change, and assembled when a
version is cut.

1. **Every change adds a note.** A pull request that changes `src/`, `scripts/` or a public
   document adds `changes/<name>.<type>.md` (type `added`, `changed`, `fixed`, `security` or
   `docs`), or carries the label `no-changelog` when nothing a reader can see has changed. The
   `changelog` workflow reports a missing note on the pull request; it is advisory, not a required
   check. `changes/README.md` and the section "Writing a change note" in
   [CONTRIBUTING.md](../../CONTRIBUTING.md) say how to write one.
2. **Every note is checked on every pull request.** `scripts/check_release_notes.py` runs in the
   conformance workflow. It reads `CHANGELOG.md` and everything under `changes/`, ignores letter
   case, and fails on internal labels, names and local paths, addresses and hosts that are not
   on the allowed list, market and fund words, customer names, mainnet dates, and the style
   rules the export applies to the whole tree. It has no allow-list.
3. **Cutting the notes.** A maintainer runs, on a clean checkout of `main`:

   ```bash
   uv run python scripts/release_notes.py --version X.Y.Z --date YYYY-MM-DD --title "Release title" --dry-run
   uv run python scripts/release_notes.py --version X.Y.Z --date YYYY-MM-DD --title "Release title"
   ```

   The dry run prints the release text and the planned moves and writes nothing. The real run
   inserts a `## [X.Y.Z] - YYYY-MM-DD` section into `CHANGELOG.md` (sections Added, Changed,
   Fixed, Security, Docs, in that order; notes sorted by name), writes the release text to
   `dist/RELEASE_NOTES_X.Y.Z.md` (ignored by git; `--out` names another place), and moves the
   used notes to `changes/archive/X.Y.Z/` with `git mv`. The same notes and arguments always
   give the same bytes. It refuses when the version already has a section or an archive
   directory, when there are no notes, when a note is malformed, and when any text fails the
   word check. It creates no tag and no release.
4. **Review.** The `CHANGELOG.md` and archive change goes through a normal pull request, and
   the weights version key, profile and scorer versions and attestation file named under "What a
   release records" are filled in by hand in that pull request.
5. **Tag and release (public repository, by the repository owner only).** After the pull
   request is merged and the public repository carries the same commit, the owner creates the
   annotated tag `vX.Y.Z` on the public repository and publishes a release from that tag using
   `dist/RELEASE_NOTES_X.Y.Z.md` as its body. Contributors and automation do not create tags or
   releases; the script prints the tag name for the owner to use.

## Status

Policy and tooling. Nothing in this page changes the behavior of the validator or the scorer,
and no tag has been created under it.
