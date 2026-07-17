# RAG実験管理ツール 開発セッションサマリー（引き継ぎサマリー19）

## プロジェクト概要
FastAPIドキュメント対象のRAGシステム実験管理ツール（Django/PostgreSQL/WSL2）。
実験データをプロジェクト単位で管理する機能を追加済み。

## 環境
- Python 3.12 / Django / WSL2（Ubuntu 24）
- DB：PostgreSQL（`portfolio_db`、ユーザー：`admin`）
- GPU：Intel Iris Xe（CUDA不可、CPU推論のみ）
- 仮想環境：`.venv` / 起動：`python manage.py runserver`
- 追加パッケージ：`langchain-text-splitters` / `rank-bm25` / `sentence-transformers`（CrossEncoderを含む）
- 外部API：OpenAI（`gpt-4.1-mini`）/ APIキーは `config.json` の `openai_api_key` で管理

## ディレクトリ構成
```
project_dir/
├── app/rag_tr_tool/
│   ├── context_processors.py        ← 全テンプレートにプロジェクト情報を供給
│   ├── web/
│   │   ├── views.py              ← 画面系ビュー
│   │   ├── views_api.py          ← Ajax系ビュー
│   │   ├── services/             ← ビジネスロジック層
│   │   │   ├── __init__.py       ← 全関数をre-export
│   │   │   ├── context_service.py   ← 画面コンテキスト生成（new/list/result）+ get_current_project_context
│   │   │   ├── run_service.py       ← 実験実行
│   │   │   ├── data_service.py      ← データ操作（Index確認・削除・compare構築）
│   │   │   └── llm_service.py       ← LLM回答生成
│   │   ├── urls.py
│   │   ├── models.py
│   │   └── migrations/
│   │       ├── 0001_initial.py
│   │       ├── 0002_experiment_is_starred.py
│   │       ├── 0003_ragproject_rename_experiment.py  ← RagProject追加・Experiment物理名変更・project FK追加
│   │       └── 0004_init_default_project.py          ← デフォルトプロジェクト挿入・既存レコードproject_id=1設定
│   ├── core/
│   │   ├── evaluation/
│   │   │   ├── __init__.py              ← run_evaluation等をre-export
│   │   │   ├── runner.py                ← 評価ループ本体
│   │   │   ├── query_logic.py           ← マージ・ゲーティング処理
│   │   │   ├── metrics.py               ← MRR/Recall計算
│   │   │   └── params.py                ← EvalParams dataclass
│   │   ├── indexing/
│   │   │   ├── __init__.py
│   │   │   └── index_builder.py
│   │   ├── chunking/
│   │   │   ├── markdown_chunker.py  # legacy
│   │   │   └── langchain_chunker.py # デフォルト
│   │   ├── embedding/local_embedder.py
│   │   ├── vectorstore/faiss_store.py
│   │   ├── retrieval/
│   │   │   ├── retriever.py
│   │   │   └── cross_encoder_reranker.py  ← Re-ranker（新規追加）
│   │   ├── rewrite/
│   │   │   ├── __init__.py
│   │   │   ├── query_rewriter.py
│   │   │   ├── rewrite_prompt.txt   ← query_option=rewrite用プロンプト
│   │   │   ├── prompt_multi.txt     ← query_option=multi用プロンプト
│   │   │   └── prompt_general.txt   ← バックアップ（general版）
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── openai_client.py
│   │   │   └── prompt_template.py
│   │   └── ingest/loader.py
│   ├── utils/
│   │   ├── spec_extractor.py
│   │   ├── log_formatter.py
│   │   ├── answers_store.py
│   │   └── rewrite_store.py         ← 旧rwa_store.pyからリネーム済み
│   └── config.json
├── data/rag_tr_tool/
│   └── pj_{id}/                     ← プロジェクト別ディレクトリ（新規作成時に自動生成）
│       ├── index/{hash8}/
│       │   ├── index.faiss / metadata.json / texts.json / params.json
│       │   └── bm25.pkl
│       ├── logs/
│       │   ├── exp_{id}.log
│       │   ├── exp_{id}.json
│       │   ├── exp_{id}_answers.json    # LLM回答保存（再生成時は.bakに退避）
│       │   └── exp_{id}_rewrite.json   # Rewrite/Multi Query Analysis保存
│       ├── raw/fastapi/docs/
│       └── evaluation_queries.json     # プロジェクト別クエリファイル（新規作成時に空[]で自動生成）
├── templates/rag_tr_tool/
│   ├── base.html / new.html / result.html / list.html / compare.html
│   ├── projects.html                ← プロジェクト管理画面（新規追加）
│   ├── spec_panel.html
│   ├── llm_answers_panel.html
│   ├── rewrite_analysis_panel.html  # compare画面用（ボタン＋不活性理由表示）
│   └── rewrite_detail_panel.html    # result画面用（Rewrite/Multi Query詳細）
├── static/rag_tr_tool/
│   ├── common.js                    # PARAM_ORDER・PARAM_DEFS定義（new.js/list.js/result.jsから参照）
│   ├── new.js
│   ├── list.js
│   ├── result.js
│   ├── llm_answers.js
│   ├── projects.js                  ← プロジェクト管理画面用（新規追加）
│   └── rewrite_analysis.js          # compare画面用
└── manage.py
```

