# skill_sheet セル同期 API 仕様

## 概要

ローカルのスプレッド形式アプリ（Excel など）の任意のセルと、Web サーバーの
DB の任意のカラムを、双方向に同期するための仕様。

このAPIの要点は、**サーバーがスプレッドシートの構造を一切知らない**ことにある。
やり取りするのは「名称」と「値」だけで、ブック名・シート名・セルアドレスは
ローカル設定ファイルの中だけに存在する。

その結果:

- ローカル側は Excel でも CSV でも LibreOffice でも Google Sheets でもよい。
  同じ JSON 契約を満たすクライアントを書けば、実装を問わず同期できる
- ローカル設定ファイルが漏れても、DB のテーブル構造は露出しない
- サーバーがテーブル名やカラム名を外部から受け取らないため、
  任意のテーブルを書き換える経路が原理的に存在しない

本リポジトリが対象とするのはサーバー側（Django）のみで、クライアント側の実装は含まない。
本書の JSON 契約を満たせば、クライアントの実装言語・方式は問わない。

---

## 全体構成

```
ローカル（クライアント）                HTTP/JSON            サーバー（Django）

  ┌───────────┐                                        ┌──────────────┐
  │ Spreadsheet│                                        │ CellBinding  │
  │  (Excel等) │                                        │  名称 → 実体  │
  └─────┬─────┘                                        └──────┬───────┘
        │ セル読み書き                                          │ 解決
  ┌─────┴─────┐   {name, direction, value}    ┌─────┐         │
  │   Client   │ ────────────────────────────→ │ API │ ────────┴──→ DB
  │ config.json│ ←──────────────────────────── │     │
  └───────────┘                                 └─────┘

   book / sheet / cell を知っている            name しか知らない
```

---

## 用語

| 用語 | 意味 |
|---|---|
| バインディング | DB 上の「どのモデルの・どのフィールドの・どのレコード」を指す定義。名称が付く |
| 名称（name） | バインディングの識別子。ローカル設定とサーバーを繋ぐ唯一のキー |
| ペア | 「名称」と「ローカル側のセル位置」の対応 |
| push | ローカル → サーバー（DB を更新） |
| pull | サーバー → ローカル（セルを更新） |

---

## サーバー側の準備

### CellBinding の登録

同期対象は、あらかじめサーバー側に登録しておく必要がある。

登録・編集は専用画面 `/skill_sheet/bindings/`（管理者のみ）から行う。
同期先のモデル名とフィールド名をドロップダウンで選べるので、存在しない
指定を作れない。画面の下部にはローカル設定ファイルの雛形が出る
（登録済みの名称が新しい順に並び、`sheet` / `cell` は空欄）。

削除は Django 管理サイト（`/admin/`）から行う。

| フィールド | 必須 | 説明 |
|---|---|---|
| name | ✓ | 名称。`^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$`、全体で一意 |
| label | ✓ | 表示名。日本語可。管理サイトの一覧とエラーメッセージで使う |
| model_label | ✓ | 対象モデル。`skill_sheet.PersonalInfo` 形式 |
| field_name | ✓ | 対象フィールド名 |
| record_id | ✓ | 対象レコードの主キー |
| writable | | push を許可するか。既定 `false`（安全側） |
| description | | 用途メモ |

登録時に次を検証する。いずれかに反する登録は保存できない。

- `model_label` が `skill_sheet` アプリのモデルであること
- `field_name` がそのモデルに実在し、編集可能な具象フィールドであること
- `record_id` のレコードが存在すること

**名称に全角文字は使えない。** 定義名が JSON・URL・ログを通過するたびに
正規化揺れ（NFC / NFKC）の問題を招くため、ASCII に限定している。
日本語の名前は `label` に置く。

---

## API 仕様

### ベースURL

```
https://your-domain.example.com/skill_sheet/
```

### 認証

リクエストボディに `api_password` を含める。サーバー側の値は
`app/skill_sheet/config.json` の `api_password` キーで設定する。

```json
{ "api_password": "env:SKILL_SHEET_API_PASSWORD" }
```

`env:` 接頭辞を付けると、その名前の環境変数を参照する。設定ファイルへの直書きも
できるが、このファイルはリポジトリに含まれるため環境変数を推奨する。
値が未設定（または空）の場合、APIは 500 を返して同期を受け付けない。

参照は python-decouple に任せているため、次のどちらでも通る。

