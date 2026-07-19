# テスト仕様

## unit testコード

| 配置先 | 行数 | 主な内容 |
|---|---|---|
| `config/settings_test.py` | 39 | sqlite3 + テスト用オーバーライド（**新規**） |
| `accounts/tests.py` | 357 | 認証URL、ログイン/ログアウト、SignUp認可、シグナルログ |
| `app/home/tests.py` | 246 | 認証リダイレクト、config.json 3系統、Markdownお知らせ、デコレータ |
| `app/skill_sheet/tests.py` | 539 | モデル、期間3分岐、工程連結、NFKC検索、実績合計3分岐 |
| `app/download/tests.py` | 1,556 | トークン、API、ダウンロード、案内文下書き、管理画面 |
| `app/work_shift/tests.py` | 1,272 | 認証境界（全URL走査）、CSRF、入力堅牢性、サービスロジック、SPA配信、FastAPIプロキシ |
| app/rag_tr_tool/tests.py | 作成中 | ※実装の見直し中 → 詳細： [テスト仕様（検討中）](../docs/rag_tr_tool/test_plan.md)参照 |

## 実行方法

```bash
# 一括
python manage.py test accounts app.home app.skill_sheet app.download app.work_shift --settings=config.settings_test

# アプリ個別
python manage.py test app.home --settings=config.settings_test
```

**追加の依存パッケージは不要**です（`unittest.mock` / `tempfile` は標準ライブラリ、`markdown` は requirements.txt に既存）。

## 特記事項

### `config/settings_test.py` の注意事項
- 当初「DATABASES を sqlite3 に上書きする」予定 → **`STATICFILES_STORAGE` の上書き付加**。
- テストランナー（`DEBUG=False` で動く）
  - 本番設定の whitenoise `CompressedManifestStaticFilesStorage` 時
    → テンプレート（内の`{% static %}`）が `staticfiles.json` を要求
      → `collectstatic` していない環境で**レンダリングを伴う全テストが中断**する問題(35ファイル)
    ⇒ 元の `StaticFilesStorage` に戻して回避
- あわせてパスワードハッシャを MD5 に固定（高速化のみ、挙動不変）。不要な場合は該当ブロックを削除する
