# Change notes

Every change a reader of this repository can see gets a short note here, so that release notes
are assembled from what contributors wrote rather than reconstructed at release time.

## Adding a note

Create one file per change: `changes/<name>.<type>.md`.

- `<name>` is a short lower-case label such as `quickstart-fixture-scores`, or the pull request
  number such as `142`. It only needs to be unique and stable.
- `<type>` is one of `added`, `changed`, `fixed`, `security` or `docs`.
- The file holds one or two plain sentences for someone who has not followed the project: say
  what is different for them and where to look. No bullet marker, no heading, at most 600
  characters.

Example, `changes/fixture-truth.added.md`:

```text
The public fixtures now ship with their expected scores in a committed file, so the demo output
can be checked against a record instead of taken on trust.
```

Pull requests that touch `src/`, `scripts/` or the public documents need a note, or the label
`no-changelog` when nothing a reader can see has changed. See "Writing a change note" in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## What happens next

`scripts/release_notes.py` gathers the notes into a new section of `CHANGELOG.md`, writes the
text for the release page, and moves the used notes to `changes/archive/<version>/`.
`scripts/check_release_notes.py` runs in CI and refuses names and words that must not appear in
public text. The steps for a release are in
[docs/releases/RELEASING.md](../docs/releases/RELEASING.md).
