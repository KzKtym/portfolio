# Download App 仕様書（統合版）


## 1. システム概要

外部アプリ（Excel等）からAPIでダウンロード用トークンを発行・ファイルを紐付け、
顧客がURL経由でパスワード認証の上ファイルをダウンロードできるようにする社内ツールです。

### 1.1 登場人物

| 役割 | 何をする人か | 使う画面/API |
|---|---|---|
| 担当者（社内・ログインユーザー） | トークン発行、ファイル紐付け確認、ダウンロード案内メールの下書き作成 | 管理画面（`/download/manage/`）、外部アプリ経由のAPI |
| 顧客（社外） | 案内メールのURLからファイルをダウンロード | ダウンロード実行画面（`/download/<token>/`） |

### 1.2 全体の流れ

```
1. 担当者が外部アプリ（Excel等）からトークン発行API実行
   → token, download_url, draft_url を取得

2. 外部アプリ側でzipアーカイブ作成（ファイル名: <token>.zip 推奨）

3. アップロードAPI実行
   → title, upload_type, user_id, file を送信し、1で発行したtokenに紐付け

4. 管理画面（/download/manage/）を開き、対象行の「下書き」ボタンでメール文面を確認・コピー
   ※文書の作成・発番管理がまだローカル側なので、アップロード機能は対象外とする。

5. 「テスト」リンクで動作確認（記録は残らない）

6. 顧客へダウンロードURLをメールで送付

7. 顧客がURLを開きパスワードを入力 → ファイルダウンロード
```

### 1.3 ファイル構成

```
app/download/
├── config.json                              # 設定ファイル
├── models.py                                # DownloadToken / DownloadUser
├── urls.py
├── utils.py                                 # config読み込み・テンプレート置換
├── views.py
└── migrations/
    ├── 0001_initial.py
    ├── 0002_downloaduser_user_name_comment.py
    └── 0003_add_issuer_owner.py             # issuer / owner フィールド追加（権限分離対応）

templates/download/
├── main.html         # ダウンロード実行画面（顧客向け）
├── draft.html         # 下書き表示（担当者向け）
└── manage.html        # 管理画面（担当者向け）

static/download/
├── main.css
└── main.js

data/download/
└── <upload_type>.txt  # 下書きテンプレート（例: sample.txt）

media/download/         # アップロードファイル格納先（自動生成）
```

---

## 2. データモデル

### 2.1 DownloadToken（テーブル名: `download_token`）

| フィールド | 型 | 説明 |
|---|---|---|
| token | CharField(32) | 32桁ランダム英数字、ユニーク |
| **issuer** | **ForeignKey(User, null可)** | **発行した社内ログインユーザー。管理画面から発行時は自動設定、APIからの発行時は`auth_user`指定時のみ設定、それ以外はNULL** |
| issued_at | DateTimeField | 発行日時（自動） |
| upload_deadline | DateTimeField | アップロード期限（発行日時 + m分） |
| download_expire_date | DateField | ダウンロード有効期限（発行日翌日0時 + d日） |
| title | CharField | タイトル（発行直後は `(Up Limit HH:MM:SS)` が自動セット） |
| upload_type | CharField | アップロードタイプ（下書きテンプレートファイル名に対応） |
| target_user | CharField | 指定ユーザーID（フリーテキスト。アップロードAPIの`user_id`/`target_user`で設定） |
| uploaded_file | FileField | アップロードファイル（`./media/download/` 配下） |
| uploaded_at | DateTimeField | アップロード日時 |
| downloaded_at | DateTimeField | **最後に**ダウンロードが成功した日時（後述4.4のとおり上書きのみ、履歴は残らない） |
| download_user | CharField | **最後に**ダウンロードした際のクライアントIPアドレス |
| is_deleted | BooleanField | 論理削除フラグ |

