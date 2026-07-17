def normalize_query_option(value) -> str | None:
    """query_optionパラメータをNone/rewrite/multiに正規化する。"""
    if isinstance(value, str):
        v = value.lower()
        if v == "multi":
            return "multi"
        if v in ("rewrite", "true"):
            return "rewrite"
        return None
    return "rewrite" if value else None


def is_gated(results_original: list, gate_mode, gate_top1: float, gate_margin: float) -> tuple:
    """ゲーティング判定。
    戻り値: (gated: bool, g_top1: float, g_margin: float)
    gated=True → Multi禁止。
    gate_mode: None=ゲーティング無効 / "top1" / "margin" / "standard"
    """
    orig_scores = [r["score"] for r in results_original]
    g_top1 = orig_scores[0]
    g_margin = orig_scores[0] - orig_scores[1] if len(orig_scores) > 1 else orig_scores[0]

    gated = False  # 初期化
    if gate_mode is None:
        pass  # ゲーティング無効→常にMulti適用
    elif gate_mode == "top1":
        gated = g_top1 > gate_top1
    elif gate_mode == "margin":
        gated = g_margin > gate_margin
    elif gate_mode == "standard":
        gated = g_top1 > gate_top1 and g_margin > gate_margin
    else:
        raise AssertionError(f"Unknown gate_mode: {gate_mode!r}")

    return gated, g_top1, g_margin


def merge_results(original: list, rewrite: list, top_k: int) -> list:
    """2系統の検索結果をrankベースでmergeしてtop_k件に絞る。
    重複（同一source）はoriginalのrankを優先。
    """
    seen_sources = set()
    merged = []

    for r in original:
        source = r["metadata"]["source"]
        if source not in seen_sources:
            seen_sources.add(source)
            merged.append(r)

    for r in rewrite:
        source = r["metadata"]["source"]
        if source not in seen_sources:
            seen_sources.add(source)
            merged.append(r)

    merged = merged[:top_k]
    for i, r in enumerate(merged):
        r["rank"] = i + 1

    return merged


def merge_by_score(all_results: list, top_k: int,
                   original_boost: float = 1.0,
                   boost_threshold: float = 0.0,
                   merge_mode: str = "max",
                   normalize: str = "minmax",
                   gate_score: str = "raw",
                   gate_mode=None,
                   gate_top1: float = 1.1,
                   gate_margin: float = 0.0) -> tuple:
    """Multi Query用スコア統合。
    normalize: "minmax"=query単位min-max正規化 / "none"=正規化なし
    merge_mode: "max"=単純max / "weighted"=original×1.0・generated×0.8
    original_boost: boost_threshold超過時にoriginalスコアに乗算
    gate_score: "raw"=生スコアでゲーティング判定 / "normalized"=正規化後スコアで判定
    戻り値: (merged_results, gated, g_top1, g_margin)
      gate_score="normalized"時はゲーティング判定をここで実施。
      gate_score="raw"時はgated=Falseを返し、呼び出し側でis_gated()を使用すること。
    """
    _GENERATED_WEIGHT = 0.8

    # 正規化
    if normalize == "minmax":
        groups = []
        for results in all_results:
            scores = [r["score"] for r in results]
            s_min, s_max = min(scores), max(scores)
            denom = s_max - s_min if s_max != s_min else 1.0
            groups.append([{**r, "score": (r["score"] - s_min) / denom} for r in results])
    else:
        # normalize="none"：生スコアそのまま
        groups = [list(results) for results in all_results]

    # gate_score="normalized"：正規化後スコアでゲーティング判定
    # SPEC_gate_score_normalized: 35/Multi Query/Gate Score/Post-Normalization
    if gate_score == "normalized" and gate_mode is not None:
        norm_scores = [r["score"] for r in groups[0]]
        g_top1_val = norm_scores[0]
        g_margin_val = norm_scores[0] - norm_scores[1] if len(norm_scores) > 1 else norm_scores[0]
        gated = False
        if gate_mode == "top1":
            gated = g_top1_val > gate_top1
        elif gate_mode == "margin":
            gated = g_margin_val > gate_margin
        elif gate_mode == "standard":
            gated = g_top1_val > gate_top1 and g_margin_val > gate_margin
        if gated:
            # ゲーティング成立：統合せずoriginalをそのまま返す
            merged = sorted(all_results[0], key=lambda r: r["score"], reverse=True)[:top_k]
            for i, r in enumerate(merged):
                r["rank"] = i + 1
            return merged, True, round(g_top1_val, 4), round(g_margin_val, 4)
    else:
        g_top1_val, g_margin_val = 0.0, 0.0

    # original boost判定
    original_top1_score = max((r["score"] for r in groups[0]), default=0.0)
    if original_boost != 1.0 and original_top1_score > boost_threshold:
        groups[0] = [{**r, "score": r["score"] * original_boost} for r in groups[0]]

    # sourceごとにmax scoreを採用
    best = {}
    for i, group in enumerate(groups):
        weight = 1.0 if (merge_mode != "weighted" or i == 0) else _GENERATED_WEIGHT
        for r in group:
            source = r["metadata"]["source"]
            weighted_score = r["score"] * weight
            if source not in best or weighted_score > best[source]["score"]:
                best[source] = {**r, "score": weighted_score}

    # スコア降順にsortしてtop_k件に絞り、rankを振り直す
    merged = sorted(best.values(), key=lambda r: r["score"], reverse=True)[:top_k]
    for i, r in enumerate(merged):
        r["rank"] = i + 1

    return merged, False, round(g_top1_val, 4), round(g_margin_val, 4)