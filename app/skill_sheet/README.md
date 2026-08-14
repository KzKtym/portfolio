# Skill Sheet（スキルシート）

システム開発案件の商談時に、職務経歴書（スキルシート）を**説明しやすくする**ためのツール。

紙やExcelのスキルシートは、「Pythonの経験は何年ですか」「AWSを使った案件はどれですか」と聞かれるたびに
該当箇所を目で探し、月数を暗算することになる。このアプリは、その場でキーワード検索して
**該当案件の一覧・実績月数の合計・本文のハイライト**を同時に出せるようにする。

## 技術検証ポイント

- 商談中のやり取りに耐える応答性を、SPAではなく**素のDjango + バニラJS**で成立させる
- 検索対象を横断する `Q` オブジェクトのOR結合と、ヒット位置のハイライト表示
- 表示ロジック（期間の「n年nヶ月」変換、null→「-」変換）をビュー側に集約し、テンプレートを素直に保つ

## 主な機能

- **キーワード検索**: 空白区切りで複数キーワードを指定可能（半角・全角どちらも可）。OR検索
- **検索結果サマリ**: キーワードごとに「案件数（n件）／実績合計（n年nヶ月）」を集計表示
- **ジャンプリンク**: 検索結果の各案件から、該当するスキル情報欄へスクロール移動
- **ハイライト表示**: ヒットした案件は背景色を変え、本文中のキーワードは太字化
- **全角・半角の吸収**: 入力を NFKC 正規化するため、`Ｐｙｔｈｏｎ` でも `Python` にヒットする
- **パーソナル情報欄**: 登録No・年齢・資格・得意分野・自己PR 等を定型フォーマットで表示
- **ページトップへ戻るボタン**: スクロール300px超で表示（`static/common.js` の共通機能）

## 画面構成

```
スキルシート
───────────────────────
スキルキーワード:[          ] [検索]

- 検索結果 -
[キーワード1]： 案件数（n件） 実績合計（n年nヶ月）
  - No.n 2024/04-2025/03(1年)： 案件名...
[キーワード2]： ...
───────────────────────
[パーソナル情報欄]
───────────────────────
No. 1 | [案件名]      ← ヒット時は背景色を変更
[スキル情報テーブル]
No. 2 | [案件名]
[スキル情報テーブル]
・・・
```

スキル情報テーブルの項目は、期間 / 業務内容 / 人員 / 使用言語 / ＤＢ / Server・OS / Tool等 /
担当工程 / 備考。

## 検索対象

案件名・内容・使用言語・DB・OS・ツール・備考に加え、**担当工程（`scope`）と業務形態（`work_style`）**も
対象に含む。この2つは、`process1〜7` のboolean列や `person1`・`remote` から導出した
**検索用のテキスト列**で、boolean列のままでは「要件定義」「フルリモート」といった
自然な言葉で検索できないために設けている（設定用SQLは仕様書9節）。

## 詳細仕様

データモデル、画面の項目定義、検索・ハイライトの仕様、`config.json` の書式は以下を参照。

📄 [docs/SkillSheet_SPEC.md](../../docs/SkillSheet_SPEC.md)

## ディレクトリ構成

```
app/skill_sheet/
├── models.py       # PersonalInfo / SkillSheetData
├── views.py        # index（ID=1へリダイレクト）/ detail（表示・検索・整形）
├── urls.py         # app_name = 'skill_sheet'
├── admin.py        # 2モデルを素で登録
├── config.json     # 担当工程(process1〜7)の表示名
├── tests.py        # Djangoテスト 54件
└── migrations/

templates/skill_sheet/main.html
static/skill_sheet/    # main.css / main.js（ハイライト処理）
static/                # common.css / common.js（ページトップボタン）
```

## URL

| URL | 動作 |
|---|---|
| `/skill_sheet/` | `/skill_sheet/1/` へリダイレクト（デモ用に固定） |
| `/skill_sheet/<id>/` | 指定IDのスキルシートを表示 |
| `/skill_sheet/<id>/?search=<keywords>` | キーワード検索付きで表示 |

存在しないIDは Django 標準の404（`get_object_or_404`）。**ログインが必要**。

## セットアップ

### 1. マイグレーション

```bash
pipenv run python manage.py migrate skill_sheet
```

### 2. データ登録

Django管理画面（`/admin/`）から `PersonalInfo` と `SkillSheetData` を登録する。

登録後、検索用の派生列を以下のSQLで更新する（`scope` と `work_style` は画面から
自動生成されないため、この手順が必要）。

```sql
-- 担当工程（process1〜7 → 検索用テキスト）
UPDATE skill_sheet_data
SET scope = TRIM(
    CASE WHEN process1 THEN '要件定義 ' ELSE '' END ||
    CASE WHEN process2 THEN '基本設計 ' ELSE '' END ||
    CASE WHEN process3 THEN '詳細設計 ' ELSE '' END ||
    CASE WHEN process4 THEN '実装・単体テスト ' ELSE '' END ||
    CASE WHEN process5 THEN '結合テスト ' ELSE '' END ||
    CASE WHEN process6 THEN '総合テスト ' ELSE '' END ||
    CASE WHEN process7 THEN '保守・運用 ' ELSE '' END
);

-- 業務形態
UPDATE skill_sheet_data
SET work_style =
    CASE
        WHEN person1 = 0 THEN '※個人ワーク'
        WHEN remote = true THEN '※フルリモート'
        ELSE ''
    END;
```

### 3. 表示

```bash
pipenv run python manage.py runserver
```

http://localhost:8000/skill_sheet/ を開く。

## 動作要件

- Django（プロジェクト共通のバージョンに準拠）
- PostgreSQL
- フロントエンドはバニラJS（ビルド不要）

## テスト

```bash
pipenv run python manage.py test app.skill_sheet --settings=config.settings_test
```

54件（うち1件はスキップ。下記「注意事項」参照）。URL解決・モデル・ビュー・検索の4系統で、
主に以下を検証している。

- 期間表示の境界（ちょうど12ヶ月は「12ヶ月」、13ヶ月以上で「n年nヶ月」）
- null・空文字が「-」に変換されること、`person1 = 0` のとき人員欄が空になること
- 全角スペース区切り・NFKC正規化を含む検索キーワードの解析
- 検索結果の No. が「全体での表示順」を指すこと（ヒット内の連番ではない）
- 他人のスキルシートが混入しないこと、404、CASCADE削除

## 注意事項

- **`config.json` が存在しないと 500 になる**。`views.py` は `try/except` なしで
  `open()` しているため、ファイル不在時に `FileNotFoundError` がそのまま送出される
  （`app/home/views.py` はフォールバック実装済み）。これを検証するテストは、本体側の
  フォールバック実装待ちで `@unittest.skip` にしてある。
- `/skill_sheet/` は**ID=1に固定**でリダイレクトする。デモ用の割り切りで、一覧画面は持たない。
- `scope` / `work_style` は登録時に自動更新されない。データ登録・更新のたびに上記SQLの実行が必要。
- 画面はログイン必須です（プロジェクト全体の既定。`LoginRequiredMiddleware`）。
  セル同期APIのみ `api_password` 認証で、セッション認証の対象外です。