## URL構成
| URL | ビュー関数 | モジュール | 説明 |
|---|---|---|---|
| `/rag/` | redirect | urls | → `/rag/projects/` へリダイレクト |
| `/rag/projects/` | `project_list` | views | プロジェクト管理画面（GET:一覧 / POST:新規作成） |
| `/rag/projects/<id>/edit/` | `project_edit` | views | Ajax: プロジェクト編集 |
| `/rag/projects/<id>/delete/` | `project_delete` | views | Ajax: プロジェクト削除（カスケード） |
| `/rag/<project_id>/` | `experiment_list` | views | プロジェクト別実験一覧 |
| `/rag/<project_id>/new/` | `new_experiment_view` | views | 実験設定・実行 |
| `/rag/<project_id>/run/` | `run_experiment` | views | 実行POST |
| `/rag/result/<id>/` | `result_view` | views | 実験結果詳細 |
| `/rag/compare/` | `compare_view` | views | 実験比較 |
| `/rag/check-index/` | `check_index` | views | Ajax: Index有無確認＋SPEC取得（POSTボディにproject_idを含む） |
| `/rag/update-name/<id>/` | `update_name` | views | Ajax: タイトル更新 |
| `/rag/delete/` | `delete_experiments` | views | 実験一括削除（POSTにproject_idを含む） |
| `/rag/toggle-star/<id>/` | `toggle_star` | views | Ajax: スター反転 |
| `/rag/log/<id>/text/` | `log_text` | views_api | Ajax: ログテキスト取得 |
| `/rag/log/<id>/download/` | `download_log` | views_api | ログDL |
| `/rag/generate-answers/<id>/` | `generate_answers` | views_api | Ajax: LLM回答生成・保存 |
| `/rag/rwa/` | `rwa_view` | views_api | Ajax: Rewrite Analysisデータ取得 |

## DBモデル
### RagProject（新規追加）
```python
class RagProject(models.Model):
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rag_project"
```

### Experiment
```python
class Experiment(models.Model):
    project = models.ForeignKey(RagProject, on_delete=models.CASCADE, default=1)
    name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    parameters = models.JSONField()
    spec_snapshot = models.TextField()
    mrr = models.FloatField()
    recall_at_5 = models.FloatField()
    is_starred = models.BooleanField(default=False)

    class Meta:
        db_table = "rag_experiment"  # 旧: web_experiment
```

## 実験パラメータ一覧（EvalParams）

| Key名 | 値 | 既定値 | Index | 備考 |
|---|---|---|---|---|
| top_k | 整数 | 5 | － | 検索結果上位k件 |
| chunk_size | 整数 | 500 | 〇 | チャンクサイズ |
| overlap | 整数 | 100 | 〇 | チャンクオーバーラップ |
| chunker | langchain/legacy | langchain | 〇 | チャンキング方式 |
| search_type | similarity/mmr/hybrid/bm25 | similarity | － | 検索タイプ |
| fetch_k | 整数 | 20 | － | MMR/Hybrid候補数。mmr/hybrid時のみ自動挿入 |
| lambda_mult | 小数 | 0.5 | － | MMR多様性係数。mmr時のみ自動挿入 |
| faiss_index_type | flatip/flatl2 | flatip | 〇 | FAISSインデックス種別 |
| bm25_k1 | 小数 | 1.5 | － | BM25パラメータ（語頻飽和制御）。hybrid/bm25時のみ自動挿入 |
| bm25_b | 小数 | 0.75 | － | BM25パラメータ（文書長正規化）。hybrid/bm25時のみ自動挿入 |
| rrf_k | 整数 | 60 | － | RRF統合パラメータ。hybrid時のみ自動挿入 |
| score_threshold | 小数 | None | － | 正規化後スコアの下限フィルタ。省略時は自動挿入なし |
| candidate_k | 整数 | None | － | score_thresholdフィルタ前の取得件数。score_threshold指定時のみ自動挿入。省略時はtop_kと同値 |
| query_option | rewrite/multi | None | － | クエリオプションモード。省略時は自動挿入なし。自動識別1.参照 |
| original_boost | 小数 | － | － | multiモード時のoriginalスコア乗数。省略時は自動挿入なし |
| boost_threshold | 小数 | － | － | original_boost適用のtop1閾値。省略時は自動挿入なし |
| gate_top1 | 小数 | － | － | ゲーティングtop1閾値。自動識別2.参照 |
| gate_margin | 小数 | － | － | ゲーティングmargin閾値。自動識別2.参照 |
| gate_mode | standard/top1/margin | None | － | ゲーティングモード。自動識別2.参照。gate_top1/gate_marginから自動推論・自動挿入 |
| gate_score | raw/normalized | raw | － | ゲーティング判定に使用するスコア種別。gate_mode指定時のみ自動挿入 |
| merge_mode | max/weighted | － | － | multiモード時のスコア統合方式。省略時は自動挿入なし |
| normalize | minmax/none | － | － | multiモード時のスコア正規化方式。省略時は自動挿入なし |
| skip_no_answer | true/false | false | － | true=relevant_sourcesが空のクエリをスキップして評価。省略時は自動挿入なし |
| reranker | cross | None | － | Re-ranker種別。省略時は自動挿入なし |
| rerank_k | 整数 | 20 | － | Re-rankerへの入力候補数。reranker指定時のみ自動挿入 |

