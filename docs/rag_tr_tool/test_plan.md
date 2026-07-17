# RAG実験ツール テスト仕様（検討中）

## 概要
テストコード生成にあたり、トークン節約のため、当初 CLIでRAG構築を進めていたcore部分は、実行そのものがテストに相当する印象があり、テストコードを省略できないかをまず検証した上で、全体のテスト方針を検討させた。

実行モデル： Claude Opus4.8

---
（以下、Claude 回答）

約2,900行、全58ファイル。まず web 層から読みます。重要な不整合を見つけました。
core と web の境界を確認するため、runner と残りを読みます。core と web を全て読み終えました。
ご想定を検証するため、境界部分を機械的にチェックします。
core は Django 非依存のモジュールがあるので、実際に動かして挙動を確認します。
全ソースを読み、境界部分は静的解析と実行で検証しました。**結論から言うと、「core は実験実行でデバッグできる」は半分正しく、半分は成立しません。** 根拠を示します。

---

## 1. 想定が成立しない最大の理由：core の例外は「実験成功」として記録される

`core/evaluation/runner.py` の `run_evaluation()` は、**処理全体を1つの `try/except Exception` で包んでいます**。

```python
    except Exception as e:
        elapsed = time.time() - start
        return {"status": "error", "error": str(e),
                "meta": {..., "query_count": 0, "total_chunks": 0, ...}}
```

そしてこれを受ける `web/services/run_service.py` は:

```python
result = run_evaluation(normalized_params, rebuild=rebuild, project_id=project_id)
metrics = result.get("metrics", {})          # error時は {} → 全部デフォルト値
current_exp = Experiment.objects.create(
    mrr=metrics.get("mrr", 0.0),             # ← 0.0 で保存される
    recall_at_5=metrics.get("recall_at_5", 0.0),
    ...
)
...
return {..., "message": "実行完了（保存OK）"}  # ← ハードコード。error時も同じ
```

つまり **core のどこで何が落ちても、`mrr=0.0 / recall=0.0` の実験レコードが「実行完了（保存OK）」というメッセージ付きで DB に残ります**。`result["error"]` はどこにも表示されず、破棄されます。

これは「実行すればデバッグできる」という前提を根本から壊します。画面上、**「検索精度が悪くて MRR=0.0」と「例外で落ちて MRR=0.0」が区別できません**。しかも比較画面に並び、SPEC スナップショットまで保存されるため、誤った実験結果として蓄積されます。

## 2. さらに重要な理由：評価ツールのバグは「落ちない」。数字が静かに狂う

`merge_by_score` / `is_gated` / `reciprocal_rank` / `recall_at_k` は、**間違っていても例外を出さず、もっともらしい MRR を返します**。実験を回して `MRR=0.42` が出たとき、それが正しいかどうかは実行では検証できません。比較対象も同じロジックを通るので、A/B 比較しても誤りは相殺されて見えません。

**この計測系ロジックこそ、この実験ツールの成果物そのもの**です。ここが静かに狂うと、実験で得た知見すべてが無効になります。ここは実行では守れません。

---

## 3. 実際に走らせて確認した core の不具合（4件）

`core/chunking/markdown_chunker.py` は Django 非依存なので、実際に実行して確認しました。

```
【1】見出し前の本文が消えるか
  入力: "この前書きは重要な内容です。\n\n# 見出し1\n本文A"
  出力チャンク: ['本文A']
  → 前書きは保持されたか?: False        ← 最初の見出し前の本文が丸ごと消失

【2】overlap が段落パッキングで機能しているか
  chunk数: 3 各長さ: [200, 200, 200]
  → chunk[0]末尾とchunk[1]先頭が重複しているか?: False   ← overlapが効いていない

【3】overlap >= max_chars のとき
  ValueError: range() arg 3 must not be zero          ← クラッシュ

【4】先頭段落が max_chars 以上のとき
  出力: ["''...(len=0)", "'ああ...'(len=500)", ...]
  → 空文字チャンクが含まれるか?: True                   ← 空チャンク混入
```