> ⚠️ `target_user`（アップロード時に指定するダウンロード対象の識別子）と `issuer`（発行した社内担当者）は**別概念**です。混同しないよう注意してください。

### 2.2 DownloadUser（テーブル名: `download_user`）

ダウンロード実行画面でのパスワード照合に使う、社外向け認証情報です。

| フィールド | 型 | 説明 |
|---|---|---|
| **owner** | **ForeignKey(User, null可)** | **登録した社内ログインユーザー（管理画面から登録時に自動設定）** |
| user_id | CharField | ユニーク。アップロード時の指定・ダウンロード時のパスワード照合対象の識別に使用 |
| user_name | CharField | メール本文表示用（下書きテンプレートの`[user_name]`に対応） |
| password | CharField | ハッシュ化済みパスワード（必須） |
| comment | CharField | 備考 |

> `issuer` / `owner` は `on_delete=SET_NULL` のため、社内ユーザーアカウントが削除されてもトークン・許可ユーザーのレコード自体は消えず、発行者/所有者情報だけがNULLになります。

---

## 3. アクセス権限モデル（重要・改修ポイント）

もともと全担当者が互いの発行分・登録ユーザーを閲覧できる仕様でしたが、**担当者ごとに自分の分だけが見える**よう改修しています。

### 3.1 基本ルール

| ログインユーザー種別 | 発行リスト（DownloadToken） | 許可ユーザー一覧（DownloadUser） |
|---|---|---|
| スーパーユーザー | 全件閲覧・操作可 | 全件閲覧・操作可 |
| 一般ユーザー | `issuer`が自分自身の分のみ | `owner`が自分自身の分のみ |
| （`issuer`/`owner`が未設定=NULLのレコード） | **スーパーユーザーのみ**閲覧・操作可 | **スーパーユーザーのみ**閲覧・操作可 |

### 3.2 実装箇所と対象機能

| 画面・機能 | 制御内容 |
|---|---|
| `manage_view`（一覧表示） | `tokens`/`users`をログインユーザーで絞り込んで表示 |
| `manage_delete_token` | 本人/スーパーユーザー以外は403 |
| `manage_user_edit` / `manage_user_delete` | 本人/スーパーユーザー以外は403 |
| `draft_view`（下書き表示） | **URLを直接指定した場合も**、本人/スーパーユーザー以外は403 |
| `test_download_view`（テストダウンロード） | **URLを直接指定した場合も**、本人/スーパーユーザー以外は403 |

> 一覧に出てこないだけでなく、トークン文字列を知っていてもURL直打ちでは他人の下書き・テストダウンロードにアクセスできない仕様です。

### 3.3 発行者・所有者が設定されるタイミング

| 経路 | issuer / owner |
|---|---|
| 管理画面から新規発行（`manage_issue_token`） | `issuer = request.user`（自動） |
| 管理画面からユーザー追加（`manage_user_add`） | `owner = request.user`（自動） |
| APIからのトークン発行（`api_issue_token`） | `auth_user`パラメータ指定時のみ、該当ユーザーを設定。省略時はNULL |
| APIからのアップロード（`api_upload`） | 対象外（`DownloadUser`を新規作成する機能ではないため関係なし） |

---

## 4. API仕様（外部アプリ向け）

### 4.1 共通仕様

**ベースURL**
```
https://your-domain.example.com/download/
```

**認証**
各APIリクエストのPOSTパラメータに `api_password` を含めます。値は `app/download/config.json` の `api_password` と一致させます。

認証失敗時のレスポンス:
```json
HTTP/1.1 401 Unauthorized
{"code": 1, "error": "invalid api_password"}
```

### 4.2 設定ファイル（`app/download/config.json`）

| キー | 説明 | 例 |
|---|---|---|
| api_password | API認証パスワード | `"your_api_password_here"` |
| upload_limit_minutes | アップロード期限（分） | `30` |
| download_expire_days | ダウンロード有効期限（日） | `7` |
| list_default_days | 管理画面の標準表示日数 | `30` |

