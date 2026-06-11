---
tags:
  - note/general
---

# A General English Note

This is an English document, so the `general_en` template should be selected.
It uses **bold**, _italic_, and `inline code`.

## Mathematics

A display equation:

$$
\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}
$$

And a multi-line one:

$$
\begin{gather}
a = b \tag{1} \\
c = d
\end{gather}
$$

See Eq. (1) above. A footnote follows.\footnote{An existing LaTeX footnote.}

## A table

| Name  | Value |
| :---  | ----: |
| alpha | 1     |
| beta  | 2     |

Percent signs like 50% and ampersands a & b are escaped in prose.

## Theorems and callouts

> [!definition] Inner product
> For vectors $a, b$ the inner product is
> $$
> \braket{a, b} = \sum_i a_i b_i
> $$

> [!theorem] Cauchy–Schwarz inequality
> For any vectors, $|\braket{a, b}|^2 \le \braket{a, a}\braket{b, b}$ holds.

> [!remark]
> An untitled remark with _italic_ text.

> [!corollary] List-first body
> - the body starts directly with a list
> - the head must still end its own line

> [!summary]
> A summary box using its default title.

> [!info] Extra information
> An info box with an explicit title.
