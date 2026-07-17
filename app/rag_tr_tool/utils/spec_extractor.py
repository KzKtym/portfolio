"""spec_extractor.py - SPECコメント抽出・SPEC文字列生成"""
import os
import json


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def extract_spec(params: dict = None) -> str:
    config = load_config()
    tree = {}
    chunker = (params or {}).get("chunker", None)
    search_type = (params or {}).get("search_type", None)
    faiss_index_type = (params or {}).get("faiss_index_type", None)
    query_option = (params or {}).get("query_option", None)
    merge_mode = (params or {}).get("merge_mode", None)
    normalize = (params or {}).get("normalize", None)
    gate_score = (params or {}).get("gate_score", None)
    gate_mode = (params or {}).get("gate_mode", None)
    reranker = (params or {}).get("reranker", None)
    # query_optionはNone・"rewrite"・"multi"で渡される
    # None（パラメータなし・無効）はどのタグにもマッチさせない
    if query_option is None:
        query_option = "__disabled__"
    # merge_mode/normalize/gate_modeはmulti時のみ有効
    # タグ名に変換（例: "max" → "multi_query_merge_max"）
    # None（未指定）は番兵値"__disabled__"にしてどのタグにもマッチさせない
    merge_mode = f"multi_query_merge_{merge_mode}" if merge_mode is not None else "__disabled__"
    normalize = f"multi_query_norm_{normalize}" if normalize is not None else "__disabled__"
    gate_score = f"gate_score_{gate_score}" if gate_score is not None else "__disabled__"
    gate_mode = f"multi_query_gate_{gate_mode}" if gate_mode is not None else "__disabled__"
    # rerankerはNone（無効）の場合は番兵値にしてどのタグにもマッチさせない
    reranker = reranker if reranker is not None else "__disabled__"

    for path in config["spec_scan_paths"]:
        full_path = os.path.join(BASE_DIR, path)
        collect_from_path(full_path, tree, chunker, search_type, faiss_index_type, query_option,
                          merge_mode, normalize, gate_score, gate_mode, reranker)

    lines = format_tree(tree)
    return "\n".join(lines)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def collect_from_path(path, tree, chunker=None, search_type=None, faiss_index_type=None, query_option=None,
                      merge_mode=None, normalize=None, gate_score=None, gate_mode=None, reranker=None):
    if os.path.isfile(path):
        scan_file(path, tree, chunker, search_type, faiss_index_type, query_option,
                  merge_mode, normalize, gate_score, gate_mode, reranker)
    else:
        for root, _, files in os.walk(path):
            for file in sorted(files):
                if file.endswith(".py"):
                    scan_file(os.path.join(root, file), tree, chunker, search_type, faiss_index_type, query_option,
                              merge_mode, normalize, gate_score, gate_mode, reranker)


# SPEC_xxx: のタグがどのparamsキーに対応するかの定義
# 新しい切り替えパラメータを追加した際はここに追記する
_TAG_PARAM_MAP = {
    "langchain": "chunker",
    "legacy": "chunker",
    "similarity": "search_type",
    "mmr": "search_type",
    "hybrid": "search_type",
    "bm25": "search_type",
    "flatl2": "faiss_index_type",
    "flatip": "faiss_index_type",
    "rewrite": "query_option",
    "multi_query": "query_option",
    "multi_query_merge_max": "merge_mode",
    "multi_query_merge_weighted": "merge_mode",
    "multi_query_norm_minmax": "normalize",
    "multi_query_norm_none": "normalize",
    "multi_query_gate_standard": "gate_mode",
    "multi_query_gate_top1": "gate_mode",
    "multi_query_gate_margin": "gate_mode",
    "gate_score_raw": "gate_score",
    "gate_score_normalized": "gate_score",
    "cross": "reranker",
}


def scan_file(filepath, tree, chunker=None, search_type=None, faiss_index_type=None, query_option=None,
              merge_mode=None, normalize=None, gate_score=None, gate_mode=None, reranker=None):
    filters = {
        "chunker": chunker,
        "search_type": search_type,
        "faiss_index_type": faiss_index_type,
        "query_option": query_option,
        "merge_mode": merge_mode,
        "normalize": normalize,
        "gate_score": gate_score,
        "gate_mode": gate_mode,
        "reranker": reranker,
    }
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            # # SPEC_xxx: 形式の条件付きSPEC
            if stripped.startswith("# SPEC_"):
                rest = stripped[len("# SPEC_"):]
                tag, _, value = rest.partition(":")
                tag = tag.strip()
                value = value.strip()
                param_key = _TAG_PARAM_MAP.get(tag)
                if param_key is None:
                    # 未知のタグは常に出力
                    insert_tree(tree, value.split("/"))
                else:
                    filter_val = filters.get(param_key)
                    # フィルタ未指定(None)かつ番兵値でない場合は全出力
                    # 番兵値"__disabled__"の場合はどのタグにもマッチさせない
                    if filter_val is None:
                        insert_tree(tree, value.split("/"))
                    elif filter_val != "__disabled__" and tag == filter_val:
                        insert_tree(tree, value.split("/"))
            # # SPEC: 形式の通常SPEC（常に出力）
            elif stripped.startswith("# SPEC:"):
                value = stripped.split(":", 1)[1].strip()
                insert_tree(tree, value.split("/"))


def insert_tree(tree, parts):
    # 先頭セグメントが数値なら並び順として解釈し、ツリーキーからは除外
    if parts and parts[0].isdigit():
        order = int(parts[0])
        parts = parts[1:]
    else:
        order = 0

    # 重複チェック用にorderをメタとして保持
    # tree構造: { key: {"_order": int, "_children": {}} }
    node = tree
    for i, part in enumerate(parts):
        if part not in node:
            node[part] = {"_order": order if i == 0 else 0, "_children": {}}
        node = node[part]["_children"]


def format_tree(tree, indent=0):
    lines = []
    # 同一階層はorderでソート、order同一は検出順（挿入順）を維持
    for key in sorted(tree.keys(), key=lambda k: tree[k]["_order"]):
        lines.append("  " * indent + f"* {key}")
        lines.extend(format_tree(tree[key]["_children"], indent + 1))
    return lines


def resolve_spec(params: dict) -> str:
    """gate_mode自動推論を反映したSPECテキストを返す。
    views.py の _resolve_spec() をこちらに移管。
    EvalParams.from_dict() で gate_mode を解決してから extract_spec() を呼ぶ。
    """
    from app.rag_tr_tool.core.evaluation.params import EvalParams
    p = EvalParams.from_dict(params)
    return extract_spec({**params, "gate_mode": p.gate_mode})