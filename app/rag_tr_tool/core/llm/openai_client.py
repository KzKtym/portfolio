import json
from pathlib import Path

import urllib.request
import urllib.error

from django.conf import settings

_CONFIG_PATH = Path(settings.BASE_DIR) / "app" / "rag_tr_tool" / "config.json"
_API_URL = "https://api.openai.com/v1/chat/completions"
_MODEL = "gpt-4.1-mini"


def _get_api_key() -> str:
    config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    key = config.get("openai_api_key", "")
    if not key:
        raise ValueError("openai_api_key が config.json に設定されていません")
    return key


def generate_answer(prompt: str) -> str:
    """プロンプトをOpenAI APIに送信し、回答文字列を返す。

    Raises:
        RuntimeError: 429/401エラーの場合（呼び出し元で即時中断）
        Exception:    その他のエラー（呼び出し元でスキップ）
    """
    api_key = _get_api_key()

    payload = json.dumps({
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
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

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        if e.code in (401, 429):
            raise RuntimeError(f"OpenAI API error {e.code}: {e.reason}")
        body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"HTTP {e.code}: {body}")
