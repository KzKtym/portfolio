# スキルシート アプリケーション仕様書

## 1. 概要

### 1.1 目的と要件
システム開発案件を獲得する際の職務経歴書（スキルシート）説明しやすくするための機能を提供する。
- 任意のスタック名やドメイン名で検索
- 該当する経歴のタイトル（リンク付き）一覧と実績月数の合計を表示
- 該当する経歴の詳細箇所をハイライト表示

### 1.2 アプリ情報
- アプリ名: Skill Sheet
- アプリID: skill_sheet
- Django app path: app.skill_sheet

---

## 2. ファイル構成

```
project_root/
├── manage.py
├── config/
│   ├── settings.py
│   └── urls.py
├── app/
│   └── skill_sheet/
│       ├── __init__.py
│       ├── admin.py
│       ├── apps.py
│       ├── models.py
│       ├── views.py
│       ├── urls.py
│       └── config.json
├── templates/
│   └── skill_sheet/
│       └── main.html
└── static/
    ├── common.css
    ├── common.js
    └── skill_sheet/
        ├── main.css
        └── main.js
```

---

## 3. URL設計

| URL | 動作 |
|-----|------|
| `/skill_sheet/` | `/skill_sheet/1/` へリダイレクト（デモ用） |
| `/skill_sheet/<id>/` | 指定IDのスキルシート表示 |
| `/skill_sheet/<id>/?search=<keywords>` | キーワード検索付き表示 |

- 存在しないID指定時: Django標準の404エラー（`get_object_or_404`）

---

## 4. モデル仕様

### 4.1 共通仕様
- `created_at`: DateTimeField, auto_now_add=True
- `updated_at`: DateTimeField, auto_now=True, null=True, blank=True

### 4.2 PersonalInfo（パーソナル情報）

| フィールド名 | 型 | 制約 | 説明 |
|-------------|-----|------|------|
| id | AutoField | PK | 自動採番 |
| registration_no | CharField(10) | null可 | 登録No |
| age | IntegerField | 必須 | 年齢 |
| gender | CharField(1) | null可 | 性別（M:男性, F:女性, X:その他） |
| education | CharField(40) | 必須 | 学歴 |
| qualification | CharField(100) | null可 | 資格 |
| availability | CharField(40) | null可 | 稼動 |
| affiliation | CharField(100) | null可 | 所属 |
| nearest_station | CharField(40) | 必須 | 最寄駅 |
| specialty_field | CharField(200) | null可 | 得意分野 |
| specialty_tech | CharField(200) | null可 | 得意技術 |
| specialty_business | CharField(200) | null可 | 得意業務 |
| self_pr | CharField(500) | null可 | 自己PR |

- テーブル名: `skill_sheet_personal`

### 4.3 SkillSheetData（スキルシート詳細）

| フィールド名 | 型 | 制約 | 説明 |
|-------------|-----|------|------|
| id | AutoField | PK | 自動採番 |
| personal | ForeignKey | CASCADE | PersonalInfoへの外部キー |
| project_name | CharField(200) | 必須 | 案件名 |
| content | TextField | 必須 | 内容 |
| remote | BooleanField | default=False | リモートフラグ |
| start_month | CharField(6) | 必須 | 開始年月（YYYYMM形式） |
| end_month | CharField(6) | 必須 | 終了年月（YYYYMM形式） |
| duration | IntegerField | 必須 | 期間（月数） |
| lang | CharField(200) | null可 | 使用言語 |
| db | CharField(200) | null可 | DB |
| os | CharField(200) | null可 | OS |
| tools | CharField(200) | null可 | ツール等 |
| process1〜7 | BooleanField | default=False | 担当工程フラグ |
| person1 | IntegerField | default=0 | チーム人数 |
| person2 | IntegerField | default=0 | 開発人数 |
| person3 | IntegerField | default=0 | 全体人数 |
| scope | CharField(400) | null可 | 担当工程（検索用テキスト） |
| work_style | CharField(20) | null可 | 業務形態 |
| remarks | TextField | null可 | 備考 |

- テーブル名: `skill_sheet_data`
- デフォルトソート: `-start_month`（開始年月降順）

---

## 5. 設定ファイル

### 5.1 config.json
場所: `app/skill_sheet/config.json`

```json
{
    "Process": {
        "1": "■要件定義",
        "2": "■基本設計",
        "3": "■詳細設計",
        "4": "■実装・単体",
        "5": "■結合テスト",
        "6": "■総合テスト",
        "7": "■保守・運用"
    }
}
```

- 読み込みタイミング: Viewで都度ロード（`json.load`）

---

## 6. 画面仕様

### 6.1 画面構成

```
スキルシート
───────────────────────
スキルキーワード:[          ] [検索]
[検索結果表示欄]
───────────────────────
[パーソナル情報欄]
───────────────────────
No. 1 | [案件名]
[スキル情報テーブル]
───────────────────────
No. 2 | [案件名]
[スキル情報テーブル]
・・・
```

### 6.2 データ表示ルール
- null または空白のデータ: 「-」を表示
- 開始年月・終了年月: `YYYY/MM` 形式で表示
- 期間: 12ヶ月以下は「nヶ月」、12ヶ月超は「n年nヶ月」
- 業務形態（work_style）の表示:
  - person1 = 0 の場合: 「※個人ワーク」
  - remote = true の場合: 「※フルリモート」
  - それ以外: 空白