```bash
# 1. シェルで export する
export SKILL_SHEET_API_PASSWORD=xxxxxxxx
```

```
# 2. プロジェクト直下の .env に書く
SKILL_SHEET_API_PASSWORD=xxxxxxxx
```

両方にあれば環境変数が優先される。

認証失敗時:

```json
HTTP/1.1 401 Unauthorized
{"code": 1, "error": "invalid api_password"}
```

### 共通レスポンスコード

| code | HTTPステータス | 意味 |
|---|---|---|
| 0 | 200 | 成功 |
| 1 | 401 / 500 | 認証エラー / サーバーエラー |
| 2 | 400 / 403 | リクエスト不正（未登録の名称、書き込み不可、値が不正） |

---

### 1. セル同期API

**エンドポイント**

```
POST /skill_sheet/api/cells/
Content-Type: application/json
```

**リクエスト**

```json
{
  "api_password": "your_api_password_here",
  "items": [
    { "name": "personal_age",     "direction": "push", "value": 41 },
    { "name": "personal_self_pr", "direction": "pull" }
  ]
}
```

| フィールド | 必須 | 説明 |
|---|---|---|
| items[].name | ✓ | 登録済みバインディングの名称 |
| items[].direction | ✓ | `push` または `pull` |
| items[].value | push時のみ | 反映する値 |

`direction` が `none` のペアはクライアント側で除外され、リクエストには含まれない。

**レスポンス（成功）**

```json
HTTP/1.1 200 OK
{
  "code": 0,
  "results": [
    { "name": "personal_age",     "direction": "push", "status": "ok" },
    { "name": "personal_self_pr", "direction": "pull", "status": "ok",
      "value": "業務系システムの設計・開発を…" }
  ]
}
```

**レスポンス（一部が不正）**

```json
HTTP/1.1 400 Bad Request
{
  "code": 2,
  "error": "1 item(s) rejected",
  "results": [
    { "name": "personal_age", "direction": "push", "status": "error",
      "error": "年齢: 整数で入力してください" },
    { "name": "personal_self_pr", "direction": "pull", "status": "skipped" }
  ]
}
```

**処理順序と原子性**

- `pull` をすべて読み終えてから `push` を書く。
  順序を固定しないと、同一実行内で pull と push が混在したときに結果が
  非決定的になるため
- `push` は全件成功か全件ロールバック（`transaction.atomic`）。
  1件でも失敗すれば DB は一切変更されない
- 値の型変換は Django のモデルフィールドに委ねる。
  `IntegerField` に文字列 `"41"` を送っても解決される。解決できない値は
  検証エラーとして拒否される

---

### 2. バインディング一覧API

ローカル設定ファイルを書くとき、利用可能な名称を確認するためのエンドポイント。

**エンドポイント**

```
POST /skill_sheet/api/bindings/
Content-Type: application/json
```

**リクエスト**

```json
{ "api_password": "your_api_password_here" }
```

**レスポンス**

```json
HTTP/1.1 200 OK
{
  "code": 0,
  "bindings": [
    { "name": "personal_age",     "label": "年齢",   "writable": true,
      "type": "IntegerField", "description": "" },
    { "name": "personal_self_pr", "label": "自己PR", "writable": false,
      "type": "TextField",    "description": "更新は管理画面から" }
  ]
}
```

---

## ローカル設定ファイル仕様

クライアントの必須引数として、このファイルのパスを渡す。形式は JSON、文字コードは UTF-8。

```json
{
  "endpoint": "https://your-domain.example.com/skill_sheet/api/cells/",
  "api_password": "env:SKILL_SHEET_API_PASSWORD",
  "books": [
    {
      "path": "C:/work/skillsheet.xlsm",
      "direction": "push",
      "save_after_pull": false,
      "pairs": [
        { "name": "personal_age",     "sheet": "基本情報", "cell": "C3"  },
        { "name": "personal_self_pr", "sheet": "基本情報", "cell": "B10",
          "direction": "pull" },
        { "name": "proj01_duration",  "sheet": "経歴",     "cell": "F5",
          "direction": "none" }
      ]
    },
    {
      "path": "C:/work/other.xlsx",
      "direction": "pull",
      "pairs": [
        { "name": "personal_availability", "sheet": "Sheet1", "cell": "B2" }
      ]
    }
  ]
}
```

### トップレベル