※ Embeddingモデル（BGE-small-en-v1.5）は現システムでは固定でパラメータ化されていないため列に含まない。モデルを変更する場合はIndex再作成が必要。

### 自動識別
1. query_option の正規化（normalize_query_option）

   `bool`/文字列で渡された値を `None` / `"rewrite"` / `"multi"` に正規化する。
   - `None` / `False` / `"false"` / その他 → `None`
   - `True` / `"true"` / `"rewrite"` → `"rewrite"`
   - `"multi"` → `"multi"`

2. gate_mode の自動推論（EvalParams.from_dict / new.js validateAndComplete）

   `gate_mode` が未指定（`None`）の場合、`gate_top1` / `gate_margin` のキーの有無から自動推論する。
   推論結果はパラメータ欄に自動挿入される。
   明示的に `gate_mode` を指定した場合はそちらが優先される。

| gate_top1指定 | gate_margin指定 | 推論されるgate_mode |
|---|---|---|
| あり | なし | `"top1"` |
| なし | あり | `"margin"` |
| あり | あり | `"standard"` |
| なし | なし | `None`（ゲーティング無効） |

ゲーティング判定式：
- `"top1"` → `g_top1 > gate_top1`
- `"margin"` → `g_margin > gate_margin`
- `"standard"` → `g_top1 > gate_top1 and g_margin > gate_margin`

判定スコアは `gate_score` に従う：
- `"raw"`：正規化前の生スコア（FAISSの内積スコア）で判定（既定）
- `"normalized"`：正規化後スコアで判定（`merge_by_score()` 内で処理）

## コンポーネント仕様

### context_processors.py
```python
def current_project(request) -> dict
    # URLのproject_idからRagProjectを取得し、全テンプレートに供給
    # {"current_project": RagProject | None, "project_description_preview": str}
    # project_description_previewの文字数はconfig.jsonの project_description_max_length で指定（既定40）
    # URLにproject_idが含まれない画面（result/compare等）はcurrent_project=None
```
`settings.py` の `TEMPLATES[0]["OPTIONS"]["context_processors"]` に以下を登録：
```
"app.rag_tr_tool.context_processors.current_project"
```

### core/evaluation/

#### __init__.py
以下をre-exportし、呼び出し側の変更不要：
```python
from .runner import run_evaluation, save_log, save_details_json
from .query_logic import normalize_query_option, is_gated, merge_results, merge_by_score
from .metrics import reciprocal_rank, recall_at_k
from .params import EvalParams
```

#### runner.py
```python
def run_evaluation(params: dict, rebuild: bool = False, project_id: int = 1) -> dict
def save_log(exp_id: int, log_text: str, project_id: int) -> Path
def save_details_json(exp_id: int, details: list, meta: dict, project_id: int) -> Path
```
- クエリファイル：`data/rag_tr_tool/pj_{project_id}/evaluation_queries.json`
- ログ保存先：`data/rag_tr_tool/pj_{project_id}/logs/`
- 戻り値：`status/metrics(mrr,recall_at_5)/meta(evaluation_time_sec,query_count,total_chunks,index_creation_time,chunk_stats)/details/rwa_queries`

query_option=rewrite 時の追加処理：
- `core/rewrite/query_rewriter.py` でクエリを書き直し
- original・rewrite両系統で検索してrankベースmerge（重複はoriginal優先）
- `rwa_queries` に各クエリのoriginal/rewrite検索結果・MRRを保存（`mode: "rewrite"`）
- 実験実行後 `exp_{id}_rewrite.json` に自動保存

score_threshold / candidate_k の処理（`_apply_score_threshold()` / `_search()` 内）：
- `candidate_k` 指定時は `candidate_k` 件で検索しフィルタ後 `top_k` 件に絞る
- `score_threshold` 指定時は正規化後スコアで下限フィルタ。0件になる場合は元結果を返す
- Re-ranker有効時は `candidate_k` を無視し `rerank_k` 件取得 → Re-rank → `_apply_score_threshold()` の順で処理

Re-rankerの処理（`runner.py` 内）：
- 評価ループ前に `CrossEncoderReranker` を一度だけロードし全クエリで使い回す
- `reranker + candidate_k` 同時指定時は `rerank_k` を優先し `candidate_k` を無視（WARNINGログ出力）
- `query_option=rewrite/multi` 時はマージ後の結果に Re-rank を適用（`_search()` 内ではなくループ内で適用）
- Re-rank はスコアリング・降順ソートのみ行い件数絞り込みは `_apply_score_threshold()` に委ねる

skip_no_answer の処理：
- `skip_no_answer=true` の場合、`relevant_sources` が空のクエリをスキップ
- `query_count` はスキップ後の実際の評価件数、`skipped_count` はスキップ件数として `meta` に記録
- result画面 summaryView の `Query count` 行に `(skipped: X)` を表示（`skipped_count > 0` の場合のみ）

