# Rule: architecture & responsibility split

## Principle

Two-stage pipeline that minimizes model tokens:

1. **Script (deterministic, 0 tokens)** — `scripts/md2latex.py` does every
   mechanical conversion and writes a complete, template-assembled `.tex` plus
   `latexmkrc`. It also prints a **post-edit hints** report to stderr.
2. **Agent (semantic, minimal tokens)** — Claude edits only the few spots the
   hints name: meaningful equation-label names, prose cross-references
   (`\eqref`/`\ref`), caption gaps, subproblem/list grouping, then compiles.

Rule of thumb: *if it can be decided without understanding the meaning of the
prose, it belongs in the script.* If it needs judgment about what the author
meant (which label, which reference, what caption), it belongs in the hints.

## Data flow

```
target.md ──▶ parse frontmatter ──▶ select template ──▶ extract H1-down body
          ──▶ segment into blocks ──▶ render blocks (inline conv.) ──▶ assemble
          ──▶ write <basename>.tex + latexmkrc (+ config.tex) ──▶ print hints (stderr)
                                                        │
                                                        ▼
                                          agent applies targeted Edits ──▶ latexmk
```

## Script internals (`scripts/md2latex.py`)

- **stdlib only** (portability for `gh skill`; no PyYAML/pandoc).
- `parse_frontmatter` — minimal YAML, extracts only `tags`.
- `select_template` / `is_japanese` — see template-selection rule.
- `segment` — line-based block segmentation (code, math, heading, figure,
  blockquote, callout, table, list, paragraph). A blockquote whose first line
  is `[!type]` becomes a `callout` block (so it is never mistaken for a caption).
- `Renderer` — renders blocks; associates `>` blockquotes with the adjacent
  figure (below) / table (above) as captions; converts Obsidian callouts into
  the template's `callout`/box environments (`CALLOUT_THEOREM_MAP` /
  `CALLOUT_BOX_ENVS` tables at the top of the script; recursive render of the
  body; degrades to `quote` on templates without callout envs); groups exercise
  subproblems; numbers `eq/fig/table` labels deterministically.
- `Inline` — converts text spans only; protects inline code/math/URLs, converts
  decoration/links/footnotes, escapes a minimal set of specials. **Never** runs
  on math or code content.
- `assemble` — substitutes `\title`, injects `hyperref` only when links are
  used, inserts the body after `\maketitle`. `convert` copies the template's
  `latexmkrc` while rewriting its `@default_files` target from `main.tex` to
  `<basename>.tex` (so a bare `latexmk` builds the output), and also copies the
  template's `config.tex` (the split-out preamble, `\input{config}`) next to
  the output when the template ships one.
- Hints — equation tag→label map, figure/table source-number→label map, empty
  captions, reference candidates (regex, line numbers), subproblem ranges.

## Why the script does NOT rewrite prose cross-references

Detecting "式(1)" vs. an enumeration "(1)" reliably needs context. The script
reports candidates instead, so it never emits a wrong reference; the agent
verifies and rewrites them. This keeps the deterministic stage correct-by-design.

## Invariants

- Source Markdown is read-only.
- Only grammar is translated; wording is preserved.
- No personal data in any output (`\author{names}` stays a placeholder).
