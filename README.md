# portfolio
生成AIを活用したシステム開発・モダンWebスタックの技術検証用サンプルアプリ集

## 概要

このリポジトリは、個人的なスキルシフトおよび技術検証を目的としたポートフォリオです。  
業務システム開発で培った設計・実装経験をベースに、
- 生成AIを開発支援ツールとして全面的に活用
- 新しい技術スタックを積極的に習得し実践

などに取り組んでいます。

## 技術スタック

* Python
* Django
* FastAPI
* TypeScript
* Vue
* PostgreSQL
* VPS (Ubuntu 24.04)
  - Nginx
  - SSL/TLS (HTTPS化), DNS（サブドメイン運用）
* 会議室予約（デモ版）※ソースは別リポジトリ
  - TypeScript, React + Vite, Fastify
  - SQLite (better-sqlite3), Drizzle ORM
  - npm workspaces, コンテナ配布

## 掲載アプリケーション一覧

| アプリ | 内容・検証技術等 | 詳細 |
| --- | --- | --- |
| Skill Sheet | スキルシート表示、スタック名等で検索しハイライト表示、月数集計 | [README](./app/skill_sheet/README.md) |
| Download App | 安全なファイル送付環境を提供。トークンのライフサイクル管理、パスワード保護 | [README](./app/download/README.md) |
| RAG実験管理ツール | RAG開発の模擬実行、実験本体はCLI → 制御や記録をWeb化 | [README](./app/rag_tr_tool/README.md) |
| Work Shift | 勤務シフトPoC、TypeScript+VueによるGUI、FastAPI+Django構成の使い分け | [README](./app/work_shift/README.md) |
| 会議室予約（デモ版） | 証券会社向けの案件シミュレーション。情報障壁による表示制御、緊急時の優先予約と強制キャンセル、監査証跡。TypeScript+React、Fastify+SQLite構成 | [別リポジトリ](https://github.com/KzKtym/mrr-demo) |

会議室予約（デモ版）のみ、ソースは別リポジトリ
（[KzKtym/mrr-demo](https://github.com/KzKtym/mrr-demo)）で公開しており、本リポジトリには
含まれていません。デモサイトでは同じログインの内側に置き、`/home/` のカードから遷移します。

上記のほか、サイトの入口（未ログイン時のランディング／ログイン後のホーム画面）を
`app/home` が担当しています。アプリ一覧とお知らせは設定ファイルで差し替えられます
（[README](./app/home/README.md)）。

認証・ログイン履歴・商談用アクセスは [accounts](./accounts/README.md)、アプリ横断の
共通部品は [app/common](./app/common/README.md) が担当します。
　

## デモサイト

- URL: https://kt-port.xvps.jp/
- 事前に発行するゲストアカウントで利用可能。***※取引先様のみに配布***
　

## セットアップ

### 必要環境

- Python 3.12 / pipenv
- PostgreSQL
- Node.js（Work Shift のフロントエンドをビルドする場合のみ）

### 手順

```bash
# 1. 依存パッケージ
pipenv install

# 2. 環境変数（SECRET_KEY は必須。未設定だと起動に失敗します）
cp .env.example .env
# .env を編集し、SECRET_KEY と DB 接続情報を設定

# 3. データベース
pipenv run python manage.py migrate
pipenv run python manage.py createsuperuser

# 4. 起動
pipenv run python manage.py runserver
```

http://localhost:8000/ を開きます。ログイン後、`/home/` に各アプリのカードが並びます。

### アプリ個別の追加手順

- **Work Shift**: SPAのビルド成果物はGit管理外のため、`frontend/work_shift` で
  `npm install && npm run build` が必要です。読み取り用のFastAPIプロセスも別途起動します
  （[README](./app/work_shift/README.md)）。
- **Skill Sheet**: データ登録後に検索用の派生列を更新するSQLの実行が必要です
  （[README](./app/skill_sheet/README.md)）。
- **Download App**: `.env` に `DOWNLOAD_API_PASSWORD` の設定が必要です
  （[README](./app/download/README.md)）。
　

## テスト

```bash
pipenv run python manage.py test accounts app.common app.home app.skill_sheet app.download app.work_shift --settings=config.settings_test
```

アプリラベル（`test skill_sheet`）ではなく、ドット付きモジュールパスで指定します。
`app.common` は Django アプリではないため、この形でしか指定できません。

詳細は [tests/README.md](./tests/README.md) を参照してください。
　

## ドキュメント

* 概要：各アプリのREADME（上記一覧）参照
* テスト仕様： [tests/README.md](./tests/README.md)
* 設計資料（[docs/](./docs/)）:

  | 文書 | 対象 |
  | --- | --- |
  | [Home_SPEC.md](./docs/Home_SPEC.md) | サービスTOP・サービス管理画面の仕様 |
  | [Home_AUTH_SPEC.md](./docs/Home_AUTH_SPEC.md) | ログイン方式（失敗ロック、商談用アクセス）の横断仕様 |
  | [SkillSheet_SPEC.md](./docs/SkillSheet_SPEC.md) | Skill Sheet の画面・検索仕様 |
  | [SkillSheet_CELL_SYNC_SPEC.md](./docs/SkillSheet_CELL_SYNC_SPEC.md) | Skill Sheet のセル同期API仕様（スプレッドシート連携） |
  | [Download_SPEC.md](./docs/Download_SPEC.md) | Download App のAPI・権限モデル |
  | [WorkShift_SPEC.md](./docs/WorkShift_SPEC.md) | Work Shift の設計判断の記録（採用しなかった案とその理由を含む） |
  | [rag_tr_tool/](./docs/rag_tr_tool/) | RAG実験管理ツールの仕様・テスト計画・引き継ぎメモ |
　

## ライセンス

[MIT License](./LICENSE)

---