### 4.3 トークン発行API

```
POST /download/api/token/
```

**リクエストパラメータ**

| パラメータ | 必須 | 説明 |
|---|---|---|
| api_password | ✓ | 設定ファイルで指定したAPIパスワード |
| auth_user | | 発行者として記録する社内ログインユーザーの`username`。指定すると管理画面の発行リストで本人（またはスーパーユーザー）のみ閲覧・操作可能になる。省略時は発行者未設定（スーパーユーザーのみ閲覧可） |

**レスポンス（成功）**
```json
HTTP/1.1 201 Created
{
    "code": 0,
    "token": "8xeecgsswfpytlhsoao5bjckpn6kai8t",
    "issued_at": "2026-06-15T10:00:00+09:00",
    "upload_deadline": "2026-06-15T10:30:00+09:00",
    "download_expire_date": "2026-06-23",
    "download_url": "https://your-domain.example.com/download/8xee.../",
    "draft_url": "https://your-domain.example.com/download/manage/draft/8xee.../"
}
```

**備考**
- 発行直後の`title`には`(Up Limit HH:MM:SS)`形式のアップロード期限時刻が自動セットされる
- `title` / `upload_type` / `target_user` はアップロードAPIで後から設定する

**レスポンスコード**

| code | HTTPステータス | 意味 |
|---|---|---|
| 0 | 201 | 発行成功 |
| 1 | 401/500 | 認証エラー / サーバーエラー |
| 4 | 400 | 指定された`auth_user`が存在しない、または無効化（`is_active=False`）されている |

### 4.4 アップロードAPI

```
POST /download/api/upload/
```

**リクエストパラメータ**

| パラメータ | 必須 | 説明 |
|---|---|---|
| api_password | ✓ | 設定ファイルで指定したAPIパスワード |
| token | ✓ | 発行済みトークン（32桁） |
| title | | タイトル |
| upload_type | | アップロードタイプ（下書きテンプレートファイル名に対応） |
| user_id | | 指定ユーザーID（`DownloadUser.user_id`をそのまま`target_user`へ格納） |
| target_user | | `user_id`の別名。どちらか一方を指定 |
| file | | アップロードするファイル。省略時は`<token>.zip`として空ファイルを保存 |

**備考**
- `user_id`（または`target_user`）はそのまま`DownloadToken.target_user`に格納される（`DownloadUser`との紐付けは行われず、フリーテキストとして保持されるのみ）
- 下書き表示時に`target_user`の値で`DownloadUser`を検索し、`user_name`を取得する（未登録時は`target_user`の値をそのまま表示）
- チェック順序：①既にアップロード済み（code=3）→ ②アップロード期限切れ（code=2）→ ③処理実行

**レスポンス（成功）**
```json
HTTP/1.1 200 OK
{
    "code": 0,
    "token": "8xeecgsswfpytlhsoao5bjckpn6kai8t",
    "title": "テスト案件資料",
    "upload_type": "sample",
    "target_user": "customer01",
    "uploaded_at": "2026-06-15T10:05:00+09:00",
    "download_url": "https://your-domain.example.com/download/8xee.../",
    "draft_url": "https://your-domain.example.com/download/manage/draft/8xee.../"
}
```

**レスポンスコード**

| code | HTTPステータス | 意味 |
|---|---|---|
| 0 | 200 | アップロード成功 |
| 1 | 400/401/404/500 | アップロード処理エラー（認証失敗、トークン不正、保存失敗等） |
| 2 | 400 | アップロード期限切れ |
| 3 | 200 | 既にアップロード済み（処理スキップ、情報） |

### 4.5 下書きテンプレート変数

テンプレートファイル（`./data/download/<upload_type>.txt`）内の`[変数名]`が下書き表示時に置換されます。