- 人員: 「チーム n名　開発 n名　全体 n名」形式
- 担当工程: process1〜7のtrue項目をconfig.jsonの文字で表示

### 6.3 パーソナル情報欄

| 登録No. | (値) | 所　　属 | (値) |
|---------|------|----------|------|
| 年　　齢 | (値) | 性　　別 | (値) |
| 資　　格 | (値) | 学　　歴 | (値) |
| 稼　　動 | (値) | 最 寄 駅 | (値) |
| 得意分野 | (値 colspan=3) |
| 得意技術 | (値 colspan=3) |
| 得意業務 | (値 colspan=3) |
| 自己PR | (値 colspan=3) |

- 自己PRは改行表示対応（`linebreaksbr`フィルタ）
- 2文字の項目名（年齢、性別）はセンタリング

### 6.4 スキル情報欄

表形式で以下の項目を表示:

| 項目名 | 内容 |
|--------|------|
| 期間 | 開始年月 〜 終了年月（期間） 業務形態 |
| 業務内容 | 内容（改行対応） |
| 人員 | チーム n名　開発 n名　全体 n名 |
| 使用言語 | Lang |
| ＤＢ | DB |
| Server/OS | OS |
| Tool 等 | Tools |
| 担当工程 | process1〜7から生成 |
| 備考 | 値がある場合のみ表示 |

---

## 7. 検索機能

### 7.1 検索仕様
- 入力: スキルキーワード欄に空白区切りで複数キーワード入力可能
- 空白: 半角・全角どちらも対応
- 検索方式: OR検索（いずれかのキーワードを含む）
- 実装方式: バックエンド検索（フォーム送信でページリロード）

### 7.2 検索対象項目
- 案件名（project_name）
- 内容（content）
- Lang（lang）
- DB（db）
- OS（os）
- Tools（tools）
- 備考（remarks）
- 担当工程（scope）
- 業務形態（work_style）

### 7.3 検索結果表示

```
- 検索結果 -
[キーワード1]： 案件数（n件） 実績合計（n年nヶ月）
  - No.n 開始年月-終了年月(期間)： 案件名
  - No.n 開始年月-終了年月(期間)： 案件名...
[キーワード2]： 案件数（n件） 実績合計（n年nヶ月）
  ・・・
```

- No.n: スキル情報欄での表示順
- 案件名: 40文字超は切り捨てて「...」付加
- 案件数: キーワードがヒットする案件の数
- 実績合計: ヒット案件の期間（duration）を合計

### 7.4 ハイライト表示
- ヒットした案件: 背景色を `#ffff00` に変更
- キーワード文字: 検索対象項目内の該当文字を太字表示
- 対象クラス: `.searchable`

### 7.5 ジャンプリンク
- 検索結果の各案件はリンクとして表示
- クリックで該当スキル情報欄へスクロール
- アンカーID: `#skill-{No}`
- リンクスタイル: アンダーラインなし

---

## 8. 共通機能

### 8.1 ページトップへ戻るボタン

#### 仕様
- 表示位置: ウィンドウ右下（fixed）
- 表示条件: スクロール位置が300px超
- 動作: スムーズスクロールでページトップへ移動

#### 実装
- 要素: `<button>` タグ使用（`<a href="#">`は非推奨）
- 監視対象: デフォルトは`window`、`data-scroll-target`属性で変更可能

#### 使用例
```html
<!-- window監視（デフォルト） -->
<button type="button" class="top-btn">
    <div class="pagetop_arrow"></div>
</button>

<!-- 特定要素監視 -->
<button type="button" class="top-btn" data-scroll-target=".message">
    <div class="pagetop_arrow"></div>
</button>
```

---

## 9. データ登録

### 9.1 scopeの設定SQL

```sql
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
```

### 9.2 work_styleの設定SQL

```sql
UPDATE skill_sheet_data
SET work_style = 
    CASE 
        WHEN person1 = 0 THEN '※個人ワーク'
        WHEN remote = true THEN '※フルリモート'
        ELSE ''
    END;
```

---

## 10. 設定追加

### 10.1 config/settings.py

```python
INSTALLED_APPS = [
    # ...
    'app.skill_sheet.apps.SkillSheetConfig',
]

TEMPLATES = [
    {
        'DIRS': [BASE_DIR / 'templates'],
        # ...
    },
]

STATICFILES_DIRS = [BASE_DIR / 'static']
```

### 10.2 config/urls.py

```python
urlpatterns = [
    # ...
    path('skill_sheet/', include('app.skill_sheet.urls')),
]
```

### 10.3 app/skill_sheet/apps.py

```python
class SkillSheetConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app.skill_sheet'
    verbose_name = 'スキルシート'
```

---

## 11. 技術仕様

### 11.1 使用技術
- Backend: Django
- Database: PostgreSQL
- Frontend: HTML, CSS, JavaScript（バニラJS）

### 11.2 JavaScript機能

| ファイル | 機能 |
|----------|------|
| common.js | ページトップボタン制御 |
| main.js | キーワードハイライト、検索フォームのハッシュクリア |

### 11.3 CSSクラス

| クラス名 | 用途 |
|----------|------|
| .searchable | 検索キーワードのハイライト対象要素 |
| .highlighted | 検索ヒット時の背景色変更 |
| .keyword-highlight | キーワードの太字表示 |
| .top-btn | ページトップボタン |
| .item-name-2char | 2文字項目名のセンタリング |

---

## 改訂履歴

| 日付 | 内容 |
|------|------|
| 2025/01/19 | 初版作成 |