- **【1】** `extract_sections()` が `match.end()` から始めるため、最初の見出しより前のテキストが構造的に捨てられます。**実験を回しても「なんとなく MRR が低い」としか見えません。**
- **【2】** `recursive_split()` の overlap は、ハードスプリットの fallback 経路でしか使われません。段落パッキング経路では無視されます。→ **`chunker=legacy` での overlap パラメータ実験は、事実上ノーオペを比較しています。**
- **【3】** `max_chars <= overlap` で `ValueError`。runner の包括 except に飲まれて `mrr=0.0` として保存されます（＝第1節の問題と直結）。
- **【4】** 空チャンクは `index_builder` 側の `if c["text"].strip()` で除去されるため露見しませんが、`chunk_index` の採番はズレたままです。

## 4. web ↔ core 境界の型・名前のドリフト（実測で確認）

```
EvalParams フィールド: ['top_k', 'search_type', ..., 'query_option', ...]
query_rewrite は存在するか?: False

llm_service が EvalParams に要求する属性:
  ['boost_threshold', ..., 'query_rewrite', 'search_type', 'top_k']
→ 未定義の属性: ['query_rewrite']
```

| # | 箇所 | 内容 |
|---|---|---|
| **A** | `llm_service.py:41` | `p.query_rewrite` を参照するが `EvalParams` にこの属性は**無い**（`query_option` に改名済み）。→ **`generate_answers` は全実験で必ず `AttributeError`**。`views_api.py` の `except Exception` が拾い、**「インデックスのロードに失敗しました」という無関係なメッセージで 500 を返す**。原因究明が極めて困難。 |
| **B** | `llm_service.py:52` | `results = merge_by_score(...)` と**単一値で受けている**。core 側の戻り値は `(merged, gated, g_top1, g_margin)` の**4要素タプル**（`runner.py:153` は正しく4つで受けている）。→ 直後の `r.get("text")` で `AttributeError: 'list' object has no attribute 'get'`。 |
| **C** | `data_service.py:88` / `views_api.py:85` | `exp.parameters.get("query_rewrite", False)` を読むが、保存されるキーは `query_option`。→ **常に `False`**。RWA ボタンの活性判定と左右の並べ替えが恒久的に死んでいる。 |

**A・B・C はいずれも「実験を回す」経路では踏まれません。** 実験実行（`run_experiment`）は `runner.py` を通り、そちらは正しく書けています。壊れているのは **`generate_answers` / `compare` / `rwa` という、実験実行とは別のボタン**です。つまり **「core は実験で叩ける」は正しいが、その実験経路がカバーしないコードが web 層に確実に存在する**、という構図です。

## 5. 🔴 別件・要即対応バグ検出：
（略）
　対応済み

---

## 6. テスト方針の提案：core を「一枚岩」ではなく3層に分ける

ご想定「core は実験実行そのもの」が当てはまるのは、**外部依存を実際に叩く5モジュールだけ**です。core 20モジュール中の残り約8割は、外部依存ゼロの決定的ロジックで、実験では正しさを検証できません。

### 層C：テスト不要（＝ご想定が正しく当てはまる範囲）

実物を動かす方が費用対効果が高い。モックしても「モックが正しい」ことしか確認できません。

| モジュール | 理由 |
|---|---|
| `embedding/local_embedder.py` | SentenceTransformer 実ロード |
| `embedding/openai_embedder.py` | OpenAI 実通信（※現在どこからも未使用） |
| `vectorstore/faiss_store.py` の `add/save/load` | faiss 実インデックス |
| `retrieval/cross_encoder_reranker.py` の `__init__` | CrossEncoder 実ロード |
| `indexing/index_builder.py` の `build_index()` 本体 | 上記の合成 |

### 層B：**ここが本命**。外部依存ゼロの純ロジック（`SimpleTestCase`）

**実験を回しても正しさが分からず、間違っても落ちない**箇所。テストの価値が最も高い。