| 変数 | 内容 |
|---|---|
| `[user_name]` | `target_user`（user_id）で`DownloadUser`を検索した`user_name`。未登録の場合は`target_user`の値をそのまま表示 |
| `[title]` | タイトル |
| `[download_url]` | ダウンロード実行画面のURL |
| `[download_expire_date]` | ダウンロード有効期限（YYYY/MM/DD形式） |

### 4.6 curl呼び出し例

```bash
# トークン発行（発行者未指定）
curl -X POST https://your-domain.example.com/download/api/token/ \
  -F "api_password=your_api_password_here"

# トークン発行（発行者を指定）
curl -X POST https://your-domain.example.com/download/api/token/ \
  -F "api_password=your_api_password_here" \
  -F "auth_user=your_login_username"

# アップロード（ファイルあり）
curl -X POST https://your-domain.example.com/download/api/upload/ \
  -F "api_password=your_api_password_here" \
  -F "token=8xeecgsswfpytlhsoao5bjckpn6kai8t" \
  -F "title=テスト案件資料" \
  -F "upload_type=sample" \
  -F "user_id=customer01" \
  -F "file=@/path/to/8xeecgsswfpytlhsoao5bjckpn6kai8t.zip"

# アップロード（ファイル省略）
curl -X POST https://your-domain.example.com/download/api/upload/ \
  -F "api_password=your_api_password_here" \
  -F "token=8xeecgsswfpytlhsoao5bjckpn6kai8t" \
  -F "title=テスト案件資料" \
  -F "upload_type=sample" \
  -F "user_id=customer01"
```

存在しない、または無効化された`auth_user`を指定した場合:
```json
HTTP/1.1 400 Bad Request
{"code": 4, "error": "auth_user not found or inactive"}
```

---

## 5. 管理画面仕様（社内ログインユーザー向け）

全画面Djangoログイン必須、キャッシュ・クローラー対策ヘッダー付与済み。

### 5.1 URL一覧

| URL | 機能 | アクセス制御 |
|---|---|---|
| `/download/manage/` | 管理画面（発行リスト・ユーザー管理） | ログイン必須、表示内容は3章のとおり絞り込み |
| `/download/manage/issue/` | 新規トークン発行（POST） | ログイン必須 |
| `/download/manage/delete/<token>/` | トークン論理削除（POST） | ログイン必須＋本人/スーパーユーザーのみ |
| `/download/manage/draft/<token>/` | ダウンロード案内の下書き表示 | ログイン必須＋本人/スーパーユーザーのみ |
| `/download/manage/test/<token>/` | テストダウンロード | ログイン必須＋本人/スーパーユーザーのみ |
| `/download/manage/user/add/` | ユーザー追加（POST） | ログイン必須 |
| `/download/manage/user/<id>/edit/` | ユーザー編集（POST） | ログイン必須＋本人/スーパーユーザーのみ |
| `/download/manage/user/<id>/delete/` | ユーザー削除（POST） | ログイン必須＋本人/スーパーユーザーのみ |
| `/download/<token>/` | ダウンロード実行画面（顧客向け） | ログイン不要 |

### 5.2 管理画面（`/download/manage/`）

**ヘッダーボタン**

| ボタン | 動作 |
|---|---|
| `<Home>` | `home:home`URLへ遷移 |
| `標準表示` | 直近n日（`list_default_days`）の削除除くレコードを表示 |
| `全表示` | 全期日の削除除くレコードを表示 |
| `削除含む` | 全レコードを表示（論理削除済み含む） |

> いずれのモードでも、3章のアクセス権限ルールによる絞り込みが**必ず適用**されます（スーパーユーザーのみ全件表示）。

**発行リスト**

見出し表示：`発行リスト（Upload期限：m分 Download期限：d日）`（m・dは`config.json`の値を動的表示）

列構成：