BM25フォールバック発生時のWARNING出力：
- 評価ループ中のフォールバック発生はカウント・クエリ番号を記録し、ループ後に1行のみ出力
- 出力形式：`[Retriever] WARNING: BM25 not available, fell back to similarity search. count=X/Y, query_no=[1, 2, ...]`
- フォールバックが発生しない場合はWARNING出力なし

#### query_logic.py
```python
def normalize_query_option(value) -> str | None
def is_gated(results_original, gate_mode, gate_top1, gate_margin) -> tuple[bool, float, float]
def merge_results(original, rewrite, top_k) -> list   # rankベースmerge（original優先）
def merge_by_score(all_results, top_k, ...,
                   gate_score, gate_mode, gate_top1, gate_margin) -> tuple[list, bool, float, float]
    # スコアベースmerge（Multi Query用）
    # gate_score="normalized"時はmerge_by_score内でゲーティング判定を実施
    # 戻り値: (merged_results, gated, g_top1, g_margin)
```
merge_results：重複（同一source）はoriginalのrank優先、merge後top_k件に絞りrankを振り直す。

#### metrics.py
```python
def reciprocal_rank(results, relevant_sources) -> float
def recall_at_k(results, relevant_sources, k) -> float
```

#### params.py（EvalParams）
```python
@dataclass
class EvalParams:
    top_k / chunk_size / overlap / chunker / search_type / fetch_k / lambda_mult
    faiss_index_type / bm25_k1 / bm25_b / rrf_k
    score_threshold / candidate_k
    query_option / original_boost / boost_threshold
    gate_top1 / gate_margin / gate_mode / gate_score / merge_mode / normalize
    skip_no_answer
    reranker / rerank_k   # Re-ranker関連（新規追加）

    @classmethod
    def from_dict(cls, d: dict) -> "EvalParams"   # gate_mode自動推論を含む
    @staticmethod
    def normalize(d: dict) -> dict                 # 型変換・クォート除去のみ
```

### core/retrieval/cross_encoder_reranker.py（新規追加）
```python
class CrossEncoderReranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2")
    def rerank(self, query: str, results: list[dict]) -> list[dict]
        # query × chunk テキストでスコアリング・降順ソートして返す（件数絞り込みなし）
        # スコアはCross-Encoderのlogitスコア（負値になり得る）
```
- モデルはクラス内に固定。将来別モデルを追加する場合は `reranker` の許容値を増やして対応
- `reranker: "cross"` → `ms-marco-MiniLM-L-6-v2` 固定
- `sentence_transformers.CrossEncoder` を使用

### core/indexing/index_builder.py
```python
def get_index_base_dir(project_id: int) -> Path
    # data/rag_tr_tool/pj_{project_id}/index/ を返す

def get_index_dir(params: dict, project_id: int) -> Path
    # _INDEX_PARAM_KEYSのハッシュでサブディレクトリを決定

def build_index(params: dict, rebuild: bool = False, project_id: int = 1)
    # -> (store, embedder, index_creation_time)

def get_index_info(params: dict, project_id: int = 1) -> dict
    # Indexの存在確認と作成日時・所要時間・chunk統計を返す
```

### utils/log_formatter.py
```python
def get_logs_dir(project_id: int) -> Path
    # data/rag_tr_tool/pj_{project_id}/logs/ を返す  ※ディレクトリ名は "logs"（sあり）

def read_log(exp_id: int, project_id: int) -> str | None
def read_details_json(exp_id: int, project_id: int) -> dict | None
def format_log_form1(...) -> str   # 書式１（表形式）
def format_log_form2(...) -> str   # 書式２（text追加形式）
def format_log_full(...) -> str    # 書式１＋書式２（.logファイル保存用）
```

### utils/answers_store.py
```python
def save_answers_json(exp_id: int, answers: list, project_id: int) -> Path
def read_answers_json(exp_id: int, project_id: int) -> list | None
```

### utils/rewrite_store.py
```python
def save_rwa_json(exp_id: int, queries: list, project_id: int) -> Path
def read_rwa_json(exp_id: int, project_id: int) -> list | None
def calc_rewrite_data(rewrite_data: list) -> tuple[list, dict]
```

### services/（web/services/）

| ファイル | 主な責務 | 主要関数 |
|---|---|---|
| `context_service.py` | 画面コンテキスト生成 | `get_new_experiment_context` / `get_experiment_list` / `get_result_data` / `get_current_project_context` |
| `run_service.py` | 実験実行 | `run_experiment_service` |
| `data_service.py` | データ操作 | `get_index_check` / `delete_experiments_service` / `build_compare_data` |
| `llm_service.py` | LLM回答生成 | `generate_answers_service` |

