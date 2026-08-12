# 仕様: home アプリ（`/home/`・`/service_admin/`）

初版 2026-08-06。本書は**画面の仕様**を扱う。
ログイン方式（ID/PWのロック、商談用アクセス）は複数アプリにまたがる横断仕様のため、
[Home_AUTH_SPEC.md](Home_AUTH_SPEC.md) に分けている。

## 1. 位置づけ

home アプリはログイン後の入口（サービスTOP）と、その運用画面（サービス管理）を持つ。
業務ロジックは持たず、各サービスへの導線・お知らせ・利用状況の確認に徹する。

| URL | 名前 | 認可 | 概要 |
|---|---|---|---|
| `/` | `index` | 誰でも | 未ログイン時のランディング（`templates/home/index.html`） |
| `/home/` | `home:home` | ログイン必須 | サービスTOP |
| `/service_admin/` | `service_admin:index` | 管理者のみ | サービス管理メニュー |

`/service_admin/` はURLこそ `/home/` 配下ではないが、ビュー・テンプレート・staticは
home アプリに置いている（`app/home/`, `templates/home/`, `static/home/`）。
URL名前空間だけ `app/home/urls_service_admin.py` に分けている。

## 2. ファイル構成

```
app/home/
  views.py                 HomeView / ServiceAdminView / 各POSTエンドポイント
  urls.py                  /home/ 用（app_name='home'）
  urls_service_admin.py    /service_admin/ 用（app_name='service_admin'）
  decorators.py            no_cache_no_index
  config.json              サービス一覧の定義
  tests.py
templates/home/
  index.html  home.html  service_admin.html
static/home/
  base.css  auth.css  home.css  service_admin.css  service_admin.js
media/home/
  system_information.md    お知らせ本文（画面から編集する）
```

## 3. `/home/` サービスTOP

`HomeView`（`LoginRequiredMixin` + `no_cache_no_index`）。

### 3.1 表示要素

| 要素 | 内容 |
|---|---|
| お知らせ | `media/home/system_information.md` をMarkdown変換して表示。空・不在なら「（お知らせ無し）」 |
| アカウント | ユーザー名と種別（管理者／一般ユーザー） |
| 最終ログイン | **今回ではなく前回**のログイン日時。`LoginHistory` の直近2件目を採用し、無ければ「（今回が初めてのログインです）」 |
| サービス一覧 | `app/home/config.json` から生成 |
| アカウント設定 | パスワード変更／（管理者のみ）新規ユーザー作成・管理画面・**サービス管理** |

### 3.2 サービス一覧の定義（config.json）

```json
{
  "name": "スキルシート",
  "status": "on",
  "description": "…",
  "url_name": "skill_sheet:index",
  "button_label": "Skill Sheet"
}
```

- `status: "on"` かつ `url_name` があればカード全体がリンクになる
- `status: "off"` は「準備中」表示（リンクなし）
- ファイル不在・JSON不正の場合は空リストにフォールバックし、ERRORログを出す（画面は落とさない）

## 4. `/service_admin/` サービス管理メニュー

`ServiceAdminView`。`login_required` + `user_passes_test(is_superuser)` + `no_cache_no_index`。
一般ユーザーがアクセスした場合は403ではなくログインURLへリダイレクトする（`/accounts/signup/` と同じ挙動）。

構成は上から次の4ブロック。

### 4.1 ユーザー一覧（参照のみ）

- 表示項目: `id` / `is_superuser` / `username` / `email` / `is_staff` / `is_active`
- 並び: `id` の降順
- 絞り込み: `?users=active`（既定・`is_active=True` のみ）/ `?users=all`
- ユーザーの作成は次の「新規発行」に統合した。商談用アクセスを伴わない作成は
  従来どおり `/accounts/signup/` で行える

### 4.2 お知らせ管理

`media/home/system_information.md` の表示・編集。

| 操作 | 挙動 |
|---|---|
| `Edit` | 画面遷移せず表示モード⇔編集モードを切り替える |
| タブ（編集／プレビュー） | プレビューは `POST /service_admin/notice/preview/` でサーバ側変換。`/home/` と同じレンダラを使うため表示ズレが出ない |
| `Cancel` | 確認ダイアログ（yes/no）の上で編集内容を破棄し、表示モードへ戻る |
| `Save` | `POST /service_admin/notice/save/` でファイルを上書き |

保存時の扱い:
- 改行コードは LF に正規化
- 一時ファイルへ書いてから `os.replace` で置換する（`/home/` 側に書きかけを読ませない）
- 生成HTMLは `mark_safe` で埋め込む。編集できるのは管理者だけという前提に立っている

