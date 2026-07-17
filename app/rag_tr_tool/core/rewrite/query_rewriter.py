import json
from pathlib import Path

import urllib.request
import urllib.error

from django.conf import settings

_CONFIG_PATH = Path(settings.BASE_DIR) / "app" / "rag_tr_tool" / "config.json"
_API_URL = "https://api.openai.com/v1/chat/completions"
_MODEL = "gpt-4.1-mini"

# SPEC_rewrite: 35/Query Rewrite/LLM/OpenAI API(gpt-4.1-mini)
# SPEC_multi_query: 34/Multi Query/original+2クエリ生成

_PROMPT_REWRITE = Path(__file__).parent / "rewrite_prompt.txt"
_PROMPT_MULTI = Path(__file__).parent / "prompt_multi.txt"


def _get_api_key() -> str:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    key = config.get("openai_api_key", "")
    if not key:
        raise ValueError("openai_api_key が config.json に設定されていません")
    return key


def _load_prompt(path: Path, query: str) -> str:
    """SPECコメント行を除去してプロンプトを返す。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    template = "\n".join(l for l in lines if not l.startswith("# SPEC"))
    return template.format(query=query)


def _call_api(prompt: str, api_key: str, max_tokens: int = 200) -> str:
    payload = json.dumps({
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(
        _API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()


def rewrite_query(query: str) -> str:
    """クエリをLLMで書き直して返す。失敗時は元のクエリを返す。"""
    try:
        api_key = _get_api_key()
        prompt = _load_prompt(_PROMPT_REWRITE, query)
        return _call_api(prompt, api_key)
    except Exception as e:
        print(f"[query_rewriter] rewrite failed, fallback to original. error: {e}")
        return query


def generate_queries(query: str) -> list[str]:
    """Multi Query用に追加クエリを生成して返す。失敗時は空リストを返す。"""
    try:
        api_key = _get_api_key()
        prompt = _load_prompt(_PROMPT_MULTI, query)
        response = _call_api(prompt, api_key, max_tokens=300)
        # レスポンスを行分割して空行・番号プレフィックスを除去
        queries = []
        for line in response.splitlines():
            line = line.strip()
            if not line:
                continue
            # "1. query" / "1) query" / "- query" 形式のプレフィックスを除去
            for prefix in ["1.", "2.", "3.", "1)", "2)", "3)", "-"]:
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
                    break
            if line:
                queries.append(line)
        return queries
    except Exception as e:
        print(f"[query_rewriter] generate_queries failed, fallback to empty. error: {e}")
        return []