#### context_service.py
```python
_DEFAULT_PARAMS = {"top_k": 5, "chunk_size": 500, "overlap": 100, "chunker": "langchain"}
    # 同プロジェクト内に実験が1件もない場合のデフォルトパラメータ

def get_new_experiment_context(params_from_list: str | None, project_id: int = 1) -> dict
    # new_experiment_view用。同プロジェクト内の最新実験パラメータを参照

def get_experiment_list(project_id: int) -> list
    # プロジェクト別の表示用データ整形済みExperimentリストを返す
    # 並び順：QRY降順 → MRR降順 → Recall@K降順 → ID降順

def get_result_data(exp_id: int) -> dict
    # result_view用。exp.project_idからパスを解決
    # 旧データのmrrキーなしはcorrect_rankからフォールバック補完

def get_current_project_context(project_id: int | None) -> dict
    # context_processor用。{"current_project": RagProject | None, "project_description_preview": str}
```

#### run_service.py
```python
def run_experiment_service(name: str, raw_dict: dict, rebuild: bool, project_id: int) -> dict
    # EvalParams.normalize() → run_evaluation(project_id) → DB保存 → ログ保存 → rwa保存
    # exp_params_urlenc/exp_params_json/message/has_log等を含む完全なコンテキストを返す
```

bm25/rrf補完はJS側（`validateAndComplete()`）に移管済み。`run_service.py` での `setdefault` 補完は廃止。

#### data_service.py
```python
def get_index_check(params: dict) -> dict
    # check_index用。paramsからproject_idをpopして get_index_info + resolve_spec の結果を返す

def delete_experiments_service(id_list: list[str]) -> None
    # exp.project_idからログディレクトリを解決し、DBレコードとログファイル5種を削除

def build_compare_data(id1: int, id2: int) -> dict
    # compare_view用。SPEC差分・パラメータ比較・rwa情報を含むコンテキストを返す
```

#### llm_service.py
```python
def generate_answers_service(exp_id: int) -> dict
    # exp.project_idからパスを解決してLLM回答生成
    # {"answers": list} または {"error": str, "answers": list, "status": int}
```

### static/

#### common.js
複数画面で共有する定数を定義。`new.html` / `list.html` / `result.html` で `common.js` を先に読み込んでから各画面のJSを読み込むこと。

```javascript
// パラメータ並び順の定義（パイプライン順、グループ単位の2次元配列）
// グループ内はスペース区切りで1行、グループ間は改行（new.jsのParameters欄表示）
// list.js / result.js ではグループ区切りなしのカンマ区切りで表示
const PARAM_ORDER = [
    ['chunk_size', 'overlap', 'chunker'],
    ['faiss_index_type'],
    ['bm25_k1', 'bm25_b'],
    ['top_k', 'search_type', 'fetch_k', 'lambda_mult', 'rrf_k'],
    ['score_threshold', 'candidate_k'],
    ['query_option', 'skip_no_answer'],
    ['gate_mode', 'gate_top1', 'gate_margin', 'gate_score'],
    ['original_boost', 'boost_threshold'],
    ['merge_mode', 'normalize'],
    ['reranker', 'rerank_k'],
];

// パラメータ既定値・許容値の定義
// default: null → 自動挿入しない（省略可能なオプションパラメータ）
// values: null  → 任意の数値（数値型チェックのみ）
// values: [...]  → 許容文字列リスト（それ以外はバリデーションエラー）
// condition: fn → 条件付き補完（search_typeに依存するパラメータ）
const PARAM_DEFS = {
    chunk_size:       { default: 500,         values: null },
    overlap:          { default: 100,         values: null },
    chunker:          { default: "langchain", values: ["langchain", "legacy"] },
    faiss_index_type: { default: "flatip",    values: ["flatip", "flatl2"] },
    top_k:            { default: 5,           values: null },
    search_type:      { default: "similarity",values: ["similarity", "mmr", "hybrid", "bm25"] },
    fetch_k:          { default: 20,          values: null,
                        condition: p => ["mmr", "hybrid"].includes(p.search_type) },
    lambda_mult:      { default: 0.5,         values: null,
                        condition: p => p.search_type === "mmr" },
    bm25_k1:          { default: 1.5,         values: null,
                        condition: p => ["hybrid", "bm25"].includes(p.search_type) },
    bm25_b:           { default: 0.75,        values: null,
                        condition: p => ["hybrid", "bm25"].includes(p.search_type) },
    rrf_k:            { default: 60,          values: null,
                        condition: p => p.search_type === "hybrid" },
    skip_no_answer:   { default: null,        values: ["true", "false"] },
    score_threshold:  { default: null,        values: null },
    candidate_k:      { default: null,        values: null,
                        condition: p => "score_threshold" in p },
    query_option:     { default: null,        values: ["rewrite", "multi"] },
    original_boost:   { default: null,        values: null },
    boost_threshold:  { default: null,        values: null },
    gate_top1:        { default: null,        values: null },
    gate_margin:      { default: null,        values: null },
    gate_mode:        { default: null,        values: ["standard", "top1", "margin"] },
    gate_score:       { default: "raw",       values: ["raw", "normalized"],
                        condition: p => "gate_mode" in p },
    merge_mode:       { default: null,        values: ["max", "weighted"] },
    normalize:        { default: null,        values: ["minmax", "none"] },
    reranker:         { default: null,        values: ["cross"] },
    rerank_k:         { default: 20,          values: null,
                        condition: p => "reranker" in p },
};
```