| 列名 | 内容 |
|---|---|
| 発行日時 | トークン発行日時（YYYY/MM/DD HH:MM） |
| トークン | 32桁トークン文字列 |
| 期限 | ダウンロード有効期限日（YYYY/MM/DD） |
| 指定ユーザー | アップロード時に指定した`user_id`（＝`target_user`） |
| タイトル | タイトル（発行直後は`(Up Limit HH:MM:SS)`が入る） |
| タイプ | アップロードタイプ |
| Upload日時 | アップロード完了日時 |
| Download日時 | ダウンロード実行日時（最後の1回のみ、履歴なし） |
| Downloadユーザー | ダウンロード実行時のクライアントIPアドレス（最後の1回のみ） |
| 操作 | 下書き / 削除 |

行の背景色（優先順位：水色 > グレー）：

| 条件 | 背景色 |
|---|---|
| Download日時あり | 水色 |
| アップロード済み かつ ダウンロード有効期限切れ | グレー |
| 未アップロード かつ アップロード期限切れ | グレー |
| 上記以外 | なし（白） |
| 論理削除済み | 半透明（opacity: 0.5） |

操作欄：

| ボタン | 条件 | 動作 |
|---|---|---|
| 下書き | アップロード済みの場合のみ表示 | 下書き表示画面へ遷移 |
| 削除 | 論理削除されていない場合のみ表示 | 論理削除（レコードは残る） |

新規発行ボタン：
- `<新規発行>`押下でトークンのみ発行（発行者は`request.user`が自動設定）、管理画面を再表示
- `title` / `upload_type` / `target_user`はアップロードAPI呼び出し時に設定される

**ダウンロード許可ユーザー管理**（常時表示、トグルなし）

列構成：

| 列名 | 内容 |
|---|---|
| ID | `user_id`（ダウンロード実行時のパスワード照合・アップロード時の指定に使用） |
| ユーザー名 | `user_name`（下書きテンプレートの`[user_name]`に使用） |
| 備考欄 | `comment` |
| 操作 | 編集 / 削除 |

追加フォーム（`<追加>`ボタン押下で展開）：
```
ユーザー追加：
  ID：[ ] ※任意の半角英数（アップロード時に指定）
  名称：[ ] ※メール本文表示用
  パスワード：[ ]
  備考：[ ]
  <保存> <Can>
```
（登録者は`request.user`が自動設定される）

編集フォーム：`編集`ボタン押下で行内に展開（縦並び）。パスワードは変更する場合のみ入力。

削除：物理削除（レコードを完全に削除）。

### 5.3 下書き表示（`/download/manage/draft/<token>/`）

アップロード済みのトークンに対して表示可能（本人/スーパーユーザーのみ、3章参照）。

**表示内容**
- トークン・タイトル・指定ユーザー・アップロードタイプの情報表示
- テンプレートファイル（`./data/download/<upload_type>.txt`）を読み込み、変数を置換したメール文面をテキストエリアに表示

**テストダウンロード欄**
```
テスト：https://your-domain.example.com/download/<token>/
```
クリックするとパスワード入力なし・記録なしでファイルをダウンロード（`downloaded_at`/`download_user`は更新されない）。

**Copyボタン**：テキストエリアの内容をクリップボードにコピー。

---

## 6. ダウンロード実行画面（`/download/<token>/`）

顧客向け画面。ログイン不要。キャッシュ・クローラー対策ヘッダー付与済み。

**表示内容**
```
ダウンロード・サービス
  タイトル：  [値]
  アップロード日時：  [値]
  パスワード：[      ] <ダウンロード実行>
```

**動作**
1. ダウンロード有効期限切れ、または未アップロードの場合：無効メッセージを表示
2. 入力パスワードを`DownloadUser`の**全レコード**と順に照合（`target_user`に紐づく特定ユーザーへの絞り込みは行わない＝登録済みのどのユーザーのパスワードでもダウンロード可能）
3. 一致した場合：ファイルをダウンロードさせ、`downloaded_at`にダウンロード日時・`download_user`にクライアントIPアドレスを記録（**上書き**）
4. 不一致の場合：エラーメッセージを表示

