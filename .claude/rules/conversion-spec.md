# Rule: conversion grammar (where the spec lives)

The **canonical** Markdown→LaTeX grammar mapping is shipped with the skill at
`skills/md2latex/reference/conversion-spec.md`. Treat that file as the single
source of truth — it travels with the skill when installed via `gh skill`, so it
must stay complete and self-contained.

This rule records only the **design intent** so the two never drift:

- Keep the spec file and `scripts/md2latex.py` in lock-step. When you change a
  conversion behavior, update both the code and the spec file in the same change,
  and adjust the `tests/` fixtures.
- The spec deliberately documents *grammar only*. Anything requiring semantic
  judgment (label names, prose cross-references, caption text) is intentionally
  left to the agent's post-edit pass — see
  `skills/md2latex/reference/post-editing.md`.
- Captions come from a `>` blockquote adjacent to the figure (below) or table
  (above); when absent, the caption is **empty** (`\caption{}`) and the author's
  content is never invented.
- Inline conversion is applied to text spans only; math and code are protected.
  Prose escaping is intentionally minimal (`% & # _`) to avoid breaking
  math/commands; widen it only with a matching test fixture.

When you need the actual rules/examples, open the shipped spec file rather than
duplicating them here.
