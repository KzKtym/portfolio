# テスト仕様

## unit testコード

| 配置先 | 行数 | 主な内容 |
|---|---|---|
| `config/settings_test.py` | 39 | sqlite3 + テスト用オーバーライド（**新規**） |
| `accounts/tests.py` | 357 | 認証URL、ログイン/ログアウト、SignUp認可、シグナルログ |
| `app/home/tests.py` | 246 | 認証リダイレクト、config.json 3系統、Markdownお知らせ、デコレータ |
| `app/skill_sheet/tests.py` | 539 | モデル、期間3分岐、工程連結、NFKC検索、実績合計3分岐 |
| `app/download/tests.py` | 1,556 | トークン、API、ダウンロード、案内文下書き、管理画面 |

## 実行方法

```bash
# 一括
python manage.py test accounts app.home app.skill_sheet app.download --settings=config.settings_test

# アプリ個別
python manage.py test app.home --settings=config.settings_test
```

**追加の依存パッケージは不要**です（`unittest.mock` / `tempfile` は標準ライブラリ、`markdown` は requirements.txt に既存）。

## `settings_test.py` の注意事項

当初「DATABASES を sqlite3 に上書きする」予定でしたが、**`STATICFILES_STORAGE` の上書きを足しています**。
テストランナーは `DEBUG=False` で動くため、本番設定の whitenoise `CompressedManifestStaticFilesStorage` のままだと、テンプレート35ファイルが使っている `{% static %}` が `staticfiles.json` を要求し、`collectstatic` していない環境では**レンダリングを伴う全テストが落ちます**。素の `StaticFilesStorage` に戻して回避しました。あわせてパスワードハッシャを MD5 に固定しています（高速化のみ、挙動不変）。不要なら該当ブロックを削ってください。