> ⚠️ **ダウンロード回数の制限はありません。** 有効期限内であれば、正しいパスワードで何度でもダウンロード可能です。`downloaded_at`/`download_user`は「最後に成功した1回分」のみが記録され、過去の実行履歴は保持されません。回数制限や全履歴保持が必要な場合は改修が必要です（8章「残課題」参照）。

---

## 7. アクセス制御まとめ（早見表）

| 画面/API | ログイン | 発行者/所有者チェック |
|---|---|---|
| トークン発行API / アップロードAPI | 不要（`api_password`で認証） | なし（`auth_user`はあくまで属性付け） |
| ダウンロード実行画面（顧客向け） | 不要 | なし（パスワード照合のみ） |
| 管理画面一覧表示 | 必須 | 表示内容を絞り込み（3章） |
| トークン削除・下書き・テストダウンロード | 必須 | 本人/スーパーユーザーのみ（URL直打ちも同様） |
| ユーザー編集・削除 | 必須 | 本人/スーパーユーザーのみ |

---

## 8. 今後の検討事項・残課題

### 8.1 API認証方式の変更検討
現状はPOSTパラメータ（`api_password`）での認証のため、HTTPSの利用が必須です。将来的にはHTTP `Authorization`ヘッダー（例: `Bearer`トークン）への変更を検討してください。

```bash
# Authorizationヘッダー方式のイメージ
curl -X POST https://your-domain.example.com/download/api/token/ \
  -H "Authorization: Bearer your_api_password_here"
```

### 8.2 テストダウンロード記録フィールドの追加
現状のテストダウンロード（`/download/manage/test/<token>/`）は記録を行いません。管理画面で「アップロード後にテスト確認済みか」を把握できるよう、`DownloadToken`モデルに`test_downloaded_at`フィールドを追加し、テスト実行日時を記録することを検討してください。

### 8.3 ユーザー管理テーブルとの連携
現状：アップロード時に顧客IDを`target_user`としてフリーテキストで指定。
予定：アップロード時に顧客IDを指定し、顧客名はテーブル`mf_customer`を参照する（請求書システム整備後に実装）。

### 8.4 ダウンロード回数・履歴の扱い
6章のとおり、現状は回数無制限かつ最終1回分のみ記録です。監査要件などにより「1回限りにしたい」「回数上限を設けたい」「全履歴を残したい」といった要望が出た場合は、別途モデル変更（例：ダウンロード履歴テーブルの新設）を伴う改修が必要です。

---

## 9. マイグレーション履歴

| ファイル | 内容 |
|---|---|
| `0001_initial.py` | `DownloadToken` / `DownloadUser` の初期作成 |
| `0002_downloaduser_user_name_comment.py` | `DownloadUser`に`user_name`/`comment`追加、`user_id`のhelp_text変更 |
| `0003_add_issuer_owner.py` | `DownloadToken.issuer` / `DownloadUser.owner`追加（担当者ごとの権限分離対応） |

---

## 10. 引継ぎ時の動作確認チェックリスト

- [ ] 一般ユーザーAでトークン発行・ユーザー登録 → 一般ユーザーBの画面に表示されないことを確認
- [ ] 一般ユーザーAが発行したトークンの`token`値を一般ユーザーBが直接URL指定（下書き/テストダウンロード）→ 403になることを確認
- [ ] スーパーユーザーで全件表示されることを確認
- [ ] APIから`auth_user`未指定でトークン発行 → 発行者未設定（スーパーユーザーのみ閲覧可）になることを確認
- [ ] APIから存在しない`auth_user`を指定 → `code=4`・HTTP 400が返ることを確認
- [ ] 同一トークンに対し複数回ダウンロードが成功すること、`downloaded_at`/`download_user`が最新のもので上書きされることを確認（現行仕様）