### 4.3 新規発行（ユーザー作成 + 商談用アクセス発行）

ユーザー一覧と商談用アクセス一覧の間に置く。ユーザー作成と発行を1回の操作で行う。
フォームは既定で折りたたみ。発行結果パネルは折りたたみの外に置くので、
フォームを閉じても表示は残る。

| 項目 | 内容 |
|---|---|
| 商談名・相手先 | 必須 |
| 対象ユーザー | 既定は「＋ 新規作成」。既存ユーザーも選べる |
| 新規ユーザー名 | 「新規作成」時のみ表示。検証は Django標準の `UserCreationForm` に委譲 |
| パスワード再生成 | 既存ユーザー選択時のみ表示（既定ON） |
| 有効日数 | 既定 `MEETING_EXPIRE_DAYS`（30日）。上限も同値 |

パスワードは常に自動生成で、管理者は入力しない。表示の出し分けは
`static/home/service_admin.js` が `data-when` 属性で行う。

**発行結果パネル**: URLとパスワードを表示し、それぞれに `URL: ` / `Pass: ` を付けて
クリップボードへコピーするボタンを備える。「閉じる」を押すまで残る
（`POST /service_admin/issued/dismiss/`）。値はDBに平文で持たないため、
閉じると再表示できない。

### 4.4 商談用アクセス（一覧）

- id / 商談名 / ユーザー / 状態 / 有効期限 / 最終アクセス / 失敗回数（連続・累計）
- **再発行**: 同じ商談名・ユーザーで新しいURLとパスワードを発行し、元を失効させる
- **失効**: 確認ダイアログの上で `POST /service_admin/meeting/<pk>/revoke/`

### 4.5 アクセスログ（参照のみ）

`accounts_loginhistory` の表示。

- 表示項目: `id` / ユーザー / ログイン日時 / **経路** / IPアドレス / ユーザーエージェント
  - 経路は「ID/PW」または「商談: 〈商談名〉」
- 絞り込み

| 値 | 表示 |
|---|---|
| `?logs=last`（既定） | 各ユーザーの最終ログイン1件のみ。全体の新しい順 |
| `?logs=last3byu` | 各ユーザーの新しい順3件。**ユーザー名昇順 → 日時降順**でまとめる |
| `?logs=tail20` | 全体の最新20件 |

- 件数（20件・3件）は `app/home/views.py` の `LOG_TAIL_COUNT` / `LOG_PER_USER_COUNT`
- `last` / `last3byu` は相関サブクエリで実装。PostgreSQL・sqlite3 の両方で動く
- 未知の値は既定値にフォールバックする（`users` も同様）

## 5. エンドポイント一覧

| メソッド | URL | 名前 | 用途 |
|---|---|---|---|
| GET | `/service_admin/` | `service_admin:index` | メニュー本体 |
| POST | `/service_admin/notice/save/` | `notice_save` | お知らせ上書き |
| POST | `/service_admin/notice/preview/` | `notice_preview` | Markdownプレビュー（JSON） |
| POST | `/service_admin/meeting/issue/` | `meeting_issue` | ユーザー作成（任意）+ 商談用アクセス発行 |
| POST | `/service_admin/meeting/<pk>/revoke/` | `meeting_revoke` | 商談用アクセス失効 |
| POST | `/service_admin/meeting/<pk>/reissue/` | `meeting_reissue` | 再発行（元は失効） |
| POST | `/service_admin/issued/dismiss/` | `issued_dismiss` | 発行結果パネルを閉じる |

すべて管理者限定。更新系は `require_POST` で、GETは405を返す。

## 6. テスト

```bash
python manage.py test accounts app.home --settings=config.settings_test
```

`app/home/tests.py` の対象: URL解決、認可（未ログイン／一般／管理者）、キャッシュヘッダー、
ユーザー一覧の絞り込みと並び、お知らせの読み込み・保存・プレビュー・権限、
アクセスログの3フィルタ、商談用アクセスの発行（既存／新規ユーザー）・再発行・失効・一覧、
発行結果パネルの保持と破棄、発行から相手のログインまでの通し。

## 7. 運用上の注意

- 本番は `CompressedManifestStaticFilesStorage` のため、CSS/JS追加時は `collectstatic` が必要
- `media/home/system_information.md` は画面から書き換わる。デプロイで上書きしないこと
- `/service_admin/` と `/home/` は `no-store` + `noindex` を返す
