# md2latex — developer guide

Repository that develops and packages the **`md2latex`** agent skill: it
converts a Markdown file into a compilable LaTeX document (`.tex` + `latexmkrc`).
This file is the design entry point; detailed rules are split under
`.claude/rules/` (imported below) to keep this file small.

## What this repo ships

The installable unit is **`skills/md2latex/`** (self-contained, for `gh skill`):

```
skills/md2latex/
├── SKILL.md                 # runtime instructions (gh skill frontmatter)
├── scripts/md2latex.py      # deterministic converter (stdlib only)
├── reference/               # progressive-disclosure detail
│   ├── conversion-spec.md   # canonical grammar mapping
│   └── post-editing.md      # the agent's semantic pass
└── templates/{general_jp,general_en,exercise}/{main.tex,latexmkrc}
                                                 # general_jp/general_en also ship config.tex
                                                 # (preamble incl. theorem/callout envs)
```

Everything else in the repo (this file, `.claude/`, `tests/`, `README.md`) is
**development tooling and is not shipped** by `gh skill`.

## Core design (one paragraph)

To save tokens, a Python script does all *mechanical* Markdown→LaTeX grammar
conversion and writes a complete `.tex`, while the agent only performs the few
*semantic* edits the script reports as "post-edit hints" (label naming, prose
cross-references, caption gaps, subproblem grouping, flagged callouts). The Markdown source is
never modified; only grammar is translated, never wording. See
@.claude/rules/architecture.md.

## Build / test

```bash
python3 skills/md2latex/scripts/md2latex.py tests/sample_exercise.md --outdir /tmp/out
latexmk /tmp/out/sample_exercise.tex      # LuaLaTeX for jp/exercise, pdfLaTeX for en
```

Fixtures in `tests/` cover all three templates and every conversion construct.

## Rules (imported)

@.claude/rules/architecture.md
@.claude/rules/conversion-spec.md
@.claude/rules/template-selection.md
@.claude/rules/skill-development.md
