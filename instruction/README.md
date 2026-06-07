# 指示

この資料はMarkdownファイルをLaTeXファイルに変換するスキル作成の指示書である．

## 基本方針

- Markdownファイルを受け取り，LaTeX形式のファイルを出力すること
- Markdownファイルは書き換えない．
- プログラム的に変換できる部分はスクリプトを使用し，そうでない部分は生成ファイルを書き換えることで，トークンを節約すること．
- コンパイル用のlatexmkrcファイルも出力すること
- **記述内容は書き換えずに**，MarkdownとLaTeXの文法の書き換えのみを対象とすること．
- スキル開発の方針はドキュメント化して，一貫性を保つこと
- 最終的には `gh skill` コマンド（https://cli.github.com/manual/gh_skill）でインストール可能な形にするため，それを考慮した開発を進めること


## 注意点

- instructionディレクトリは開発完了後削除されるので，このディレクトリ内のファイルを参照するのではなく，必要に応じてコピーを作成すること
- instructionディレクトリの削除はユーザーが実施する．claudeは削除しないこと．
- GitHubへのアップロードするなどの公開は，明示的なアップロード指示があるまでは禁止する
- 最終的には公開されるためパスワードや氏名などの情報は生成物に含めないこと

## 使用方法

- Markdownファイルを指定してスキルを呼び出す: `/md2latex target.md`
- 作業ディレクトリにファイルが生成される

## 生成物のディレクトリ構造

以下が，想定しているディレクトリ構造である．必要に応じて修正してもよい．

```
./project_root
├── .claude
├── README.md
├── CLAUDE.md
└── skills
    └── md2latex
        ├── SKILL.md
        ├── scripts # save scripts in this directory if any
        └── templates
            ├── general_jp
            │   ├── main.tex
            │   └── latexmkrc
            ├── general_en
            │   ├── main.tex
            │   └── latexmkrc
            └── exercise
                ├── main.tex
                └── latexmkrc
```

## 開発ドキュメント

- 設計のための情報をCLAUDE.mdに記載すること
- Claude code用の設定を，本プロジェクトの.claude/rules ディレクトリ内に分割して保存し，CLAUDE.mdの肥大化を防ぐこと
- 開発ドキュメントの管理については https://code.claude.com/docs/en/memory に記載の方法に従うこと

## テンプレート

- LaTeXファイルはテンプレートに従い生成すること
- 英語か日本語かに応じてテンプレートを切り替えること
- MarkdownファイルにYAML frontmatterがある場合，その内容に基づいてテンプレートを切り替えること
- テンプレートは`instruction/templates`に作成済み

frontmatterの例：

```markdown
---
tags:
  - lecture/exercise
---
```

### テンプレート選択ルール

1. frontmatterのtagsリストに`lecture/exercise`が含まれている場合は，`exercise`テンプレートを選択
2. 上記ルールのtagをどれも含んでない，かつ本文が日本語の場合`general_jp`テンプレートを選択
3. 上記のいずれのルールにも当てはまらない場合，`general_en`テンプレートを選択

テンプレート選択ルールのためのfrontmatterのtagは今後追加される可能性がある．よって，拡張可能な形で実装すること．

## 変換方法

変換方法の具体例を示す．

### 変換対象

- 変換対象は，MarkdownのH1ヘッダ行以下の部分だけにすること
- H1ヘッダ行よりも上は生成するLaTeXファイルに含めなくて良い

### タイトルやセクションの変換

- H1ヘッダはLaTeX文書のタイトルとし，`\title{}`マクロの引数を置き換える
- H2ヘッダ以降は順に`\section`, `\subsection`，以下同様とする

### 別行数式環境の変換

変換前
```markdown
$$
f(x) = \sin \theta
$$
```

変換後
```latex
\begin{equation}
f(x) = \sin \theta
\end{equation}
```

---

変換前
```markdown
$$
\begin{align}
f(x) &= \sin \theta \tag{1} \\
g(x) &= \cos \theta \\
\end{align}
$$
```

変換後
```latex
\begin{align}
f(x) &= \sin \theta \label{eq:sin_function} \\
g(x) &= \cos \theta
\end{align}
```

他の数式環境 `alignat`, `gather` などでも同様．


### 図表環境の変換

変換前
```markdown
> 表1 テーブルの例．
> この場合は中央揃えとなっている．

| a     | b     |
| :---: | :---: |
| 1     | 2     |
| 3     | 4     |
```

変換後
```latex
\begin{table}[h]
  \centering
  \caption{テーブルの例．この場合は中央揃えとなっている．}
  \label{table:here_is_label}
  \begin{tabular}{ cc } 
  \hline
  a & b \\
  \hline
  1 & 2  \\ 
  3 & 4  \\ 
  \hline
  \end{tabular}
\end{table}
```

---

変換前
```markdown
![[file.pdf#page=1&rect=5,3,219,177&width=300|fig_ans_1-1d, p.1]]

> 図1 図のキャプション．
> 図の説明文．
```

変換後
```latex
\begin{figure}[h]
  \centering
  \includegraphics[width=0.65\linewidth]{file.pdf}
  \caption{図のキャプション．図の説明文．}
  \label{fig:here_is_label}
\end{figure}
```

### 参照の変換

- Markdownには数式番号が`\tag`を使って付けられている場合がある．その時は，`\label`と`\eqref`を使用した参照に書き換えること
- 数式の参照は，「式(1)」や「ベクトル(3)」の様に丸括弧で番号が振られていることが多い
- 図や表の参照も`\label`と`\ref`で書き換えること
- 節番号の参照も`\label`, `\ref`で書き換えること
- ラベルには種類に応じた接頭語を付ける：節`sec:`，数式`eq:`，図`fig:`，表`table:`


### 脚注の変換

変換前
```markdown
文章^[これは脚注です．]．
sentence.\footnote{Here is a footnote.}
```

変換後
```latex
文章\footnote{これは脚注です．}．
sentence.\footnote{Here is a footnote.}
```

### 文字の装飾

- `**太字**`→`\textbf{太字}`
- `_斜体_`→`\textit{斜体}`

### exerciseテンプレートの特殊ルール

小問の問題文に独自定義環境`subproblems`環境を用いること

```markdown
## 問題タイトル
問題文．

**(a)** 小問

**(b)** 小問
```

```latex
\section{問題タイトル}
問題文．

\begin{subproblems}
\item 小問
\item 小問
\end{subproblems}
```