#### new.js
- `jsConfig` に `data-project-id` を追加。`check_index` AjaxのPOSTボディに `project_id` を含める
- 実験タイトル初期値：同プロジェクト内の前回タイトル無し → `ex{MMDD-HHMM}`、前回タイトル有り → `前回タイトル-2`（末尾が`-n`なら`n+1`）
- Parameters欄：`PARAM_ORDER` のグループ順・グループ内スペース区切り・グループ間改行で表示
- Run確認ダイアログ：タイトル＋パラメータ内容を表示。Index無し時は「時間がかかります」追加、Index有り＋再作成ONも同様
- バリデーション・補完（`validateAndComplete()`）：
  - 旧パラメータ名チェック：`OBSOLETE_PARAMS = ['max_chars', 'query_rewrite']`
  - `PARAM_DEFS` の `default` 値による既定値補完（未入力キーをパラメータ欄に自動挿入）
  - 条件付き補完（`condition` あり）：`search_type` に応じて `fetch_k` / `lambda_mult` / `bm25_k1` / `bm25_b` / `rrf_k` を挿入、`score_threshold` 指定時に `candidate_k` を挿入、`gate_mode` 指定時に `gate_score` を挿入、`reranker` 指定時に `rerank_k` を挿入
  - gate_mode自動推論：`gate_mode` 未指定時に `gate_top1` / `gate_margin` の有無から推論してパラメータ欄に自動挿入
  - gate_mode組み合わせチェック：`gate_mode` 指定時に `gate_top1` / `gate_margin` の過不足を検証しエラーポップアップ
  - 不要パラメータチェック：`condition` が定義されているパラメータが条件不成立なのに指定されている場合はエラーポップアップして処理停止（例：`search_type:mmr` で `rrf_k` が残っている場合）
  - 許容値チェック（`values` あり）・数値型チェック（`values: null`）：エラーは全件まとめてポップアップ
- 「再確認」ボタン：`validateAndComplete()` → `checkIndex()` の順で実行
- Runボタン：`validateAndComplete()` → `checkIndex()` → 確認ダイアログ → フォーム送信

#### projects.js
プロジェクト管理画面専用。`jsConfig` の `data-*` 属性からURL情報を取得。
- `toggleNewForm()`：新規追加フォームの表示/非表示
- `goToProject(event, projectId)`：プロジェクト別list画面へ遷移
- `startEdit(projectId)` / `cancelEdit(projectId)`：行編集モード切り替え
- `saveEdit(projectId)`：Ajax POST で編集内容を保存
- `deleteProject(projectId)`：Ajax POST でプロジェクト削除（確認ダイアログ付き）

## 各画面の仕様

### projects.html / projects.js
- 新規追加欄：「新規追加：」ラベルクリックで表示/非表示切り替え
- 一覧テーブル：行クリックでプロジェクト別list画面へ遷移
- 操作欄：E（編集）/ D（削除）/ 編集中はCn（キャンセル）・Sv（保存）
- 編集モード中のinput/textareaは`onclick="event.stopPropagation()"`で行クリックを無効化
- プロジェクト新規作成時に `pj_{id}/index/` `pj_{id}/logs/` `pj_{id}/raw/` を自動生成し、空の `evaluation_queries.json`（`[]`）を配置

### new.html / new.js
- `jsConfig` に `data-project-id` を追加。`check_index` AjaxのPOSTボディに `project_id` を含める
- 実験タイトル初期値：同プロジェクト内の前回タイトル無し → `ex{MMDD-HHMM}`、前回タイトル有り → `前回タイトル-2`（末尾が`-n`なら`n+1`）
- Parameters欄：`PARAM_ORDER` のグループ順・グループ内スペース区切り・グループ間改行で表示
- Run確認ダイアログ：タイトル＋パラメータ内容を表示。Index無し時は「時間がかかります」追加、Index有り＋再作成ONも同様
- バリデーション・補完（`validateAndComplete()`）：new.js節を参照

### list.html / list.js
- プロジェクト別表示（`project_id` でフィルタ済み）
- ボタン配置順：T-CC / M-CC / P-CC / A-CC / 削除 / 新規実験 / Star / 比較
- `deleteForm` に `project_id` hidden項目を含む（削除後のリダイレクト先に使用）
- Parameters列：`PARAM_ORDER` 順・グループ区切りなし・カンマ区切りで表示（`formatParamsDisplay()`）
- 「選択」ヘッダークリックで全チェックオフ
- 比較ボタン：URLパラメータは常にID小→大順
- Star：★バッジと New/1st/2nd バッジを両立表示
- 各 `<tr>` に `data-icon="{{ e.icon }}"` を付与（`new` / `1st` / `2nd` / 空文字）
- コピーボタン仕様（複数選択時は ` | ` 区切り）：
  - 選択あり：選択行をコピー
  - 選択なし：`data-icon="new"` の行（最新実験）をフォールバックとしてコピー。該当行なしの場合は何もしない
  - T-CC：`ID:[値] タイトル`
  - M-CC：`ID:[値] MRR=[値],Recall@K=[値]`
  - P-CC：`ID:[値] Parameters`
  - A-CC：`ID:[値] タイトル` + 改行 + `MRR=[値],Recall@K=[値]` + 改行 + Parameters

