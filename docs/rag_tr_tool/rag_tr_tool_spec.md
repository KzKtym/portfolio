# RAG実験管理ツール 仕様書

## コンセプト
RAG開発のプロセス把握や記録作業を容易にするとともに、効率的な学習ツールにもなる事も意図して次の機能を実現する。
- 実験記録を見やすく管理でき、複数の実験結果やパラメータを容易に比較できること
- パイプライン構成や設定値を簡単に変更できるよう、シンプルな書式のパラメータテキスト化
- パイプライン構成を構造的にも分かりやすく字下げした一覧で表示し、スナップショットとして記録もできること

## 目次

1. [システム概要](#1-システム概要)
2. [用語集](#2-用語集)
3. [動作環境](#3-動作環境)
4. [データモデル](#4-データモデル)
5. [ディレクトリ構成](#5-ディレクトリ構成)
6. [処理パイプライン（core層）](#6-処理パイプラインcore層)
7. [実験パラメータ リファレンス](#7-実験パラメータ-リファレンス)
8. [インデックスのキャッシュ機構](#8-インデックスのキャッシュ機構)
9. [Web層（画面とAPI）](#9-web層画面とapi)
10. [SPEC抽出機構](#10-spec抽出機構)
11. [開発ルール](#11-開発ルール)
12. [既知の制約](#12-既知の制約)
13. [付録A：ドキュメントと実装の相違点](#付録aドキュメントと実装の相違点)
14. [付録B：マイグレーション履歴](#付録bマイグレーション履歴)

---

## 1. システム概要

### 1.1 何をするツールか

**RAGシステムのパラメータを変えながら検索精度を測定し、その結果を記録・比較するための実験台**です。

RAGの検索精度は、チャンクサイズ・検索方式・クエリ書き換えの有無など多数のパラメータの組み合わせで決まります。どの組み合わせが最良かは理論的には決まらず、**実際に測ってみるしかありません**。しかし手作業で試すと「どの設定で何点だったか」がすぐ分からなくなります。

本ツールは以下を自動化します。

| やること | 内容 |
|---|---|
| **実験の実行** | パラメータを画面で指定 → 検索を実行 → 精度（MRR / Recall@5）を算出 |
| **結果の永続化** | パラメータ・スコア・検索ログ・SPECスナップショットをDBとファイルに保存 |
| **比較** | 2つの実験を並べ、パラメータ差分・スコア差分・SPEC差分を表示 |
| **インデックス再利用** | 同一設定のベクトルインデックスをハッシュで識別しキャッシュ（再構築は数分かかるため） |

**評価対象コーパスは FastAPI 公式ドキュメント（Markdown）**です。汎用のRAGライブラリではなく、特定コーパスに対する**チューニング用の実験環境**である点に注意してください。

### 1.2 このツールが「測っているもの」

重要な前提です。本ツールが測るのは **検索（Retrieval）の精度のみ**で、LLMの回答品質ではありません。

```
質問 ──▶ [検索] ──▶ 関連しそうな文書チャンク ──▶ [LLM] ──▶ 回答
          ↑                                        ↑
     ここを測る                              ここは測らない
   （MRR / Recall@5）                    （LLM回答生成はおまけ機能）
```

「正解の文書を検索結果の何番目に持ってこられたか」を採点します。LLMによる回答生成機能（`generate_answers`）もありますが、**これは目視確認用のおまけであり、スコアには一切影響しません**。

### 1.3 全体の流れ

```
┌─ 準備（1プロジェクトにつき1回）────────────────────────┐
│                                                          │
│  data/rag_tr_tool/raw/fastapi/docs/*.md   ← 評価対象コーパス
│  data/rag_tr_tool/pj_{id}/evaluation_queries.json ← 正解データ
│                                                          │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─ 実験1回の流れ ──────────────────────────────────────────┐
│                                                          │
│  ① パラメータ指定（new画面）                             │
│         │                                                │
│         ▼                                                │
│  ② インデックス構築 or キャッシュロード                  │
│     Markdown → チャンク分割 → ベクトル化 → FAISS + BM25   │
│         │                                                │
│         ▼                                                │
│  ③ 評価ループ（クエリの数だけ繰り返す）                  │
│     クエリ → [書き換え] → 検索 → [Re-rank] → [フィルタ]  │
│           → 正解と照合して MRR / Recall を計算            │
│         │                                                │
│         ▼                                                │
│  ④ 保存                                                  │
│     DB: Experiment レコード（スコア・パラメータ・SPEC）   │
│     ファイル: ログ・詳細JSON・Rewrite分析JSON             │
│         │                                                │
│         ▼                                                │
│  ⑤ result画面に描画                                      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 2. 用語集

RAGに不慣れな方は、まずここを押さえてください。

### 2.1 RAGの基本要素

| 用語 | 意味 | 本システムでの実装 |
|---|---|---|
| **コーパス** | 検索対象の文書集合 | FastAPI公式ドキュメントの `.md` ファイル群 |
| **チャンク（chunk）** | 文書を検索単位に切り分けた断片。長すぎると無関係な内容が混ざり、短すぎると文脈が失われる | `core/chunking/` |
| **Embedding（埋め込み）** | 文章を数百次元の数値ベクトルに変換すること。意味が近い文章はベクトルも近くなる | `BAAI/bge-small-en-v1.5`（ローカル実行、CPU） |
| **ベクトルストア** | ベクトルを大量に保持し、近いものを高速検索するデータ構造 | FAISS |
| **Retrieval（検索）** | クエリのベクトルに近いチャンクを取り出すこと | `core/retrieval/retriever.py` |
| **インデックス** | 上記を事前計算して保存したもの。構築に数分かかるためキャッシュする | `pj_{id}/index/{hash8}/` |

### 2.2 検索方式

| 用語 | 意味 |
|---|---|
| **similarity** | ベクトルの近さ（内積 or L2距離）だけで上位k件を取る。最も基本的な方式 |
| **MMR** (Maximal Marginal Relevance) | 「クエリに近い」だけでなく「既に選んだものと似すぎていない」ことも考慮し、**結果の多様性**を確保する方式。`lambda_mult` で両者のバランスを調整 |
| **BM25** | ベクトルを使わず、**単語の一致**で採点する古典的な全文検索アルゴリズム。固有名詞や専門用語に強い |
| **Hybrid** | ベクトル検索とBM25の結果を **RRF** で統合する方式 |
| **RRF** (Reciprocal Rank Fusion) | 複数の検索結果を統合する手法。各結果での順位の逆数 `1/(rrf_k + rank)` を足し合わせる。スコアのスケールが違う検索方式同士でも統合できるのが利点 |

### 2.3 クエリ加工

| 用語 | 意味 |
|---|---|
| **Query Rewrite** | ユーザーのクエリをLLMで検索向きに書き直し、**元クエリと書き直しクエリの両方**で検索して結果を統合する |
| **Multi Query** | LLMでクエリのバリエーションを複数生成し、**全部で検索**して結果を統合する。Rewriteより網羅性が高い |
| **Gating（ゲーティング）** | 「元クエリの検索結果が既に十分良い」場合に、Multi Queryを**あえて実行しない**判定。LLM呼び出しコストの削減と、余計なクエリによる精度悪化の防止が目的 |
| **Re-ranker** | 検索で取れた候補を、より精度の高い（が重い）モデルで**採点し直して並べ替える**。検索は粗く多めに取り、Re-rankerで絞るのが定石 |
| **Cross-Encoder** | Re-rankerの一種。クエリとチャンクを**セットで**モデルに入れて関連度を出す。ベクトルの内積より精度が高いが、候補数だけモデル実行が必要で遅い |

### 2.4 評価指標

正解データ `evaluation_queries.json` には、各クエリに対する**正解文書のパス（`relevant_sources`）**が人手で定義されています。

| 指標 | 定義 | 直感 |
|---|---|---|
| **MRR** (Mean Reciprocal Rank) | 正解が最初に現れた順位の逆数の平均。1位なら1.0、2位なら0.5、3位なら0.333…、圏外なら0.0 | **「正解をどれだけ上位に置けたか」**。順位に敏感 |
| **Recall@5** | 上位5件の中に正解が1つでもあれば1、なければ0。その平均 | **「そもそも拾えたか」**。順位は問わない |

```
例：正解が3位にある場合
  MRR      = 1/3 = 0.333   （上位に置けていないので低い）
  Recall@5 = 1             （5件以内には入っているのでヒット扱い）
```

MRRが低くRecall@5が高い → 「拾えてはいるが上位に持ってこられていない」 → **Re-rankerが効く可能性がある**、といった読み方をします。

> **注意**：`recall_at_5` というフィールド名ですが、実装は `recall_at_k(results, relevant_sources, k=p.top_k)` であり、**`top_k` の値で計算されます**。`top_k=10` で実験すると、`recall_at_5` カラムには実質 Recall@10 が入ります。画面表示が `Recall@K` となっているのはこのためです。

---

## 3. 動作環境

| 項目 | 内容 |
|---|---|
| OS | WSL2（Ubuntu 24） |
| 言語 | Python 3.12 |
| フレームワーク | Django 5.1 |
| DB | PostgreSQL（`portfolio_db` / ユーザー `admin`） |
| 仮想環境 | `.venv` |
| 起動 | `python manage.py runserver` |
| GPU | Intel Iris Xe（**CUDA不可・CPU推論のみ**） |

### 主要パッケージ

| パッケージ | 用途 |
|---|---|
| `sentence-transformers` | Embedding（`SentenceTransformer`）と Re-ranker（`CrossEncoder`） |
| `faiss` | ベクトルインデックス |
| `langchain-text-splitters` | Markdownチャンキング（デフォルト方式） |
| `rank-bm25` | BM25検索（`BM25Okapi`） |
| `numpy` | ベクトル演算 |

### 外部API

| 項目 | 内容 |
|---|---|
| プロバイダ | OpenAI |
| モデル | `gpt-4.1-mini`（Query Rewrite / Multi Query / LLM回答生成 すべて共通） |
| 呼び出し方法 | `urllib.request` による直接POST（SDK不使用） |
| APIキー | `app/rag_tr_tool/config.json` の `openai_api_key` |

> **🔴 セキュリティ上の注意**
> 現在の実装はAPIキーを `config.json` に平文で保持しています。このファイルがリポジトリに含まれる場合、キーが漏洩します。
> プロジェクト内の他アプリと同様に `python-decouple` の `config('OPENAI_API_KEY')` による環境変数管理へ移行してください。移行が必要なのは以下2箇所の `_get_api_key()` です。
> - `core/llm/openai_client.py`
> - `core/rewrite/query_rewriter.py`

**CPU推論のみ**という制約から、インデックス構築とRe-rankerの実行には相応の時間がかかります。UIに「時間がかかります」の警告が出るのはこのためです。

---

## 4. データモデル

### 4.1 概念モデル

```
RagProject （実験のグルーピング単位）
    │
    │  1 : N
    ▼
Experiment （実験1回＝1レコード）
    │
    │  1 : N（ファイルシステム上で exp_{id} を接頭辞に紐づけ。DB上のリレーションではない）
    ▼
ログファイル群（.log / .json / _answers.json / _rewrite.json）
```

**プロジェクト**は「実験セット」の単位です。インデックスと正解クエリはプロジェクトごとに独立します（ただし [付録A-1](#a-1-評価対象コーパスはプロジェクト別ではない) の制約あり）。

### 4.2 RagProject

`web/models.py` / テーブル名 `rag_project`

| フィールド | 型 | 制約 | 説明 |
|---|---|---|---|
| `id` | BigAutoField | PK | **フォルダ名 `pj_{id}` に使われる** |
| `name` | CharField(200) | – | プロジェクト名 |
| `short_name` | CharField(50) | – | 略称。**表示専用。フォルダ名には使わない**（略称変更の影響を受けないため） |
| `description` | TextField | blank可 | 説明。ナビバーに先頭N文字がプレビュー表示される |
| `created_at` | DateTimeField | auto_now_add | – |

### 4.3 Experiment

`web/models.py` / テーブル名 `rag_experiment`（旧名 `web_experiment`）

| フィールド | 型 | 制約 | 説明 |
|---|---|---|---|
| `id` | BigAutoField | PK | **ログファイル名 `exp_{id}.*` に使われる** |
| `project` | FK(RagProject) | CASCADE / default=1 | プロジェクト削除時、実験も削除される |
| `name` | CharField(200) | blank可 | 実験タイトル（画面から編集可能） |
| `created_at` | DateTimeField | auto_now_add | – |
| `parameters` | JSONField | – | **正規化済みパラメータdict**。実験の再現に必要な情報すべて |
| `spec_snapshot` | TextField | – | 実行時点のSPECツリー文字列（[10章](#10-spec抽出機構)参照） |
| `mrr` | FloatField | – | MRR |
| `recall_at_5` | FloatField | – | Recall@`top_k`（[2.4節](#24-評価指標)の注意参照） |
| `is_starred` | BooleanField | default=False | お気に入りフラグ |

**`parameters` と `spec_snapshot` が実験の再現性を担保する中核**です。`parameters` は「何を設定したか」、`spec_snapshot` は「そのときコードがどうRAGを構成していたか」を記録します。コードを変更しても過去の実験が何をしていたか追跡できるようにするための仕組みです。

### 4.4 正解データ：evaluation_queries.json

DBではなくファイルで管理します。配置は `data/rag_tr_tool/pj_{project_id}/evaluation_queries.json`。

```json
[
  {
    "query": "How do I define a path parameter with a type?",
    "relevant_sources": ["tutorial/path-params.md"]
  },
  {
    "query": "How to return a custom status code?",
    "relevant_sources": ["tutorial/response-status-code.md", "advanced/response-change-status-code.md"]
  }
]
```

| キー | 型 | 説明 |
|---|---|---|
| `query` | str | 評価用の質問文 |
| `relevant_sources` | list[str] | 正解文書のパス。**コーパスルートからの相対posixパス**で、チャンクの `metadata.source` と完全一致で照合される |

- `relevant_sources` を空 `[]` にすると「正解なし」クエリになります。`skip_no_answer=true` を指定すると評価から除外されます。
- **新規プロジェクト作成時は空配列 `[]` のファイルが自動生成される**ため、実験前に必ず編集が必要です。空のまま実行すると評価件数0で MRR=0.0 になります。

---

## 5. ディレクトリ構成

### 5.1 ソースコード

```
app/rag_tr_tool/
├── config.json                  ← 設定（APIキー・SPEC走査パス・説明文プレビュー長）
├── context_processors.py        ← 全テンプレートに現在のプロジェクト情報を供給
│
├── web/                         ← 【Web層】Djangoアプリ本体（INSTALLED_APPS の登録名は app.rag_tr_tool.web）
│   ├── models.py                ← RagProject / Experiment
│   ├── urls.py
│   ├── views.py                 ← 画面系ビュー
│   ├── views_api.py             ← Ajax系ビュー
│   ├── migrations/              ← 0001〜0005（付録B参照）
│   └── services/                ← 【サービス層】ビジネスロジック
│       ├── __init__.py          ← 全関数をre-export（views からは services.xxx() で呼ぶ）
│       ├── context_service.py   ← 画面コンテキスト生成
│       ├── run_service.py       ← 実験実行のオーケストレーション
│       ├── data_service.py      ← Index確認・削除・compare構築
│       └── llm_service.py       ← LLM回答生成
│
├── core/                        ← 【コア層】RAGパイプライン本体（Djangoに依存しない設計が原則）
│   ├── ingest/loader.py         ← Markdown読み込み
│   ├── chunking/
│   │   ├── langchain_chunker.py ← デフォルト方式
│   │   ├── markdown_chunker.py  ← legacy方式
│   │   └── splitter.py          ← ⚠ 未使用（付録A-6参照）
│   ├── embedding/
│   │   ├── base.py              ← 抽象基底クラス
│   │   ├── local_embedder.py    ← BGE-small-en-v1.5（実際に使われるのはこれ）
│   │   └── openai_embedder.py   ← ⚠ 未使用
│   ├── vectorstore/faiss_store.py
│   ├── indexing/index_builder.py ← インデックス構築・キャッシュ管理
│   ├── retrieval/
│   │   ├── retriever.py         ← 4つの検索方式
│   │   └── cross_encoder_reranker.py
│   ├── rewrite/
│   │   ├── query_rewriter.py
│   │   ├── rewrite_prompt.txt   ← 実行に使うプロンプト（暫定でファイル名変更でプロンプト切り替え）
│   │   ├── prompt_multi.txt     ← query_option=multi 用プロンプト
│   │   ├── prompt_domain.txt    ← query_option=rewrite ドメイン制限用プロンプト
│   │   └── prompt_general.txt   ← query_option=rewrite 用プロンプト
│   ├── llm/
│   │   ├── openai_client.py     ← 回答生成のAPI呼び出し
│   │   └── prompt_template.py
│   └── evaluation/
│       ├── __init__.py          ← re-export（呼び出し側は core.evaluation から import）
│       ├── runner.py            ← 評価ループ本体
│       ├── query_logic.py       ← マージ・ゲーティング
│       ├── metrics.py           ← MRR / Recall
│       └── params.py            ← EvalParams dataclass
│
└── utils/                       ← 【ユーティリティ層】ファイル入出力・整形
    ├── spec_extractor.py        ← SPECコメント抽出
    ├── log_formatter.py         ← ログ整形・パス解決の起点
    ├── answers_store.py         ← LLM回答の保存/読込
    └── rewrite_store.py         ← Rewrite分析データの保存/読込/集計
```

**層の依存方向**（これを崩さないこと）：

```
views / views_api  ──▶  services  ──▶  core  ──▶  （外部ライブラリ）
                            │            │
                            └──────┬─────┘
                                   ▼
                                 utils
```

- `views` は薄く保ち、ロジックは `services` に置く
- `core` は「RAGとして何をするか」だけを持ち、Djangoのモデルを知らない
- ただし現状 `core` の一部は `django.conf.settings`（`BASE_DIR` 参照）に依存しています

### 5.2 データディレクトリ

```
data/rag_tr_tool/
├── raw/fastapi/docs/*.md        ← ⚠ 評価対象コーパス【全プロジェクト共通】（付録A-1参照）
│
└── pj_{project_id}/             ← プロジェクト別。新規作成時に自動生成
    ├── evaluation_queries.json  ← 正解データ（自動生成時は空配列 [])
    ├── index/
    │   └── {hash8}/             ← パラメータのハッシュ（8桁）ごとのインデックス
    │       ├── index.faiss      ← FAISSインデックス本体
    │       ├── metadata.json    ← 各チャンクの source / section_title / header_path / chunk_index
    │       ├── texts.json       ← 各チャンクの本文（BM25再構築とログのtext表示に使用）
    │       ├── bm25.pkl         ← BM25Okapi をpickle化したもの
    │       └── params.json      ← 構築時のインデックスパラメータ＋所要時間
    ├── logs/                    ← ⚠ 実際に使われるのはこちら（"logs"、sあり）
    │   ├── exp_{id}.log         ← 書式1＋書式2の全文ログ
    │   ├── exp_{id}.json        ← details + meta（画面描画とログ再生成の元データ）
    │   ├── exp_{id}_answers.json ← LLM回答（再生成時、旧ファイルは .bak に退避）
    │   ├── exp_{id}_answers.bak
    │   └── exp_{id}_rewrite.json ← Rewrite / Multi Query 分析データ
    ├── log/                     ← ⚠ 自動生成されるが誰も使わない空ディレクトリ（付録A-2参照）
    └── raw/                     ← ⚠ 自動生成されるが誰も読まない空ディレクトリ（付録A-1参照）
```

**ログファイルの命名規則が実験IDと直結している**点が重要です。DB上に外部キーはなく、`exp_{Experiment.id}` という命名だけで紐づいています。実験削除時（`delete_experiments_service`）は、この規則に従って5種類のサフィックス（`.log` / `.json` / `_answers.json` / `_answers.bak` / `_rewrite.json`）を手動で削除しています。

---

## 6. 処理パイプライン（core層）

`run_evaluation()`（`core/evaluation/runner.py`）が全体を統括します。

```
run_evaluation(params, rebuild, project_id)
  │
  ├─ ① EvalParams.from_dict(params)          パラメータをdataclassへ
  │
  ├─ ② build_index(params, rebuild, project_id)
  │      キャッシュあり → ロードして即返す
  │      キャッシュなし → Ingest → Chunking → Embedding → FAISS+BM25 → 保存
  │
  ├─ ③ Retriever(store, embedder) を生成
  │     reranker="cross" なら CrossEncoderReranker をここで1回だけロード
  │
  ├─ ④ evaluation_queries.json を読み込み
  │
  ├─ ⑤ クエリごとにループ ────────────────────┐
  │      skip_no_answer 判定                    │
  │      query_option により分岐（下記6.5）     │
  │      MRR / Recall を加算                    │
  │      details / rwa_queries に記録           │
  │   ←──────────────────────────────────────┘
  │
  └─ ⑥ 集計して dict を返す
         {status, metrics, meta, details, rwa_queries}
```

### 6.1 Ingest（読み込み）

`core/ingest/loader.py::load_markdown_documents(base_path)`

- `base_path` を `rglob("*.md")` で再帰探索
- 戻り値：`[{"source": <base_pathからの相対posixパス>, "text": <ファイル全文>}, ...]`
- `source` はそのままチャンクのメタデータになり、`relevant_sources` との照合キーになります

> **注意**：同ファイル内の `strip_frontmatter()` はYAMLフロントマターを除去する関数ですが、**`load_markdown_documents()` からは呼ばれていません**（`load_markdown_documents_old()` のみが使用）。したがって現状、フロントマターはチャンクに含まれたままです。

### 6.2 Chunking（分割）

`chunker` パラメータで2方式を切り替えます。

#### `chunker=langchain`（デフォルト）

`core/chunking/langchain_chunker.py`

1. `MarkdownHeaderTextSplitter` で `#`〜`####` の見出し単位に分割（`strip_headers=False` なので見出し行も本文に残る）
2. `RecursiveCharacterTextSplitter(chunk_size, chunk_overlap=overlap)` で長すぎるものを再分割

出力される各チャンク：

| キー | 内容 |
|---|---|
| `chunk_id` | `{source}::chunk_{0000}` |
| `source` | 元ファイルの相対パス |
| `section_title` | 最も深い見出しのタイトル（無ければ `"root"`） |
| `header_path` | 見出し階層のリスト（例：`["FastAPI", "Tutorial", "Path Parameters"]`） |
| `chunk_index` | 通し番号 |
| `token_count` | **文字数**（名前に反してトークン数ではない） |
| `text` | 本文 |

#### `chunker=legacy`

`core/chunking/markdown_chunker.py`

正規表現で見出しを検出 → セクションごとに段落単位でパッキング → 溢れたらハードスプリット。

> ⚠ **この方式には複数の既知の不具合があります。[付録A-5](#a-5-legacyチャンカーの不具合4件) を必ず確認してください。**

### 6.3 Embedding（ベクトル化）

`core/embedding/local_embedder.py`

| 項目 | 内容 |
|---|---|
| モデル | `BAAI/bge-small-en-v1.5`（384次元） |
| 正規化 | `normalize_embeddings=True`（ベクトル長1に正規化 → 内積＝コサイン類似度になる） |
| バッチ | `build_index` 側で100件ずつ処理 |

**プレフィックス規約（BGE系モデルの作法）**：

| 対象 | プレフィックス | 付与箇所 |
|---|---|---|
| チャンク | `"passage: "` | `index_builder.build_index()` |
| クエリ | `"query: "` | `retriever.search()` |

**このプレフィックスは非対称に付きます。** BM25検索には**プレフィックスなしの生クエリ**が使われます（`retriever.search()` の `raw_query`）。

> Embeddingモデルはパラメータ化されておらず**固定**です。変更する場合は全インデックスの再構築が必要になります。

### 6.4 VectorStore と Index

`core/vectorstore/faiss_store.py::FAISSStore`

| 項目 | 内容 |
|---|---|
| `faiss_index_type=flatip` | `IndexFlatIP`（内積）。正規化済みベクトルとの組み合わせでコサイン類似度になる。**デフォルト** |
| `faiss_index_type=flatl2` | `IndexFlatL2`（ユークリッド距離）。**値が小さいほど類似**という逆向きのスコアになる |
| BM25 | `add()` の中で `BM25Okapi(tokenized, k1=bm25_k1, b=bm25_b)` を構築。トークナイズは**単純な空白split**（`t.split()`） |

**スコアの向きが `flatip` と `flatl2` で逆転する**点に注意してください。MMR選択ロジック（`_search_mmr`）はこれを `self.store.faiss_index_type == "flatip"` で判定し符号を反転させています。

`save()` が書き出すファイル：`index.faiss` / `metadata.json` / `texts.json` / `bm25.pkl`（BM25がある場合のみ）。

### 6.5 Retrieval（検索）

`core/retrieval/retriever.py::Retriever.search()`

```
search(query, k, search_type, fetch_k, lambda_mult, rrf_k)
  │
  ├─ query に "query: " を付与してベクトル化
  │
  ├─ search_type == "mmr"        → _search_mmr(k, fetch_k, lambda_mult)
  ├─ search_type == "hybrid"     → BM25なし? → _search_similarity にフォールバック
  │                                BM25あり? → _search_hybrid(k, fetch_k, rrf_k)
  ├─ search_type == "bm25"       → BM25なし? → _search_similarity にフォールバック
  │                                BM25あり? → _search_bm25(k)
  └─ その他                       → _search_similarity(k)
```

戻り値は共通で以下の形式のリストです。以降の全処理（merge / rerank / metrics）がこの形に依存します。

```python
[{"rank": 1, "score": 0.87, "metadata": {"source": "...", ...}, "text": "..."}, ...]
```

| 方式 | 動作 |
|---|---|
| **similarity** | FAISSで上位k件。`idx == -1`（該当なし）はスキップ |
| **MMR** | `fetch_k` 件を候補取得 → ベクトルをL2正規化 → `lambda_mult * クエリ類似度 - (1-lambda_mult) * 選択済みとの最大類似度` が最大のものを貪欲に k 件選択 |
| **Hybrid** | ベクトル検索 `fetch_k` 件 + BM25上位 `fetch_k` 件 → **RRF**（`1/(rrf_k + rank)` の和）で統合 → 上位k件。**スコアはRRFスコアに置き換わる**（元の類似度ではない） |
| **BM25** | BM25スコア上位k件のみ。ベクトル検索は一切使わない（ただしクエリのベクトル化自体は実行される） |

**BM25フォールバック**：`bm25.pkl` を持たない古いインデックスで `hybrid`/`bm25` を指定すると、警告カウントを増やして `similarity` に切り替わります。評価ループ終了後に1行だけ警告が出ます。

```
[Retriever] WARNING: BM25 not available, fell back to similarity search. count=3/20, query_no=[1, 5, 12]
```

### 6.6 Re-ranking

`core/retrieval/cross_encoder_reranker.py`

| 項目 | 内容 |
|---|---|
| モデル | `cross-encoder/ms-marco-MiniLM-L-6-v2`（約22Mパラメータ）**固定** |
| 入力 | `(query, chunk_text)` のペア |
| 動作 | 全ペアを採点 → **降順ソート → rank振り直し**。件数は絞らない |
| スコア | 既定では**元の検索スコアを保持**（`rerank_score=False`）。順序だけが変わる |

`reranker="cross"` 指定時のフロー：

```
_search() で rerank_k 件取得（candidate_k は無視される）
      ↓
reranker.rerank() で並べ替え
      ↓
_apply_score_threshold() で top_k 件に絞る
```

`query_option=rewrite/multi` の場合はマージ**後**の結果に再適用されます。

### 6.7 スコアフィルタ

`runner.py::_apply_score_threshold()`

```python
if score_threshold is None or not results:
    return results[:top_k]
# min-max正規化してから閾値でフィルタ
filtered = [r for r in results if (r.score - s_min)/(s_max - s_min) >= score_threshold]
filtered = filtered[:top_k]
return filtered if filtered else results[:top_k]   # ← 0件になったら元の結果を返す
```

- **正規化はクエリ内の相対評価**です。絶対的なスコアの閾値ではありません（1件しかなければ `denom=1.0` で0除算は回避）
- **0件になった場合はフィルタを諦めて元の結果を返す**仕様です（評価が壊れないようにするための安全弁）
- `candidate_k` を指定すると、フィルタ前に `top_k` より多く取得できます

### 6.8 Query Option（クエリ加工）

#### `query_option=None`（既定）

そのまま検索するだけです。

#### `query_option=rewrite`

```
クエリ ──┬─────────────────────▶ _search() ──▶ results_original ──┐
         │                                                          ├─▶ merge_results() ──▶ top_k
         └─▶ rewrite_query() ──▶ _search() ──▶ results_rewrite ────┘
                  (LLM)
```

`merge_results()`：**original優先で重複sourceを排除**し、先頭から `top_k` 件に切って rank を振り直します。スコアは統合せず、**順序だけのマージ**です。

`rewrite_query()` はLLM呼び出しに失敗すると**元のクエリをそのまま返す**（フォールバック）ため、例外は発生しません。その代わり、APIキーが無効でも「効果がなかった」という結果に見えるので注意してください。

#### `query_option=multi`

```
                            ┌─ Gating判定 ─┐
クエリ ──▶ _search() ──▶ results_original
                            │
                    gated=True → Multiを実行せず results_original をそのまま採用
                            │
                    gated=False
                            ▼
              generate_queries() でクエリを複数生成（LLM）
                            ▼
              生成クエリごとに _search()
                            ▼
              merge_by_score() でスコア統合 ──▶ top_k
```

**Gating（`is_gated()` / `query_logic.py`）**

元クエリの検索結果から2つの指標を計算します。

| 指標 | 定義 | 意味 |
|---|---|---|
| `g_top1` | 1位のスコア | 「一番の候補にどれだけ自信があるか」 |
| `g_margin` | 1位のスコア − 2位のスコア | 「1位が2位をどれだけ引き離しているか」 |

| `gate_mode` | 判定式 | gated=True のとき |
|---|---|---|
| `None` | – | 常にMulti実行（ゲーティング無効） |
| `"top1"` | `g_top1 > gate_top1` | Multiをスキップ |
| `"margin"` | `g_margin > gate_margin` | Multiをスキップ |
| `"standard"` | `g_top1 > gate_top1 and g_margin > gate_margin` | Multiをスキップ |

> `gate_top1` の既定値が **1.1** なのは意図的です。正規化済みベクトルの内積は最大1.0なので、**1.1を超えることはなく、事実上ゲーティングが無効になる**ためです。

**merge_by_score()（Multi Query用スコア統合）**

処理順序が重要です。

```
① 正規化（normalize）
     "minmax" → クエリ系統ごとに min-max 正規化（全同値なら denom=1.0）
     "none"   → 生スコアのまま
          ↓
② gate_score="normalized" の場合、ここでゲーティング判定
     gated なら統合せず original をそのまま返して終了
          ↓
③ original boost
     original系統の1位スコア > boost_threshold なら
     original系統の全スコアに original_boost を乗算
          ↓
④ source単位で最大スコアを採用
     merge_mode="max"      → 全系統 weight=1.0
     merge_mode="weighted" → original は 1.0、生成クエリは 0.8
          ↓
⑤ スコア降順 → top_k件 → rank振り直し
```

戻り値は **4要素タプル** `(merged, gated, g_top1, g_margin)` です。

**`gate_score` の raw / normalized の違い**

| 値 | 判定場所 | 判定に使うスコア |
|---|---|---|
| `"raw"`（既定） | `runner.py` が `is_gated()` を呼ぶ | FAISSの生スコア |
| `"normalized"` | `merge_by_score()` の内部 | min-max正規化後のスコア |

> ⚠ `gate_score="normalized"` かつ `normalize="minmax"` の場合、正規化の定義上 **`g_top1` は常に 1.0 になります**（min-maxは最大値を必ず1.0に写すため）。したがって `gate_mode="top1"` は「`1.0 > gate_top1`」という、実質的にパラメータ依存のない判定に退化します。この組み合わせで意味を持つのは `gate_mode="margin"` のみです。

### 6.9 評価とメトリクス

`core/evaluation/metrics.py`

```python
def reciprocal_rank(results, relevant_sources) -> float:
    # 上から見て最初に relevant_sources に含まれる source が見つかった rank の逆数
    # 見つからなければ 0.0

def recall_at_k(results, relevant_sources, k) -> int:
    # results[:k] に1つでも含まれれば 1、なければ 0
```

`runner.py` での集計：

```python
n = len(queries) - skipped_count
mrr_val    = round(total_mrr / n, 4)     if n > 0 else 0.0
recall_val = round(total_recall / n, 4)  if n > 0 else 0.0
```

### 6.10 戻り値の構造

```python
{
  "status": "success",                    # または "error"
  "metrics": {"mrr": 0.7234, "recall_at_5": 0.85},
  "meta": {
      "evaluation_time_sec": 12.34,
      "query_count": 20,                  # skip後の実評価件数
      "skipped_count": 2,
      "total_chunks": 4521,
      "index_creation_time": "0:03:12",   # キャッシュヒット時はparams.jsonの記録値
      "chunk_stats": {"avg": 480, "max": 500, "min": 12},
  },
  "details": [...],                       # クエリ単位の検索結果（result画面とログの元データ）
  "rwa_queries": [...],                   # rewrite/multi時のみ。Rewrite分析データ
}
```

> ⚠ **`run_evaluation()` は処理全体を単一の `try/except Exception` で包んでおり、あらゆる例外を `{"status": "error", "error": str(e)}` に変換します。**
> 呼び出し側の `run_experiment_service()` はこの `error` を参照せず、`metrics.get("mrr", 0.0)` により **MRR=0.0 の実験レコードを「実行完了（保存OK）」として保存します**。
> **結果として「検索精度が悪くて0.0」と「例外で落ちて0.0」が画面上で区別できません。** 詳細は [付録A-3](#a-3-coreの例外が実験成功として記録される)。


---

## 7. 実験パラメータ リファレンス

### 7.1 一覧

**Index列 = 〇** のパラメータはインデックスのハッシュ計算に使われます（[8章](#8-インデックスのキャッシュ機構)）。値を変えると**インデックスの再構築が発生します**（数分かかります）。

| Key | 値 | 既定 | Index | 効く場所 | 説明 |
|---|---|---|---|---|---|
| `chunk_size` | 整数 | 500 | **〇** | Chunking | チャンクの最大文字数 |
| `overlap` | 整数 | 100 | **〇** | Chunking | チャンク間の重複文字数（⚠legacyでは[ほぼ機能しない](#a-5-legacyチャンカーの不具合4件)） |
| `chunker` | `langchain` / `legacy` | `langchain` | **〇** | Chunking | 分割方式 |
| `faiss_index_type` | `flatip` / `flatl2` | `flatip` | **〇** | VectorStore | 内積 or L2距離 |
| `top_k` | 整数 | 5 | – | 全体 | 最終的に採用する件数。**Recall@Kのkも兼ねる** |
| `search_type` | `similarity` / `mmr` / `hybrid` / `bm25` | `similarity` | – | Retrieval | 検索方式 |
| `fetch_k` | 整数 | 20 | – | Retrieval | MMR/Hybridの候補取得数。`mmr`/`hybrid` 時のみ自動挿入 |
| `lambda_mult` | 小数 | 0.5 | – | Retrieval | MMRの多様性係数（1.0=関連度のみ / 0.0=多様性のみ）。`mmr` 時のみ |
| `bm25_k1` | 小数 | 1.5 | – | VectorStore | BM25の語頻飽和制御。`hybrid`/`bm25` 時のみ |
| `bm25_b` | 小数 | 0.75 | – | VectorStore | BM25の文書長正規化。`hybrid`/`bm25` 時のみ |
| `rrf_k` | 整数 | 60 | – | Retrieval | RRFの平滑化定数。大きいほど順位差の影響が小さくなる。`hybrid` 時のみ |
| `score_threshold` | 小数 | なし | – | フィルタ | 正規化後スコアの下限。省略時は自動挿入なし |
| `candidate_k` | 整数 | なし | – | フィルタ | フィルタ前の取得件数。`score_threshold` 指定時のみ自動挿入 |
| `query_option` | `rewrite` / `multi` | なし | – | クエリ加工 | 省略時は無効 |
| `original_boost` | 小数 | なし | – | Multi統合 | originalスコアの乗数 |
| `boost_threshold` | 小数 | なし | – | Multi統合 | `original_boost` を適用するtop1閾値 |
| `gate_top1` | 小数 | 1.1 | – | Gating | top1閾値 |
| `gate_margin` | 小数 | 0.0 | – | Gating | margin閾値 |
| `gate_mode` | `standard` / `top1` / `margin` | なし | – | Gating | 未指定時は自動推論（[7.3](#73-自動識別)） |
| `gate_score` | `raw` / `normalized` | `raw` | – | Gating | 判定に使うスコア種別。`gate_mode` 指定時のみ自動挿入 |
| `merge_mode` | `max` / `weighted` | なし | – | Multi統合 | スコア統合方式 |
| `normalize` | `minmax` / `none` | なし | – | Multi統合 | スコア正規化方式 |
| `skip_no_answer` | `true` / `false` | `false` | – | 評価 | `relevant_sources` が空のクエリを除外 |
| `reranker` | `cross` | なし | – | Re-rank | 省略時は無効 |
| `rerank_k` | 整数 | 20 | – | Re-rank | Re-rankerへの入力候補数。`reranker` 指定時のみ自動挿入 |

> **Embeddingモデルはパラメータ化されていません**（`BAAI/bge-small-en-v1.5` 固定）。変更する場合は全インデックスの再構築が必要です。

### 7.2 パイプラインのどこに効くか

```
 [Ingest]     （パラメータなし）
     │
 [Chunking]   chunk_size / overlap / chunker                    ─┐
     │                                                           │ Index
 [Embedding]  （固定）                                           │ ハッシュ
     │                                                           │ 対象
 [VectorStore] faiss_index_type / bm25_k1 / bm25_b              ─┘※k1,bは対象外
     │
 [Retrieval]  top_k / search_type / fetch_k / lambda_mult / rrf_k
     │
 [Re-rank]    reranker / rerank_k
     │
 [Filter]     score_threshold / candidate_k
     │
 [Metrics]    top_k（Recall@Kのk）/ skip_no_answer

 ※クエリ加工は Retrieval を包む形で作用：
   query_option / gate_* / merge_mode / normalize / original_boost / boost_threshold
```

**`bm25_k1` / `bm25_b` はインデックス構築時に使われるにもかかわらず、ハッシュ対象外**です。これは意図的な設計で、[8章](#8-インデックスのキャッシュ機構)で説明します。

### 7.3 自動識別

#### query_option の正規化（`normalize_query_option()`）

| 入力 | 結果 |
|---|---|
| `"multi"` | `"multi"` |
| `"rewrite"` / `"true"` / `True` | `"rewrite"` |
| `None` / `False` / `"false"` / その他の文字列 | `None` |

#### gate_mode の自動推論

`gate_mode` 未指定時、`gate_top1` / `gate_margin` の**キーの有無**（値ではない）から推論します。明示指定があればそちらが優先されます。

| `gate_top1` | `gate_margin` | 推論結果 |
|---|---|---|
| あり | なし | `"top1"` |
| なし | あり | `"margin"` |
| あり | あり | `"standard"` |
| なし | なし | `None`（無効） |

この推論は **`EvalParams.from_dict()`（Python側）と `new.js` の `validateAndComplete()`（JS側）の2箇所に実装があります**。片方だけ変更すると挙動が食い違うので注意してください。

### 7.4 正規化（`EvalParams.normalize()`）

画面から届く生dictを、DB保存前にクリーンにします。**キャッシュのハッシュ一致に直結する重要処理**です。

| 処理 | 例 |
|---|---|
| キー・値のクォート除去 | `'"top_k"'` → `top_k` |
| 数値文字列 → int | `"5"` → `5` |
| 数値文字列 → float | `"0.5"` → `0.5` |
| 整数値のfloat → int | `5.0` → `5` |
| 非数値文字列は素通し | `"langchain"` → `"langchain"` |

**「整数値のfloat → int」が特に重要**です。`chunk_size=500` と `chunk_size=500.0` はハッシュ文字列 `chunk_size=500` / `chunk_size=500.0` が異なるため、正規化しないと同じ設定で別インデックスが作られてしまいます。

### 7.5 バリデーションと自動補完（JS側）

パラメータの既定値補完・整合性チェックは**サーバーではなくブラウザ側**（`static/rag_tr_tool/common.js` + `new.js`）で行われます。

- `PARAM_ORDER`：パラメータの表示順（パイプライン順のグループ2次元配列）
- `PARAM_DEFS`：各パラメータの `default`（`null` = 自動挿入しない）/ `values`（許容値。`null` = 数値チェックのみ）/ `condition`（条件付き補完）

`validateAndComplete()` が行うこと：

| チェック | 内容 |
|---|---|
| 旧パラメータ名 | `OBSOLETE_PARAMS = ['max_chars', 'query_rewrite']` を検出してエラー |
| 既定値補完 | `default` が `null` でないキーを自動挿入 |
| 条件付き補完 | `search_type` に応じて `fetch_k`/`lambda_mult`/`bm25_*`/`rrf_k` を挿入 など |
| gate_mode推論 | 上記7.3の推論をJS側でも実施し、パラメータ欄に挿入 |
| 不要パラメータ | `condition` が不成立なのに指定されている場合はエラー（例：`search_type=mmr` なのに `rrf_k` が残っている） |
| 許容値・型 | `values` リストとの照合／数値型チェック。エラーは全件まとめて表示 |

> **設計上の注意**：`run_experiment` ビューは `parameters` が空dictの場合のみ弾き、**値の妥当性はサーバーで検証していません**。JSを経由しない経路（curl等）で不正な値を送ると、`run_evaluation` の包括 `except` に落ちて MRR=0.0 の実験として保存されます。

---

## 8. インデックスのキャッシュ機構

**本システムで最も重要かつ非自明な仕組み**です。

### 8.1 なぜ必要か

インデックス構築は「全Markdownの読み込み → チャンク分割 → 数千チャンクのCPU推論によるベクトル化」であり、**数分かかります**。一方、`top_k` や `search_type` を変えるだけの実験ではインデックス自体は同じもので構いません。そこで「インデックスの中身に影響するパラメータ」だけを取り出してハッシュ化し、ディレクトリ名にしています。

### 8.2 ハッシュの計算

`core/indexing/index_builder.py`

```python
_INDEX_PARAM_KEYS = {"chunk_size", "overlap", "chunker", "faiss_index_type"}

def get_index_dir(params, project_id):
    index_params = {k: v for k, v in params.items() if k in _INDEX_PARAM_KEYS}
    key = ",".join(f"{k}={v}" for k, v in sorted(index_params.items()))
    hash_str = hashlib.md5(key.encode()).hexdigest()[:8]
    return _DATA_DIR / f"pj_{project_id}" / "index" / hash_str
```

- `sorted()` により**キーの記述順に依存しません**
- 対象は4キーのみ。`top_k` や `search_type` を変えても**同じディレクトリを参照します**

### 8.3 search_type をハッシュに含めない理由

**これは意図的な設計判断です。**

`similarity` と `hybrid` と `bm25` が同じインデックスを共有することで、**全く同一のチャンク集合・同一のEmbeddingに対して検索方式だけを変えた、公正な比較**ができます。もし `search_type` をハッシュに含めると、方式ごとに別インデックスが作られ、「チャンクが違うから差が出たのか、検索方式が違うから差が出たのか」が切り分けられなくなります。

そのため **`bm25.pkl` は search_type に関係なく常に構築・保存されます**。

同じ理由で `bm25_k1` / `bm25_b` もハッシュ対象外です。ただしこれには副作用があります。

> ⚠ **`bm25_k1` / `bm25_b` はインデックス構築時に `BM25Okapi` へ渡されて `bm25.pkl` に焼き込まれますが、ハッシュ対象外のためキャッシュが再利用されます。**
> つまり `bm25_k1` だけを変えて再実験しても、**キャッシュヒットして古い `bm25.pkl` が読まれ、値が反映されません**。
> `bm25_k1` / `bm25_b` を変えて比較する場合は、**必ず「Index再作成」をONにしてください**。

### 8.4 キャッシュヒット判定

```python
if (index_dir / "index.faiss").exists():   # ← これだけ
    store = FAISSStore.load(str(index_dir))
    ...
    return store, embedder, creation_time
```

`index.faiss` の存在のみで判定します。`rebuild=True` の場合は先に `shutil.rmtree(index_dir)` でディレクトリごと削除します。

### 8.5 「Index有無」表示の判定（`get_index_info()`）

new画面に表示される「Index：有/無」は、上記より厳しい判定を使います。

```
① index_dir が存在しない            → 無
② index.faiss が存在しない          → 無
③ search_type が hybrid / bm25 かつ bm25.pkl が存在しない → 無
④ それ以外                          → 有（＋作成日時・所要時間・chunk統計を返す）
```

③は `_BM25_SEARCH_TYPES = {"hybrid", "bm25"}` によるもので、**BM25を必要とする検索方式なのに `bm25.pkl` がない古いインデックスを「無」と表示して再構築を促す**ための仕組みです。新たにBM25を要する `search_type` を追加した際は、この集合への追記を忘れないでください。

### 8.6 インデックスの移植

ハッシュはプロジェクトIDを含まないため、**同じパラメータなら異なるプロジェクトでも同じハッシュ値になります**。したがって `pj_1/index/{hash8}/` をフォルダごと `pj_2/index/` にコピーすれば、そのまま再利用できます。

---

## 9. Web層（画面とAPI）

### 9.1 レイヤ構造

```
URL ──▶ views.py / views_api.py ──▶ services/ ──▶ core/ ・ utils/
         (HTTPの入出力のみ)          (ロジック)      (RAG本体・IO)
```

`views` は「リクエストを解釈して services を呼び、返り値をテンプレートに渡す」だけに保つ方針です。`services/__init__.py` が全関数をre-exportしているので、views 側は常に `services.xxx()` の形で呼びます。

### 9.2 URL一覧

| URL | ビュー | モジュール | 種別 | 説明 |
|---|---|---|---|---|
| `/rag/` | （lambda） | urls | リダイレクト | → `project_list` |
| `/rag/projects/` | `project_list` | views | 画面 | GET:一覧 / POST:新規作成 |
| `/rag/projects/<id>/edit/` | `project_edit` | views | Ajax | プロジェクト編集 |
| `/rag/projects/<id>/delete/` | `project_delete` | views | Ajax | プロジェクト削除（実験もCASCADE削除） |
| `/rag/<project_id>/` | `experiment_list` | views | 画面 | 実験一覧 |
| `/rag/<project_id>/new/` | `new_experiment_view` | views | 画面 | 実験設定 |
| `/rag/<project_id>/run/` | `run_experiment` | views | 画面(POST) | 実験実行 → result描画 |
| `/rag/result/<id>/` | `result_view` | views | 画面 | 実験結果詳細 |
| `/rag/compare/` | `compare_view` | views | 画面 | 実験比較（`?ids=A&ids=B`） |
| `/rag/check-index/` | `check_index` | views | Ajax | Index有無＋SPEC取得 |
| `/rag/update-name/<id>/` | `update_name` | views | Ajax | タイトル更新 |
| `/rag/delete/` | `delete_experiments` | views | POST | 実験一括削除 |
| `/rag/toggle-star/<id>/` | `toggle_star` | views | Ajax | スター反転 |
| `/rag/log/<id>/text/` | `log_text` | views_api | Ajax | ログテキスト取得（`?fmt=1|2`） |
| `/rag/log/<id>/download/` | `download_log` | views_api | DL | `.log` ファイルダウンロード |
| `/rag/generate-answers/<id>/` | `generate_answers` | views_api | Ajax | LLM回答生成 |
| `/rag/rwa/` | `rwa_view` | views_api | Ajax | Rewrite分析データ取得（`?id_a=&id_b=`） |

> **認証は一切ありません。** 全URLが未ログインでアクセス可能です。ローカル実験ツールという位置づけによる割り切りです。

### 9.3 サービス層

| ファイル | 責務 | 主要関数 |
|---|---|---|
| `context_service.py` | 画面コンテキスト生成 | `get_new_experiment_context` / `get_experiment_list` / `get_result_data` / `get_current_project_context` |
| `run_service.py` | 実験実行のオーケストレーション | `run_experiment_service` |
| `data_service.py` | データ操作 | `get_index_check` / `delete_experiments_service` / `build_compare_data` |
| `llm_service.py` | LLM回答生成 | `generate_answers_service` |

#### run_experiment_service（実験実行の中核）

```python
def run_experiment_service(name, raw_dict, rebuild, project_id) -> dict:
    normalized_params = EvalParams.normalize(raw_dict)      # ① 正規化
    result = run_evaluation(normalized_params, rebuild, project_id)  # ② 評価実行
    spec_text = resolve_spec(normalized_params)             # ③ SPEC生成
    current_exp = Experiment.objects.create(...)            # ④ DB保存
    if result["status"] == "success":
        save_log(...)                                       # ⑤ .log 保存
        save_details_json(...)                              # ⑥ .json 保存
    if result.get("rwa_queries"):
        save_rwa_json(...)                                  # ⑦ _rewrite.json 保存
    return {...}                                            # ⑧ result.html用コンテキスト
```

#### get_experiment_list の並び順

```
QRY（評価クエリ数）降順 → MRR降順 → Recall@K降順 → ID降順
```

加えて、**ID降順の上位3件**に `new` / `1st` / `2nd` のアイコンが付与されます（`<tr data-icon="...">`）。これはスコア順位ではなく**新しさの順位**である点に注意してください。

### 9.4 画面

#### projects.html（プロジェクト管理）

- 「新規追加：」ラベルクリックでフォームを開閉
- 行クリックでそのプロジェクトのlist画面へ遷移
- 操作欄：E（編集）/ D（削除）、編集中は Cn（キャンセル）/ Sv（保存）
- 編集中の input/textarea は `onclick="event.stopPropagation()"` で行クリックを無効化
- **新規作成時に `pj_{id}/index/` `pj_{id}/log/` `pj_{id}/raw/` を生成し、空の `evaluation_queries.json`（`[]`）を配置**

#### new.html（実験設定）

- 実験タイトル初期値：同プロジェクト内に前回タイトルが無ければ `ex{MMDD-HHMM}`、有れば `前回タイトル-2`（末尾が `-n` なら `n+1`）
- パラメータ欄は `PARAM_ORDER` のグループ順（グループ内スペース区切り／グループ間改行）
- 「再確認」：`validateAndComplete()` → `checkIndex()`
- 「Run」：`validateAndComplete()` → `checkIndex()` → 確認ダイアログ → フォーム送信
- 確認ダイアログはIndex無し時／再作成ON時に「時間がかかります」を追加表示

#### list.html（実験一覧）

- ボタン：T-CC / M-CC / P-CC / A-CC / 削除 / 新規実験 / Star / 比較
- コピーボタン（複数選択時は ` | ` 区切り）

| ボタン | コピー内容 |
|---|---|
| T-CC | `ID:[値] タイトル` |
| M-CC | `ID:[値] MRR=[値],Recall@K=[値]` |
| P-CC | `ID:[値] Parameters` |
| A-CC | 上記3種を改行連結 |

  - 選択があれば選択行、なければ `data-icon="new"` の行（最新実験）をフォールバック
- 比較ボタンのURLパラメータは常に **ID小→大順**

#### result.html（実験結果）

タブ構成：`Summary`（初期）/ `Form1` / `Form2` / `Rewrite1` / `Rewrite2`（`has_rewrite_data=True` のときのみ）

`result_view` / `run_experiment` が渡すコンテキスト：

```python
{
  "exp": Experiment, "exp_params_urlenc": str, "exp_params_json": str,
  "prev_exp": Experiment | None, "has_log": bool,
  "details": list, "meta": dict,
  "answers": list, "has_answers": bool,
  "rewrite_data": list, "has_rewrite_data": bool,
  "rewrite_summary": {"improved": int, "degraded": int, "unchanged": int, "gain": int} | None,
}
```

`rewrite_data` の各要素には `calc_rewrite_data()` が以下を付与済みです。

| キー | 内容 |
|---|---|
| `results_rewrite[].is_new` | originalに無かったsourceか |
| `original_rank` / `rewrite_rank` | 正解の順位（無ければ `None`） |
| `mrr_delta` | `mrr_rewrite - mrr_original` |
| `rewrite_gain` | `mrr_delta > 0` |

> **run実行後もURLが `/<project_id>/run/` のまま**なのは、`render()` で結果を直接描画してDB再取得を省いているためです。**ブラウザ再読み込み時に再POST警告が出る**副作用があります（既知・許容済み）。

#### compare.html（比較）

- `?ids=A&ids=B` の2件のみ受け付け（それ以外は `project_list` へリダイレクト）
- SPEC差分：`difflib.SequenceMatcher` による行単位比較。全行表示し、差分箇所に `+ ` / `- ` / `  ` のGit風タグを付与
- パラメータ比較：両者のキー和集合をソートし、片方に無いキーは `-`
- 「Rewrite比較実行」ボタンは**両方の実験に `exp_{id}_rewrite.json` がある場合のみ活性**。不活性時は理由（`rwa_disabled_reasons`）を表示

### 9.5 context_processors

`app.rag_tr_tool.context_processors.current_project` を `settings.py` の `TEMPLATES[0]["OPTIONS"]["context_processors"]` に登録しています。

```python
{"current_project": RagProject | None, "project_description_preview": str}
```

URLの `project_id` から `RagProject` を引き、全テンプレートのナビバーに供給します。プレビュー文字数は `config.json` の `project_description_max_length`（既定40）。

> **既知の制約**：`result` / `compare` 画面はURLに `project_id` を含まないため、`current_project=None` となりナビバーのプロジェクト情報が消えます。許容済みの仕様です。


---

## 10. SPEC抽出機構

### 10.1 何のための仕組みか

**「この実験を実行したとき、コードはRAGをどう構成していたか」をソースコードから自動抽出し、実験結果と一緒に保存する仕組み**です。

パラメータ（`parameters`）は「何を設定したか」を記録しますが、それだけでは不十分です。たとえば `chunker=langchain` と記録されていても、半年後にlangchain_chunkerの実装を変更していたら、当時と今で意味が違います。そこで**実行時点のアーキテクチャ構成をテキストのツリーとして凍結保存**します。これが `Experiment.spec_snapshot` です。

compare画面のSPEC差分は、この凍結されたツリー同士を比較しています。

### 10.2 書き方

ソースコード中に特定形式のコメントを埋め込みます。

```python
# SPEC: 20/VectorStore/FAISS/IndexFlatIP
# SPEC_flatip: 20/VectorStore/FAISS/IndexFlatIP
```

| 形式 | 意味 |
|---|---|
| `# SPEC:` | **常に出力**される |
| `# SPEC_<タグ>:` | **条件付き出力**。タグが実験パラメータの値と一致したときだけ出力される |

値の書式は `<並び順>/<階層1>/<階層2>/...` です。**先頭が数値の場合は並び順として解釈され、ツリーのキーからは除外されます**。

### 10.3 タグとパラメータの対応

`utils/spec_extractor.py` の `_TAG_PARAM_MAP` が、タグ名 → パラメータキーの対応を定義します。

```python
_TAG_PARAM_MAP = {
    "langchain": "chunker",       "legacy": "chunker",
    "similarity": "search_type",  "mmr": "search_type",
    "hybrid": "search_type",      "bm25": "search_type",
    "flatl2": "faiss_index_type", "flatip": "faiss_index_type",
    "rewrite": "query_option",    "multi_query": "query_option",
    "multi_query_merge_max": "merge_mode",  ...
    "cross": "reranker",
}
```

判定ロジック（`scan_file()`）：

| 状況 | 動作 |
|---|---|
| タグが `_TAG_PARAM_MAP` に無い | **常に出力**（未知タグは無条件出力） |
| 対応パラメータが `None`（フィルタ未指定） | **常に出力** |
| 対応パラメータが `"__disabled__"`（番兵値） | **出力しない** |
| 対応パラメータの値 == タグ名 | **出力する** |

`"__disabled__"` は**番兵値**です。`query_option=None`（オプション無効）のようなケースで、「フィルタ未指定だから全部出す」と誤解されないよう、明示的に「どのタグにもマッチさせない」ことを表します。

### 10.4 走査対象

`config.json` の `spec_scan_paths` で指定します。

```json
"spec_scan_paths": ["core/", "core/rewrite/rewrite_prompt.txt"]
```

ディレクトリ指定の場合は `os.walk` で `.py` ファイルのみを走査します（ファイル名ソート順）。

### 10.5 resolve_spec()

`extract_spec()` を直接呼ばず、**必ず `resolve_spec(params)` を使ってください**。

```python
def resolve_spec(params: dict) -> str:
    p = EvalParams.from_dict(params)                      # gate_mode を自動推論
    return extract_spec({**params, "gate_mode": p.gate_mode})
```

`gate_mode` は明示指定されないことがあるため、推論結果を反映してからSPECを生成する必要があります。

---

## 11. 開発ルール

### 11.1 SPECコメント管理

- `# SPEC:` / `# SPEC_xxx:` コメントは **無断削除・改変禁止**
- 対象は **RAGアーキテクチャのみ**。アプリの機能や実装詳細は書かない
- 数値プレフィックスで並び順を制御する
- **すべて静的文字列で記述**（f-string等による動的生成は不可。ソースを1行ずつ読む実装のため）
- 新しい切り替えパラメータを追加したら `_TAG_PARAM_MAP` にも追記する

### 11.2 インデックス管理

- ハッシュ対象は `_INDEX_PARAM_KEYS` のみ。`search_type` / `bm25_k1` / `bm25_b` は含めない（[8.3](#83-search_type-をハッシュに含めない理由)）
- `bm25.pkl` は全インデックス構築時に常に生成する
- BM25を必要とする `search_type` を追加したら `_BM25_SEARCH_TYPES` に追記する
- インデックスはプロジェクト間で共有しない（ただしフォルダコピーによる移植は可能）

### 11.3 JSコーディングルール

- フラットスタイル統一（縦位置アラインメント禁止）
- サーバー値は **`data-*` 属性経由**でJSに渡す。`|safe` フィルタでdictを展開しない
- 数値のみ `{{ exp.id }}` で直接展開してよい
- **dictをJSに渡すときは必ず `json.dumps` 済みの正規JSON文字列を使う**（Python dictの `str()` はシングルクォートになり `JSON.parse()` が失敗する）
- `common.js` を各画面JSより先に読み込む（`PARAM_ORDER` / `PARAM_DEFS` を参照するため）

### 11.4 テンプレート

- `compare.html` は `{% extends %}` の**後**に `{% load static %}` を書く（Djangoテンプレート継承の制約）

---

## 12. 既知の制約

### 12.1 設計上の割り切り

| 項目 | 内容 |
|---|---|
| 認証なし | 全URLが未認証でアクセス可能。ローカル実験ツールという前提 |
| ナビバーのプロジェクト情報 | `result` / `compare` 画面ではURLに `project_id` が無く非表示になる |
| run実行後のURL | `/<project_id>/run/` のまま。再読み込みで再POST警告 |
| `_FakeExp` | `context_service.py` 内の暫定クラス。プロジェクト内に実験が1件も無い場合に使われる |
| CPU推論のみ | インデックス構築とRe-rankerが遅い |

### 12.2 パラメータの組み合わせに関する注意

| 組み合わせ | 注意点 |
|---|---|
| `candidate_k` + `search_type=mmr` | **逆効果**。MMRが `k=candidate_k` 件を選ぶ際に多様性ペナルティが歪む。`score_threshold` 単独使用を推奨 |
| `reranker` + `candidate_k` | `rerank_k` が優先され `candidate_k` は無視される（WARNINGログ出力） |
| `bm25_k1` / `bm25_b` の変更 | ハッシュ対象外のためキャッシュが再利用され**値が反映されない**。必ず「Index再作成」をONにすること |
| `gate_score=normalized` + `normalize=minmax` | `g_top1` が常に1.0になり `gate_mode=top1` が退化する（[6.8](#68-query-optionクエリ加工)） |
| `reranker` + `score_threshold` | Re-rankerのスコアはlogit（負値あり）。min-max正規化のため絶対値スケール差は問題ないが、**同じ閾値でもRe-ranker有無で絞り込み結果が変わる** |

### 12.3 旧データ互換

| 項目 | 対応 |
|---|---|
| `exp_{id}_rewrite.json` の形式 | 新＝リスト直接 / 旧＝`{"queries": [...]}` ラッパー付き。`read_rwa_json()` が透過的に吸収 |
| `relevant_sources` | 新規実験のみ含まれる。旧データはOriginal/Rewrite Rankが `－` 表示 |
| `details` の `mrr` キー | 旧データには無い。`correct_rank` から `1/rank` で補完（`get_result_data()` / `format_log_form1()` の両方に実装あり） |
| `bm25.pkl` | Step10以前のインデックスには存在しない。`hybrid`/`bm25` 使用時はRebuild必須 |
| `query_rewrite` キー | 旧実験の `parameters` には残る。`query_option` への互換変換は**行われない** |

### 12.4 Re-rankerのモデル

`ms-marco-MiniLM-L-6-v2` は英語Web検索向けに学習されたモデルで、**FastAPIのような技術ドキュメントとの相性は限定的な可能性があります**。モデル変更は別課題として保留中です。

---

## 付録A：ドキュメントと実装の相違点

本書の作成にあたり `handover.md` の記述とソースを突き合わせた結果、以下の相違を検出しました。**すべて実装側を正としています。**

### A-1. 評価対象コーパスはプロジェクト別ではない

| | 内容 |
|---|---|
| **引き継ぎ書の記述** | `data/rag_tr_tool/pj_{id}/raw/fastapi/docs/` |
| **実装** | `data/rag_tr_tool/raw/fastapi/docs/`（`index_builder.py:17`） |

```python
_DATA_DIR = Path(settings.BASE_DIR) / "data" / "rag_tr_tool"
_DOCS_DIR = _DATA_DIR / "raw" / "fastapi" / "docs"   # ← pj_{id} を含まない
```

**影響**：`_init_project_dirs()` は `pj_{id}/raw/` を作成しますが、**このディレクトリは誰も読みません**。全プロジェクトが同一コーパスをインデックスします。

「プロジェクトごとに別のコーパスを扱う」ことは現状**できません**。プロジェクトが分離しているのは「インデックス」「正解クエリ」「ログ」の3つだけです。プロジェクト別コーパスを実現するには `_DOCS_DIR` を `project_id` 引数で解決するよう変更が必要です。

### A-2. ログディレクトリ名の不一致（`log` と `logs`）

| | 内容 |
|---|---|
| `views._init_project_dirs()` | `["index", "log", "raw"]` を作成 ← **`log`（sなし）** |
| `utils.log_formatter.get_logs_dir()` | `pj_{id}/logs` を返す ← **`logs`（sあり）** |

**影響**：新規プロジェクト作成時に作られる `log/` は**永久に空のまま**です。実際に使われる `logs/` は `save_log()` 内の `mkdir(parents=True, exist_ok=True)` により初回書き込み時に遅延作成されます。動作はしますが、無駄な空ディレクトリが残ります。

### A-3. coreの例外が「実験成功」として記録される

`run_evaluation()` は処理全体を単一の `try/except Exception` で包み、あらゆる例外を戻り値に変換します。

```python
except Exception as e:
    return {"status": "error", "error": str(e), "meta": {...}}
```

呼び出し側の `run_experiment_service()` は：

```python
metrics = result.get("metrics", {})          # error時は {} → デフォルト値になる
current_exp = Experiment.objects.create(
    mrr=metrics.get("mrr", 0.0),             # 0.0 で保存
    recall_at_5=metrics.get("recall_at_5", 0.0),
    ...)
...
return {..., "message": "実行完了（保存OK）"}  # error時も同じメッセージ
```

**影響**：
- `result["error"]` は**どこにも表示されず破棄されます**
- coreのどこで何が落ちても、**MRR=0.0 の実験が「実行完了（保存OK）」として保存されます**
- 画面上で「検索精度が悪くて0.0」と「例外で落ちて0.0」が**区別できません**
- 失敗した実験もcompare画面に並び、SPECスナップショットまで保存されます

**これは「実験を実行すればcoreのバグは分かる」という前提を崩す最重要事項です。** 現在、修正が別途進行中です。

### A-4. `EvalParams` に存在しないフィールドが記載されている

| | 内容 |
|---|---|
| **引き継ぎ書の記述** | `EvalParams` のフィールドとして `chunk_size` / `overlap` / `chunker` / `faiss_index_type` を列挙 |
| **実装** | **これら4つは `EvalParams` に存在しません** |

これらは `build_index(params, ...)` が**生の `params` dictから直接読みます**（`params.get("chunk_size", 500)` 等）。`EvalParams` は Retrieval 以降のパラメータのみを保持します。

`EvalParams` の実フィールド（21個）：

```
top_k, search_type, fetch_k, lambda_mult, query_option,
original_boost, boost_threshold, gate_top1, gate_margin,
merge_mode, normalize, gate_mode, gate_score,
score_threshold, candidate_k, bm25_k1, bm25_b, rrf_k,
skip_no_answer, reranker, rerank_k
```

**「インデックス構築系パラメータは dict のまま、検索系パラメータは dataclass」という二重管理**になっています。新パラメータを追加する際は、どちらに属するかを意識してください。

### A-5. legacyチャンカーの不具合（4件）

`core/chunking/markdown_chunker.py` を実行して確認した挙動です。

| # | 症状 | 原因 |
|---|---|---|
| **1** | **最初の見出しより前の本文が消える** | `extract_sections()` が `match.end()` から本文を切り出すため、1つ目の見出しの前にあるテキストがどのセクションにも属さず捨てられる |
| **2** | **`overlap` がほぼ機能しない** | `recursive_split()` の段落パッキング経路では `overlap` が一切使われない。ハードスプリットのfallback経路でしか効かない |
| **3** | **`overlap >= max_chars` でクラッシュ** | `range(0, len(chunk), max_chars - overlap)` のstepが0または負になり `ValueError: range() arg 3 must not be zero` |
| **4** | **空チャンクが混入する** | 先頭段落が `max_chars` 以上のとき、空の `current` が `chunks` に追加される |

実測結果：

```
【1】入力: "この前書きは重要な内容です。\n\n# 見出し1\n本文A"
     出力: ['本文A']              ← 前書きが消失

【2】max_chars=300, overlap=100 で200文字×3段落
     出力: 3チャンク（各200文字）  ← 重複部分なし

【3】max_chars=500, overlap=500
     ValueError: range() arg 3 must not be zero

【4】先頭段落600文字, max_chars=500
     出力: ['', 'ああ…(500)', 'ああ…(200)', 'いい…(100)']   ← 先頭が空文字
```

**影響**：
- **1** はデータ欠落。実験しても「なんとなくMRRが低い」としか見えません
- **2** により、`chunker=legacy` での `overlap` 比較実験は**実質ノーオペを比較しています**
- **3** は [A-3](#a-3-coreの例外が実験成功として記録される) と結合し、MRR=0.0 の「成功した実験」として保存されます
- **4** の空チャンクは `index_builder` の `if c["text"].strip()` で除去されますが、`chunk_index` の採番はズレたままです

### A-6. `chunking/splitter.py` は未使用

`split_text_fixed()` / `split_documents()` はどこからも import されていません。かつ `split_text_fixed()` は `start = end - overlap` のため、**`overlap >= chunk_size` で無限ループします**。削除候補です。

同様に `core/embedding/openai_embedder.py` も未使用です。

### A-7. `recall_at_k` の戻り値型

| | 内容 |
|---|---|
| **引き継ぎ書の記述** | `def recall_at_k(results, relevant_sources, k) -> float` |
| **実装** | `-> int`（1 または 0 を返す） |

平均を取る `runner.py` 側で float になるため実害はありませんが、シグネチャの記述が誤っています。

### A-8. マイグレーション0005が未記載

引き継ぎ書は 0001〜0004 のみ記載していますが、実際には `0005_alter_experiment_project_alter_ragproject_id.py` が存在します（[付録B](#付録bマイグレーション履歴)）。

### A-9. web層とcore層の名前・型のドリフト（3件）

`query_rewrite` → `query_option` へのリネームが web層に反映されておらず、**実験実行以外の機能が壊れています**。

| # | 箇所 | 内容 |
|---|---|---|
| **1** | `llm_service.py:41` | `p.query_rewrite` を参照。`EvalParams` にこの属性は**無い** → **`generate_answers` は全実験で必ず `AttributeError`**。`views_api.py` の `except Exception` が拾い、**「インデックスのロードに失敗しました」という無関係なメッセージで500を返す** |
| **2** | `llm_service.py:52` | `results = merge_by_score(...)` と単一値で受けている。実際の戻り値は**4要素タプル** `(merged, gated, g_top1, g_margin)`（`runner.py:153` は正しく4つで受けている） → `AttributeError: 'list' object has no attribute 'get'` |
| **3** | `data_service.py:88` / `views_api.py:85` | `exp.parameters.get("query_rewrite", False)` を読むが、保存されるキーは `query_option` → **常に `False`**。compare画面のRWAボタン活性判定と左右の並べ替えが恒久的に機能していない |

**いずれも実験実行（`run_experiment` → `runner.py`）の経路では踏まれません。** 壊れているのは `generate_answers` / `compare` / `rwa` という別ボタンです。現在、修正が別途進行中です。

---

## 付録B：マイグレーション履歴

| # | ファイル | 内容 |
|---|---|---|
| 0001 | `0001_initial.py` | `Experiment` の初期定義（当時のテーブル名 `web_experiment`） |
| 0002 | `0002_experiment_is_starred.py` | `is_starred` 追加 |
| 0003 | `0003_ragproject_rename_experiment.py` | `RagProject` 追加 / `Experiment` の物理名を `rag_experiment` に変更 / `project` FK追加 |
| 0004 | `0004_init_default_project.py` | `RunPython` でデフォルトプロジェクト（`id=1` / `name="Default"`）を挿入し、既存 `Experiment` を `project_id=1` に更新 → `project` を NOT NULL 化 |
| 0005 | `0005_alter_experiment_project_alter_ragproject_id.py` | `Experiment.project` に `default=1` を付与 / `RagProject.id` を `BigAutoField` 化 |

**マイグレーション0004が「デフォルトプロジェクト id=1」を作る**点は重要です。`Experiment.project` の `default=1` はこのレコードの存在を前提にしています。テスト環境やDB再作成時にこのマイグレーションを飛ばすと、外部キー制約違反が発生します。

> アプリラベルが `web` である点に注意してください（`AppConfig.name = 'app.rag_tr_tool.web'` のため、ラベルは末尾の `web` になります）。マイグレーションコマンドは `python manage.py makemigrations web` です。

---

## 変更履歴

| 版 | 日付 | 内容 |
|---|---|---|
| 1.0 | 2026-07-17 | 初版。`handover.md`（チャット引き継ぎサマリー19）と実ソースの突き合わせにより作成。相違点は付録Aに記載 |
