/* common.js - 複数画面で共有する定数・ユーティリティ */

// パラメータ並び順の定義（パイプライン順、グループ単位）
// new.js / list.js から参照する。このファイルを先に読み込むこと。
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
// condition: fn → 条件付き補完（search_typeに依存するbm25/rrf系）
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