### result.html / result.js
- 「一覧」ボタン：`{% url 'experiment_list' project_id=exp.project_id %}`
- 「新規実験」ボタン：`{% url 'new_experiment' project_id=exp.project_id %}?params={{ exp_params_urlenc }}`
- 評価概要テーブルのParametersをPARAM_ORDER順に表示（JSで書き換え）
- CCボタン（T-CC/M-CC/P-CC/A-CC）をページ右上（「一覧」ボタンの左）に配置。コピー内容はlist画面と同形式
- `評価概要`カード：`Recall@K`（固定表示）
- ボタン構成：`Summary`（初期active）/ `Form1` / `Form2` / `Rewrite1` / `Rewrite2`（`has_rewrite_data=True`の場合のみ表示）
- Form1の各クエリに `MRR: X.XXXX` を表示（旧データは `correct_rank` からフォールバック）
- `switchFmt(fmt)`：`summary` / `1` / `2` / `rewrite1` / `rewrite2` の5種切り替え
- `rewriteView` は `rewrite1` / `rewrite2` どちらかで表示、内部の `rewrite1Content` / `rewrite2Content` を切り替え
- Copyボタン：`rewrite1` / `rewrite2` タブ選択時は `rewriteView.innerText` をコピー
- SPEC欄：`{% include "rag_tr_tool/spec_panel.html" %}`
- LLM回答欄：`{% include "rag_tr_tool/llm_answers_panel.html" %}` （SPEC欄の下）
- `exp_params_json`：`json.dumps` 済みの正規JSON文字列をサーバーから渡す（`data-exp-params` 属性経由）
- run実行後のURLが `/<project_id>/run/` のままである理由：`render()` で実行結果を直接描画しDB再取得を回避。ブラウザ再読み込み時に再POST警告が出る副作用あり

result_view / run_experiment のテンプレート変数：
```python
{
    "exp": Experiment,
    "exp_params_urlenc": str,
    "exp_params_json": str,
    "prev_exp": Experiment | None,
    "has_log": bool,
    "details": list,
    "meta": dict,
    "answers": list,
    "has_answers": bool,
    "rewrite_data": list,
    "has_rewrite_data": bool,
    "rewrite_summary": {"improved": int, "degraded": int, "unchanged": int, "gain": int} | None,
}
```
- `rewrite_data` の各クエリに付与済み（`calc_rewrite_data` で計算）：
  - `results_rewrite[].is_new`：bool（originalにないsource）
  - `original_rank` / `rewrite_rank`：int | None
  - `mrr_delta`：float
  - `rewrite_gain`：bool（mrr_delta > 0）
- 「LLM回答を生成」ボタン：クエリ数確認ダイアログ付き
- 保存済み回答がある場合は自動表示、ボタンは「再生成」
- 429/401エラー時は即時中断、その他エラーはスキップして続行

### rewrite_detail_panel.html（result画面用）
- `result.html` の `rewriteView` div に `{% include %}` で埋め込み
- `mode` キーで `"rewrite"` / `"multi"` を判定し、タイトル・列名・内容を切り替え（`"rewrite"` は else 扱い）
- `rewrite1Content`：サマリーテーブル
  - 列：Query / Original Rank / Rewrite(Merged) Rank / MRR Δ / Rewrite Gain / Rewrite Quality（空欄） / Notes（空欄）
  - MRR Δ > 0 → Gain=Yes（緑）、≤ 0 → No（グレー）
  - Original/Rewrite Rankは `relevant_sources` から計算（旧データは `－` 表示）
- `rewrite2Content`：クエリ単位詳細
  - `rewrite`：original query・rewrite query・MRR差分・検索結果並列
  - `multi`：original query・生成クエリ一覧・gated表示・MRR差分・検索結果（original/merged/per query）
  - `gated=True` のクエリは `→ Gated (top1=X.XXXX, margin=X.XXXX) → No Multi` を表示

### compare.html
- SPEC欄の下に `{% include "rag_tr_tool/rewrite_analysis_panel.html" %}`
- `show_rwa_btn`：両方の実験に `exp_{id}_rewrite.json` が存在する場合のみボタン活性
- `rwa_disabled_reasons`：不活性時の理由リスト
- 「新規実験」「一覧」ボタンのURLは `exp_a.project_id` を使用（`{% url '...' project_id=exp_a.project_id %}`）

### rewrite_analysis_panel.html / rewrite_analysis.js（compare画面用）
- 「Rewrite比較実行」ボタン：Ajax GET `/rag/rwa/` でサマリーデータ取得・表示
- 表示内容：
  - 比較対象ラベル：`比較対象 (ID:query_option)： 79:None → 80:rewrite`
    （None側を左・rewrite/multi側を右に自動並び替え、両方同値の場合はID昇順）
  - 各実験のサマリー行：`{label}: 改善X / 悪化X / 変化なしX / Rewrite Gain:X`
  - 両方データあり時のみ差分行：`差分: 改善±X / 悪化±X / 変化なし±X / Rewrite Gain:±X`
