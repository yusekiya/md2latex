# Rule: template selection (extensible)

## Selection order (implemented in `select_template`)

1. **Frontmatter tag match** — first matching row of the `TAG_RULES` table wins.
2. **Japanese body** → `general_jp`.
3. **Otherwise** → `general_en`.

`TAG_RULES` (top of `scripts/md2latex.py`) is a priority-ordered list:

```python
TAG_RULES = [
    ("lecture/exercise", "exercise"),
    # add future tag -> template rows here
]
```

## How to add a new tag/template (the required extension path)

The README states new selector tags will appear over time, so adding one must be
a one-line change plus assets:

1. Create `skills/md2latex/templates/<name>/{main.tex, latexmkrc}`; optionally
   split the preamble into `config.tex` (`\input{config}` in `main.tex` — the
   converter copies it next to the output automatically). Templates with a
   `config.tex` defining the callout/theorem envs should also be added to
   `CALLOUT_TEMPLATES` in the script so Obsidian callouts map onto them.
2. Add a row to `TAG_RULES`, e.g. `("lecture/report", "report")`.
3. Add `<name>` to `VALID_TEMPLATES`.
4. Add a `tests/sample_<name>.md` fixture and verify it compiles.

No other code changes are needed — rendering is template-agnostic except for the
`exercise`-only `subproblems` handling (gated on `template == "exercise"`).

## Language detection

`is_japanese` compares kana+kanji vs. Latin letters in the body. It is a
heuristic; the agent or user can override with `--template`. Keep it dependency-
free. If it misclassifies real documents, prefer adjusting the heuristic over
adding a language library.

## Engine per template (must match the shipped `latexmkrc`)

| template     | class         | engine    |
| :----------- | :------------ | :-------- |
| `general_jp` | `ltjsarticle` | LuaLaTeX  |
| `exercise`   | `ltjsarticle` | LuaLaTeX  |
| `general_en` | `scrartcl`    | pdfLaTeX  |

A LuaLaTeX template must ship the LuaLaTeX `latexmkrc` (`pdf_mode=4`); a
pdfLaTeX template the pdfLaTeX one (`pdf_mode=1`).
