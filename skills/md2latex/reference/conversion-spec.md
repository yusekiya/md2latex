# Conversion specification (authoritative)

This is the canonical Markdown → LaTeX grammar mapping implemented by
`scripts/md2latex.py`. It is self-contained so the skill works after the
original development `instruction/` directory is removed.

General principles:

- The Markdown source is never modified.
- Only **grammar** is translated; the author's wording is preserved verbatim.
- Deterministic parts are done by the script; semantic parts (label names,
  cross-references, captions) are reported as hints for the agent to finish.

## Scope of conversion

- Only the content **from the first H1 (`# `) line downward** is converted.
  Anything above the first H1 (including the YAML frontmatter) is dropped.
- The H1 text becomes the document title (`\title{...}`).

## Template selection

Selection is data-driven and extensible (`TAG_RULES` table in the script):

1. If the frontmatter `tags:` list contains a mapped tag, use its template.
   Currently: `lecture/exercise` → `exercise`. Add rows to extend.
2. Otherwise, if the body is Japanese → `general_jp`.
3. Otherwise → `general_en`.

Language is detected by comparing kana+kanji vs. Latin-letter counts.

| template     | document class | engine (latexmkrc) |
| :----------- | :------------- | :----------------- |
| `general_jp` | `ltjsarticle`  | LuaLaTeX (`pdf_mode=4`) |
| `exercise`   | `ltjsarticle`  | LuaLaTeX (`pdf_mode=4`) |
| `general_en` | `scrartcl`     | pdfLaTeX (`pdf_mode=1`) |

## Headings

| Markdown | LaTeX |
| :------- | :---- |
| `# Title` (first) | `\title{Title}` |
| `## X`   | `\section{X}` |
| `### X`  | `\subsection{X}` |
| `#### X` | `\subsubsection{X}` |
| `##### X`| `\paragraph{X}` |
| `###### X`| `\subparagraph{X}` |

## Display math (`$$ … $$`)

- Plain content → wrap in `equation`:

  ```
  $$
  f(x) = \sin \theta
  $$
  ```
  →
  ```latex
  \begin{equation}
  f(x) = \sin \theta
  \end{equation}
  ```

- Content that already opens with an environment (`align`, `gather`, `alignat`,
  `multline`, …) → keep the environment, drop the `$$` fence, and strip the
  trailing `\\` on the last row:

  ```
  $$
  \begin{align}
  f(x) &= \sin \theta \tag{1} \\
  g(x) &= \cos \theta \\
  \end{align}
  $$
  ```
  →
  ```latex
  \begin{align}
  f(x) &= \sin \theta \label{eq:eq1} \\
  g(x) &= \cos \theta
  \end{align}
  ```

- `\tag{N}` → `\label{eq:eqN}` (placeholder; the agent may rename it to a
  semantic label such as `eq:sin_function`).
- Inline math `$ … $` is unchanged (identical in LaTeX).

## Blank lines & paragraph structure

In LaTeX a blank line starts a new (indented) paragraph, so blank lines are not
cosmetic. The converter reproduces the source's paragraph structure rather than
padding every block:

- Between ordinary blocks, a blank line is emitted **only where the source had
  one**; adjacent blocks stay tight (single newline, same paragraph).
- A **display-math environment is always tight** with its neighbours (no blank
  line before/after), so an equation embedded in running text does not split the
  surrounding paragraph. Markdown usually requires blank lines around `$$`; those
  are intentionally dropped.
- `<span></span>` on its own line is an **explicit blank-line marker** (authors
  use it, e.g. in Obsidian, to force a paragraph break). It is rendered as a kept
  blank line — never as literal text — and overrides math tightness, so it is the
  way to force a paragraph break right after an equation.

## Tables

A blockquote **immediately above** a pipe table is its caption (the leading
`表N` / `図N` / `Table N` / `Figure N` label word is stripped, lines joined).
Column alignment: `:---:` → `c`, `:---` → `l`, `---:` → `r`.

```
> 表1 テーブルの例．
> この場合は中央揃えとなっている．

| a     | b     |
| :---: | :---: |
| 1     | 2     |
| 3     | 4     |
```
→
```latex
\begin{table}[h]
  \centering
  \caption{テーブルの例．この場合は中央揃えとなっている．}
  \label{table:table1}
  \begin{tabular}{ cc }
  \hline
  a & b \\
  \hline
  1 & 2 \\
  3 & 4 \\
  \hline
  \end{tabular}
\end{table}
```

## Figures

Obsidian embeds `![[file.ext#…|alt]]` and Markdown images `![alt](path)` become
a `figure`. A blockquote **immediately below** the image is its caption.

```
![[file.pdf#page=1&rect=5,3,219,177&width=300|fig_ans_1-1d, p.1]]

> 図1 図のキャプション．
> 図の説明文．
```
→
```latex
\begin{figure}[h]
  \centering
  \includegraphics[width=0.65\linewidth]{file.pdf}
  \caption{図のキャプション．図の説明文．}
  \label{fig:fig1}
\end{figure}
```

**Captions are optional.** When there is no adjacent blockquote, the caption is
left empty: `\caption{}` (never invent caption text).