- クエリ単位詳細は **compare画面では表示しない**（result画面のRewriteタブで確認）

## JSコーディングルール（確定）
- フラットスタイル統一：縦位置アラインメント禁止
- `data-*`属性経由でサーバー値をJSに渡す（`|safe`フィルタでdictを展開しない）
- 数値のみ`{{ exp.id }}`で直接展開
- サーバーから dict を JS に渡す際は `json.dumps` 済みの正規JSON文字列を使用（Python dict の `str()` はシングルクォートになり `JSON.parse()` 不可）

## SPECコメント管理ルール
- `# SPEC:` / `# SPEC_xxx:` コメント行は**無断削除・改変禁止**
- RAGアーキテクチャのみ対象（アプリ機能・実装詳細は含まない）
- 数値プレフィックスで並び順制御
- 切り替えパラメータの分岐は対応する `# SPEC_xxx:` で記述（無効側にSPECコメント不要な場合は省略可）
- `_TAG_PARAM_MAP` に新タグを追加した際は `spec_extractor.py` の同マップも更新
- SPECコメントはすべて静的文字列で記述（動的生成不可）

## インデックス管理ルール
- `_INDEX_PARAM_KEYS` のみでハッシュ計算。`search_type` / `bm25_k1` / `bm25_b` はハッシュに含めない
- 全 `search_type` が同一チャンク・Embedding設定なら同じディレクトリを参照し、正確な比較が可能
- `bm25.pkl` は全インデックス構築時に常に生成・保存される
- `_BM25_SEARCH_TYPES` に属する `search_type` でIndex「有無」判定時は `bm25.pkl` の存在も確認する
- 新たにBM25インデックスが必要な `search_type` を追加する際は `_BM25_SEARCH_TYPES` に追記すること
- インデックスはプロジェクト別（`pj_{id}/index/`）に格納。プロジェクト間でインデックスは共有しない
- インデックスは別プロジェクトへフォルダごとコピーして再利用可能（パラメータが同じならハッシュが一致する）

## 旧処理・旧データ互換対応
- `exp_{id}_rewrite.json` の `relevant_sources` は新規実験のみ含まれる（旧データはOriginal/Rewrite Rankが `－` 表示）
- `exp_{id}_rewrite.json` の保存形式は新旧で異なる（新形式：リスト直接保存、旧形式：`{"queries":[...]}` のラッパー付き）。`read_rwa_json()` で透過的に吸収済み
- result画面 Form1：旧データは `mrr` キーなしのため `correct_rank` から `1/rank` で補完（`context_service.py` の `get_result_data()` で処理）
- Step10以前に作成したインデックスには `bm25.pkl` が存在しない。`hybrid`/`bm25` で使用する場合はRebuildが必要
- `query_rewrite` キーを持つ旧実験データはキー名がそのまま残る（`query_option` への互換変換なし）

## 既知の注意点
- `_FakeExp` クラスは `services/context_service.py` 内に存在。同プロジェクト内にDBに実験が1件もない場合の暫定対応
- `compare.html` は `{% extends %}` の後に `{% load static %}` を記述すること（Django テンプレート継承の制約）
- `rewrite_detail.js` は削除済み。Copyボタン処理は `result.js` で実装
- `flatl2` インデックスキャッシュを再利用する場合は `faiss_index_type:flatl2` をパラメータに指定すること
- サーバーから dict を JS に渡す際は必ず `json.dumps` 済みの正規JSON文字列を使うこと（Python dict の `str()` はシングルクォートになり `JSON.parse()` 不可）
- Step10適用後は全既存インデックスのRebuildを推奨（`bm25.pkl` が存在しないため `hybrid`/`bm25` でフォールバックが発生する）
- プロジェクト略称（`short_name`）はフォルダ名には使用しない。フォルダ名は `pj_{id}` で固定（略称変更の影響を受けない）
- `evaluation_queries.json` はプロジェクト別（`pj_{id}/evaluation_queries.json`）。新規プロジェクト作成時に空ファイル（`[]`）を自動生成するため、実験前に実際のクエリを編集すること
- `candidate_k` は `search_type:mmr` との組み合わせでは逆効果になる（MMRの `k=candidate_k` 件選択時に多様性ペナルティが歪む）。`score_threshold` 単独使用を推奨
- result/compare画面はURLに `project_id` を含まないため `context_processors.py` がプロジェクト情報を取得できず、ナビバーのプロジェクト情報が非表示になる。既知の制約として許容済み
- Re-rankerのスコアはCross-Encoderのlogitスコア（負値になり得る）。`score_threshold` の正規化処理はmin-maxのため絶対値スケール差は問題なく、Re-ranker有無で閾値の再調整は不要。ただし同一 `score_threshold` 値でもRe-ranker有無で絞り込み結果が変わる場合がある
- Re-ranker（`reranker:cross`）は `ms-marco-MiniLM-L-6-v2`（約22Mパラメータ）固定。FastAPIのような技術ドキュメントとの相性は限定的な可能性があるが、モデル変更は別課題として保留中
