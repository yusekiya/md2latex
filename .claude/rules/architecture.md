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
target.md | dir/ ──▶ (dir) collect *.md, natural order, pick abstract, drop ref notes
          ──▶ load_md each (frontmatter, H1, body) ──▶ select template
          ──▶ segment into blocks ──▶ render blocks (inline conv. + \cite, figure copy)
          ──▶ assemble (title, abstract, body, \bibliography)
          ──▶ write <basename>.tex + latexmkrc (+ config.tex, .bib, figures)
          ──▶ print hints (stderr)
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
  `CALLOUT_BOX_ENVS` / `CALLOUT_PLAIN_ENVS` tables at the top of the script; the
  last is for non-boxed run-in envs like `sol`; recursive render of the
  body; degrades to `quote` on templates without callout envs); groups exercise
  subproblems; numbers `eq/fig/table` labels deterministically.
- `Inline` — converts text spans only; protects inline code/math/URLs, converts
  citation wikilinks (via the `Citations.cite` callback; adjacent ones merged
  into one `\cite{a,b}`; brackets enclosing only citations are dropped),
  Markdown backslash escapes (→ the literal character, `\\` kept),
  decoration/links/footnotes, escapes a minimal set of specials. **Never** runs on math or code content.
- `load_md` / `collect_dir` — per-file frontmatter/H1/body (with source line
  offset); directory listing in natural order, abstract detection
  (`ABSTRACT_STEMS`), exclusion of cited reference notes from the chapters.
  In directory mode the `Renderer` gets `heading_shift=1` (H1 → `\section`)
  and prefixes hints with the source file; `\tag` labels are de-duplicated.
- `Vault` — Obsidian-style link resolution (note dir first, then vault-wide by
  file name; lazy index). Root = nearest `.obsidian/` ancestor or `--vault`.
- `Citations` / `write_bib` — first ```` ```bibtex ```` record of a linked note →
  cite key; each key added once; an existing `.bib` is merged (append-only).
- `Figures` — copies images next to the `.tex` (or `--figdir`), sanitizing
  names and resolving clashes; missing files are reported, never faked.
- `indent_environments` — post-pass on the generated abstract+body (called
  from `assemble`): re-indents every line by two spaces per `\begin`/`\end`
  depth; renderers emit flat text and leave indentation to it. `verbatim`
  bodies and their `\end` line are left at column 0.
- `assemble` — substitutes `\title` (kept as placeholder when there is no
  title), injects `hyperref` only when links are used, inserts the abstract
  and body after `\maketitle`, adds `\bibliography` when something is cited. `convert` copies the template's
  `latexmkrc` while rewriting its `@default_files` target from `main.tex` to
  `<basename>.tex` (so a bare `latexmk` builds the output), and also copies the
  template's `config.tex` (the split-out preamble, `\input{config}`) next to
  the output when the template ships one.
- Hints — equation tag→label map, figure/table source-number→label map, empty
  captions, reference candidates (regex, `file:line` source positions),
  subproblem ranges, unresolved wikilinks, missing/renamed figures, bib summary.

## Why the script does NOT rewrite prose cross-references

Detecting "式(1)" vs. an enumeration "(1)" reliably needs context. The script
reports candidates instead, so it never emits a wrong reference; the agent
verifies and rewrites them. This keeps the deterministic stage correct-by-design.

## Invariants

- Source Markdown is read-only.
- Only grammar is translated; wording is preserved.
- No personal data in any output (`\author{names}` stays a placeholder).