## Cross-references

The script does **not** rewrite prose references (to avoid false positives); it
lists candidates as hints. The agent rewrites them:

- Equation refs (e.g. `式(1)`, `ベクトル(3)`) → `\eqref{eq:…}`.
- Figure / table refs (e.g. `図1`, `表1`) → `\ref{fig:…}` / `\ref{table:…}`.
- Section refs (e.g. `第2節`) → add `\label{sec:…}` to the section, then `\ref`.
- Label prefixes by kind: section `sec:`, equation `eq:`, figure `fig:`, table `table:`.
- **Always put a non-breaking space `~` between the leading reference word and
  the macro**, so the word and number never split across a line break:
  `式~\eqref{eq:…}`, `図~\ref{fig:…}`, `表~\ref{table:…}`,
  `Eq.~\eqref{eq:…}`, `Fig.~\ref{fig:…}`, `Table~\ref{table:…}`. (When the number
  is embedded in a word with no leading label, e.g. `第2節` → `第\ref{sec:…}節`,
  there is no `~` to add.)

## Callouts (Obsidian) → theorem / box environments

A blockquote whose first line is `[!type]` (optionally `[!type]+` / `[!type]-`,
optionally followed by a title) is an **Obsidian callout**, not a quote/caption.
The callout body is full Markdown and is converted recursively (math, lists,
decoration, …).

The `general_jp` / `general_en` templates define the target environments in
their `config.tex`. Mapping (tables `CALLOUT_THEOREM_MAP` / `CALLOUT_BOX_ENVS`
at the top of the script):

- **Theorem-like types** → `\begin{callout}[{Title}]{env} … \end{callout}`
  (the optional `[{Title}]` is omitted when the callout has no title):

  | callout type | env | callout type | env |
  | :--- | :-- | :--- | :-- |
  | `[!theorem]` | `thm` | `[!assumption]` | `asm` |
  | `[!lemma]` | `lem` | `[!definition]` | `dfn` |
  | `[!proposition]` | `prop` | `[!remark]` | `rem` |
  | `[!corollary]` | `cor` | `[!exercise]` | `exc` |
  | `[!conjecture]` | `conj` | `[!law]` | `law` |

  The **numbered** environments are used; switch to the starred variant
  (`thm*`, …) by hand if numbering is unwanted. `law` requires a title; a
  title-less `[!law]` is emitted as `[{}]` and flagged as a hint.

- **Box types** → the standalone box environments:
  `[!objective]` → `objective`, `[!summary]` → `summary`, `[!info]` → `info`
  (`objective`/`summary` fall back to their default titles when none is given).

- **Unknown types** (e.g. `[!note]`) → an `info` box with the author's title
  preserved; a hint is emitted so the agent can pick a better environment.

Example:

```
> [!theorem] コーシー・シュワルツの不等式
> 任意のベクトルに対して次が成り立つ．
> $$
> |\braket{a, b}|^2 \le \braket{a, a} \braket{b, b}
> $$
```
→
```latex
\begin{callout}[{コーシー・シュワルツの不等式}]{thm}
任意のベクトルに対して次が成り立つ．
\begin{equation}
|\braket{a, b}|^2 \le \braket{a, a} \braket{b, b}
\end{equation}
\end{callout}
```

The `exercise` template has no callout environments: a callout there degrades
to a `quote` (title kept as a bold lead line) and a hint is emitted.

## Footnotes

| Markdown | LaTeX |
| :------- | :---- |
| `文章^[これは脚注です．]．` | `文章\footnote{これは脚注です．}．` |
| `sentence.\footnote{Here is a footnote.}` | unchanged (already LaTeX) |

## Inline decoration & other standard grammar

| Markdown | LaTeX |
| :------- | :---- |
| `**bold**` / `__bold__` | `\textbf{bold}` |
| `_italic_` / `*italic*` | `\textit{italic}` |
| `` `code` `` | `\texttt{code}` (specials escaped) |
| `[text](url)` | `\href{url}{text}` (script injects `hyperref` when used) |
| ` ``` fenced ``` ` | `verbatim` environment |
| `- ` / `* ` list | `itemize` (nesting preserved) |
| `1. ` list | `enumerate` |
| blockquote (not a caption) | `quote` environment |

Decoration/escaping is **not** applied inside math or code. In prose, only the
LaTeX specials `% & # _` are escaped (kept minimal so math/commands are not
broken); other special characters needing escaping are surfaced via hints.

## exercise template: subproblems

Within the `exercise` template, consecutive `**(x)**`-led paragraphs become a
`subproblems` list:

```
## 問題タイトル
問題文．

**(a)** 小問

**(b)** 小問
```
→
```latex
\section{問題タイトル}
問題文．

\begin{subproblems}
\item 小問
\item 小問
\end{subproblems}
```

## Output

Into the current working directory:

- `<basename>.tex` — the assembled document (template preamble + converted body).
- `latexmkrc` — copied from the chosen template; compile with `latexmk <basename>.tex`.
- `config.tex` — the preamble settings (`\input{config}`), when the chosen
  template ships one (`general_jp` / `general_en`; `exercise` is single-file).
