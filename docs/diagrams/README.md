# Diagrams

> Eight diagrams of how SN87 works. Each is checked against the code it cites, and each says what
> it does not show.

Quick links: [docs map](../README.md) | [glossary](../GLOSSARY.md) | [README](../../README.md)

GitHub draws these natively from the Mermaid text, in light and dark mode. If a diagram does not
render in your viewer, the text under it still reads as a list of boxes and arrows.

| # | Diagram | Question it answers | Audience |
|---|---|---|---|
| 1 | [System architecture](01-architecture.md) | Who does what, and what moves between them? | everyone |
| 2 | [Submission lifecycle](02-submission-lifecycle.md) | What happens to one capsule from request to score? | miners, validators |
| 3 | [Scoring pipeline](03-scoring-pipeline.md) | How does an answer become a score and a preference row? | miners, reviewers |
| 4 | [Contest window timeline](04-contest-window-timeline.md) | In what order are things committed, opened and revealed, and by when? | everyone |
| 5 | [Trust and verification chain](05-trust-chain.md) | What can I check myself, and what stays UNVERIFIED? | reviewers, validators |
| 6 | [Weight flow](06-weight-flow.md) | Do scores reach the chain, and which parts are inactive? | everyone |
| 7 | [Sandbox and trust boundary](07-trust-boundary.md) | What is private, what is public, what protects a miner's code? | miners, reviewers |
| 8 | [A miner's first day](08-miner-first-day.md) | What do I do, in order, and which steps are mine alone? | miners |

## Legend used in every diagram

| Style | Meaning |
|---|---|
| Red or pink box | private to the operator or the miner |
| Blue box | public: code in this repository or a published record |
| Green box | in use, or a step you can run on your own machine |
| Yellow box | needs a decision, a deadline, or action outside this repository |
| Dashed grey box or dashed line | committed or proposed, and inactive |

Colours are always paired with a label, so no meaning rests on colour alone.

## How these were checked

Each page lists the files its boxes come from. A box that names a function or a phase was read
from that file at the time of writing. Where the code is only partly public (the shadow service
and the operator tooling are not in this repository), the diagram says so. If a diagram and the
code ever disagree, the code is right and the diagram is a bug: please open an issue.