| キー | 必須 | 説明 |
|---|---|---|
| endpoint | ✓ | セル同期APIのURL |
| api_password | ✓ | API認証パスワード。`env:` 接頭辞で環境変数を参照できる |
| books | ✓ | ブック定義の配列 |
| bindings_endpoint | | バインディング一覧APIのURL。省略時は `endpoint` の末尾 `cells/` を `bindings/` に置き換えて導く |

`api_password` に `env:SKILL_SHEET_API_PASSWORD` と書くと、環境変数
`SKILL_SHEET_API_PASSWORD` の値を使う。設定ファイルへの直書きも可能だが、
リポジトリへの混入事故を避けるため環境変数を推奨する。

### books[]

| キー | 必須 | 既定 | 説明 |
|---|---|---|---|
| path | ✓ | | ブックのパス。設定ファイルからの相対パスで解決する |
| direction | ✓ | | このブック内のペアの既定方向。`push` / `pull` / `none` |
| save_after_pull | | `false` | pull 後にブックを保存するか |
| pairs | ✓ | | ペア定義の配列 |

パス区切りは `/` と `\` の両方を受け付ける。JSON では `\` のエスケープが必要に
なるため、`C:/work/book.xlsx` の形を推奨する。

### books[].pairs[]

| キー | 必須 | 既定 | 説明 |
|---|---|---|---|
| name | ✓ | | サーバーに登録済みのバインディング名称 |
| sheet | ✓ | | シート名 |
| cell | ✓ | | セルアドレス（A1形式） |
| direction | | ブックの値 | 方向をペア単位で上書きする |

上記の例は「このブックは基本 push、`personal_self_pr` だけ pull、
`proj01_duration` は無効」と読む。

同じ名称を複数のセルに割り当てることはできない（設定の読み込み時にエラーになる）。
push の結果が書き込み順に依存してしまうため。`direction` が `none` のペアは
この判定の対象外なので、割り当て先を切り替える途中の状態は書ける。

### direction の意味

| 値 | 動作 |
|---|---|
| `push` | セルの値を読み、DB へ反映する |
| `pull` | DB の値を取得し、セルへ書き戻す |
| `none` | このペアを処理しない。リクエストにも含めない |

`save_after_pull` を `false`（既定）にしておくと、pull の結果はブックのメモリ上に
書かれるだけでファイルは未保存のままになる。利用者が画面で内容を確認してから
保存するか、取り消すかを選べる。

---

## クライアント側について

クライアントの実装は本リポジトリの対象外だが、契約上、次の2点は実装側で守る必要がある。

サーバーとクライアントは別プロセス（多くの場合は別OS）で動くため、
`api_password` は**双方に別々に用意する**必要がある。サーバー側の `.env` を
クライアントが読むことはない。

すべてのペアは1リクエストにまとめて送る。ペアごとに往復はしない。

### 設計上の要点（Excel を対象にする場合）

以下は Excel（Windows）向けのクライアントを実装した際の知見で、
サーバー側の仕様ではない。

Excel との入出力には **COM オートメーション**（xlwings）を使う。
ファイルを直接読み書きする方式ではなく、起動中の Excel プロセス本体を操作する。

これにより:

- **ブックを開いたまま同期できる。** ファイル方式では Excel が排他ロックを
  持つため書き込めない
- 画面上の**未保存の編集内容もそのまま読める**。ファイル方式で読めるのは
  最後に保存された内容だけ
- pull の結果が即座に画面へ反映される
- `.xlsm` のマクロ、書式、条件付き書式が一切壊れない。
  書き込みを行うのは Excel 自身であるため
- 数式セルは、計算結果と数式そのものを明確に区別して扱える

こちらで開いたブックは処理後に閉じるが、**利用者が既に開いていたブックは
閉じずに残す**。

Excel は整数のセルも浮動小数点で返す（`41` → `41.0`）。そのまま送ると
文字列型のカラムに `"41.0"` が入るため、整数値の float は int に戻してから送る。

サーバー側は COM も Excel も一切関知しない。ローカル実装を差し替えても
サーバーの変更は不要である。

---

## 制約・未対応

- **更新衝突の検出は行わない。** ある名称に対し、サーバー側で誰かが値を
  更新した後に push すると、その変更は上書きされる
- 同期の単位はセル1つ。範囲（`A1:C10`）の一括同期には対応しない
- バインディングの登録は Django 管理サイトからのみ。API 経由での登録はできない
- クライアントは本リポジトリに含まない。本書の JSON 契約に沿ったものを別途用意する
