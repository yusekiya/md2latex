# Rule: skill development, packaging & operational guardrails

## Operational guardrails (do not violate)

- **The repository is public** at <https://github.com/yusekiya/md2latex>.
  Routine pushes and GitHub Releases (see *Release / version bump* below) are
  expected maintenance; still pause before irreversible actions (force-push,
  deleting tags/releases).
- **No personal data anywhere.** Outputs may be published. Keep `\author{names}`
  a placeholder; never embed real names, emails, IDs, or passwords in code,
  templates, fixtures, docs, or generated `.tex`.

## `gh skill` packaging

- Layout follows the `gh skill` convention: `skills/<name>/SKILL.md` (plus
  `scripts/`, `reference/`, `templates/`). This repo uses `skills/md2latex/`.
- `SKILL.md` frontmatter requires `name` (lowercase-hyphen, matches the dir) and
  `description`; `license` is optional (this skill declares `license: MIT`).
- Keep the skill **self-contained**: only relative references inside
  `skills/md2latex/`. `scripts/md2latex.py` resolves templates relative to its
  own location (`Path(__file__).parent.parent/"templates"`), so it works from
  any working directory and any install location.
- `gh skill install` writes provenance metadata into `SKILL.md` frontmatter on
  install — do not add it by hand.
- `gh skill preview` does **not** accept a local path (it only fetches from a
  GitHub repository, e.g. `gh skill preview yusekiya/md2latex md2latex` for the
  published version). Validate local changes by converting the `tests/`
  fixtures and compiling them instead (see the maintenance checklist below).

## SKILL.md authoring

- Keep it short and action-oriented; push detail into `reference/*` (progressive
  disclosure). The model reads `reference/conversion-spec.md` /
  `reference/post-editing.md` only when needed.
- The runtime workflow is: run the script → read stderr hints → apply only those
  edits → compile → report. Never re-scan the whole document.

## Maintenance checklist (per change)

1. Update `scripts/md2latex.py` **and** `reference/conversion-spec.md` together.
2. Update/extend `tests/sample_*.md` and re-run all three through the converter.
3. Compile each with `latexmk` (Lua/pdf as per template) — confirm no errors and
   no undefined references after the semantic pass.
4. Keep `general_jp`/`exercise` on LuaLaTeX and `general_en` on pdfLaTeX.

## Release / version bump (publishing a new skill version)

`gh skill install` / `gh skill update` resolve the latest **GitHub Release**, not
the latest git tag — a tag alone is invisible to installers. A version bump is
"published" only once a Release exists. Use semver `vX.Y.Z` tags (feature add →
minor, e.g. `v1.3.0` → `v1.4.0`; bugfix → patch).

Steps, once the maintenance checklist above passes:

1. Commit to `main` and push — **Claude may do both** (routine maintenance).
2. Annotated tag + push it — **Claude may do both**:
   `git tag -a vX.Y.Z -m "…"` then `git push origin vX.Y.Z`.
3. Create the Release from that tag:
   `gh release create vX.Y.Z --title vX.Y.Z --notes-file <notes.md>`.
   **`gh release:*` is in the user's `deny` list (`~/.claude/settings.json`), so
   Claude cannot run this and must not try to edit settings to bypass it.** Claude
   prepares the notes file and hands the user the exact command to run themselves
   (e.g. `! gh release create …`).
4. Refresh installed copies: `gh skill update --all` (run from `$HOME`, **not**
   inside this repo). The skill is installed at **user scope for more than one
   agent** (`~/.claude/skills/md2latex` for Claude Code, `~/.copilot/skills/md2latex`
   for GitHub Copilot); a home-dir update refreshes all of them, so seeing two
   `✓ Updated md2latex` lines is expected, not a duplicate bug. Verify with
   `grep github-ref <install>/SKILL.md` → `refs/tags/vX.Y.Z`.

Gotcha: running `gh skill list`/`update` *inside* this repo also surfaces the
source tree as a `project`-scope `n/a (published)` entry with no metadata — ignore
it; only the `$HOME`-scope copies are real installs to update.