| モジュール | テスト対象 | 優先度 |
|---|---|---|
| `evaluation/metrics.py` | `reciprocal_rank` / `recall_at_k`（hit無し、rank=1、k境界、重複source） | **最高** |
| `evaluation/query_logic.py` | `is_gated`（4 gate_mode × 境界値、**結果0件→IndexError**）、`merge_results`（重複source優先、rank振り直し、top_k切り詰め）、`merge_by_score`（minmax正規化、全同値→denom=1.0、weighted 0.8、original_boost、normalized gate） | **最高** |
| `evaluation/params.py` | `normalize`（クォート除去、`"5"`→int、`"0.5"`→float、`5.0`→5、非数値素通し）、`from_dict`（gate_mode 自動推論の4分岐、`skip_no_answer` 文字列判定、`reranker` の falsy→None） | **最高** |
| `chunking/markdown_chunker.py` | 上記【1】〜【4】+ `extract_sections` の階層スタック | 高 |
| `retrieval/retriever.py` | **store/embedder はフェイクを注入すれば faiss 不要**。`_search_similarity`（idx=-1除去）、`_search_hybrid` の**RRF 計算**、`_search_bm25`、`query: ` プレフィクス付与、BM25フォールバック計数 | 高 |
| `retrieval/cross_encoder_reranker.py` | `rerank` のみ（`model.predict` をモック。`__init__` は迂回） | 中 |
| `indexing/index_builder.py` | `get_index_dir` の**ハッシュ安定性**（キー順不同で同一、top_k/search_type を無視、chunk_size 変更で別ハッシュ）、`get_index_info`（tempfile） | 高 |
| `llm/prompt_template.py` | `build_prompt` | 低 |
| `llm/openai_client.py` / `rewrite/query_rewriter.py` | `urllib.request.urlopen` をモック。401/429→`RuntimeError`、その他→`Exception`、`rewrite_query` の失敗時フォールバック、`generate_queries` の**番号プレフィクス除去パース** | 高 |
| `ingest/loader.py` | `strip_frontmatter`、`load_markdown_documents`（tempfile） | 中 |
| `utils/*` 4ファイル | `log_formatter`（書式1/2、mrr フォールバック）、`rewrite_store.calc_rewrite_data`（improved/degraded/gain 集計）、`answers_store`（.bak ローテーション）、`spec_extractor`（`__disabled__` 番兵、`_TAG_PARAM_MAP`、order ソート） | 中〜高 |
| `evaluation/runner.py` | **`build_index` / `Retriever` / `rewrite_query` をモックして分岐だけ検証**。特に **`status="error"` を返す経路** | 高 |

### 層A：web 層（`TestCase`、core はモック）

`views` / `views_api` / `services` / `context_processors`。**第4節の A・B・C はここで検出できます。**

---

## 7. 方針を固めるための確認事項

1. **層Cの線引き**：上表の5モジュールをテスト対象外とする案でよいですか。`vectorstore/faiss_store.py` は faiss さえ入っていれば軽量に往復テストできますが、含めますか。
2. **発見済みバグ4件+3件の扱い**：前回同様「`@unittest.skip` + TODO で現状固定せず明示」でよいですか。特に **A・B（`generate_answers` が全実験で確実に落ちる）は先に本体修正を提案します** — テストを skip で寝かせるより直す方が早い規模です（`p.query_rewrite`→`p.query_option`、戻り値4要素受け）。
3. **`run_evaluation` の包括 try/except と `"実行完了（保存OK）"`**：第1節の問題。テストで「現状（エラーでも mrr=0.0 で保存）」を固定しますか、それとも本体の設計課題として TODO 化しますか。**私見では、これはテストより先に直す価値がある最優先事項**です。
4. **`chunking/splitter.py`**：どこからも import されていないデッドコードに見えます（`split_text_fixed` は `overlap >= chunk_size` で**無限ループ**します）。テスト対象に含めますか、削除候補として扱いますか。
5. **配置**：`web/tests.py` 1ファイルに集約しますか、それとも `core/tests.py`・`utils/tests.py` を新設して3層を分けますか（Django のテストランナーはアプリラベル単位なので、`app.rag_tr_tool.web` 配下に `tests/` パッケージ化するのが現実的です）。
6. **依存**：層Bのテストは faiss / sentence-transformers / langchain の import を避けられますが、`retriever.py` は `numpy` を、`langchain_chunker.py` は `langchain_text_splitters` を import 時に要求します。テスト環境にこれらは入っていますか。

以上