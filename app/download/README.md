# Download App

Djangoベースの自社用ファイル配布（ダウンロード）ツールを想定。
外部アプリ（Excel等）からAPI経由でダウンロード用トークンを入手し、ファイルを紐付けてアップロード。
顧客にはパスワード保護付きのダウンロードURLを配布する仕組みを提供する。

## 技術検証ポイント
- トークンを使った安全性の担保（発行、使用状況管理、利用期限などのライフサイクル設計）
- API設計（特に利用者の制限）

## 主な機能

- トークン発行・ファイルアップロード用API（外部アプリ連携）
- 発行状況の管理画面（一覧・下書きメール文面生成・テストダウンロード）
- ログインユーザー毎に発行リスト／ダウンロード許可ユーザーを管理（アクセス制御）
- 顧客向けパスワード認証付きダウンロード画面
- トークン有効期限（アップロード有効時間、ダウンロード有効期限）の設定
- ファイル保存期限の設定と自動削除　**※追加予定**

## 詳細仕様

API仕様・管理画面仕様・データモデル・アクセス権限モデル等の詳細は以下を参照してください。

📄 [docs/Download_SPEC.md](../../docs/Download_SPEC.md)

## ディレクトリ構成

```
app/download/
├── config.json     # 設定ファイル（API認証パスワード・期限日数等）
├── models.py       # DownloadToken / DownloadUser
├── urls.py
├── utils.py
├── views.py
└── migrations/

templates/download/  # 画面テンプレート
static/download/      # CSS / JS
data/download/        # 下書きメールテンプレート
media/download/        # アップロードファイル格納先（自動生成）
```

## セットアップ

1. `app/download/config.json` に `api_password` 等を設定
2. マイグレーション実行
   ```bash
   python manage.py migrate download
   ```
3. `data/download/` 配下に下書きメールテンプレート（`<upload_type>.txt`）を配置

## 動作要件

- Django（プロジェクト共通のバージョンに準拠）
- ログイン機能（Django標準認証）が有効になっていること

---

詳しい使い方・API仕様は [docs/Download_SPEC.md](../../docs/Download_SPEC.md) を参照してください。
