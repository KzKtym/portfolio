# Home（ポートフォリオのトップ／ホーム画面）

このポートフォリオサイトの入口となるアプリ。未ログイン時のランディングページと、
ログイン後のホーム画面（アプリ一覧・お知らせ）を提供する。

各アプリへの導線を**設定ファイルで差し替えられる**ようにしてあり、アプリを追加しても
テンプレートを編集せずに一覧へ載せられる。

## 画面構成

| URL | 画面 | 認証 |
|---|---|---|
| `/` | ランディングページ（`templates/home/index.html`） | 不要 |
| `/home/` | ホーム画面（アプリ一覧・お知らせ） | **必要** |

- `/` は`config/urls.py`で`TemplateView`に直結しており、ビューを持たない静的ページ。
- `/home/` は未ログインだと `/accounts/login/` へリダイレクトする（`LoginRequiredMixin`）。
  ログイン後は `LOGIN_REDIRECT_URL = '/home/'` により、この画面へ戻る。

## 設定ファイル

### アプリ一覧: `app/home/config.json`

ホーム画面に並ぶサービスカードは、このJSONの配列がそのまま描画される。
**アプリを追加したら、ここに1件追記するだけで一覧に載る**（テンプレートの修正は不要）。

```json
[
  {
    "name": "スキルシート",
    "status": "on",
    "description": "個人用のスキルシートです。案件種別や開発言語を検索し、ハイライト表示、月数集計などが行えます。",
    "url_name": "skill_sheet:index",
    "button_label": "Skill Sheet"
  }
]
```

| キー | 説明 |
|---|---|
| `name` | カードの見出し |
| `status` | `"on"` = 「利用可能」でリンク有効 / `"off"` = 「準備中」表示でリンク無効 |
| `description` | カード本文の説明 |
| `url_name` | 遷移先のURL名。`{% url %}`で解決するため、**名前空間付き**で書く（例: `skill_sheet:index`、`work_shift:spa`） |
| `button_label` | ボタンの表示文字列 |

- リンクが張られるのは `status` が `"on"` **かつ** `url_name` がある場合のみ。
- `url_name` が解決できない値だとページ全体がエラーになるため、追記時は実在するURL名を指定すること。
- 公開前のアプリは `"status": "off"` にしておけば、「準備中」のカードとして枠だけ表示できる。

### お知らせ: `media/home/system_information.md`

ホーム画面上部のお知らせ欄は、このMarkdownファイルを読んでHTMLに変換して表示する。

- ファイルが**無い場合・中身が空の場合**は「（お知らせ無し）」と表示する（エラーにはしない）。
- 現在このファイルは `xx_system_information.md` にリネームして**無効化**してある。
  お知らせを出すときは `system_information.md` に戻す。
- `media/` 配下なのでGit管理外。運用中にファイルを差し替えるだけで文面を更新できる。

どちらの設定ファイルも、読み込みは**リクエストごと**。編集後にサーバーの再起動は要らない。

## ディレクトリ構成

```
app/home/
├── views.py        # HomeView（config.json と お知らせMD を読んでcontextに載せる）
├── urls.py         # app_name = 'home'
├── decorators.py   # no_cache_no_index（他アプリからも使う共通デコレータ）
├── config.json     # アプリ一覧
└── tests.py        # Djangoテスト 18件

templates/home/
├── index.html      # 未ログイン時のランディングページ
└── home.html       # ログイン後のホーム画面

static/home/        # base.css / home.css / auth.css
media/home/         # system_information.md（お知らせ。Git管理外）
```

## `no_cache_no_index` デコレータ

`app/home/decorators.py` で定義している共通デコレータ。ブラウザキャッシュとクローラーの
インデックスを防ぐため、以下のヘッダーを付与する。

- `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` / `Pragma` / `Expires`（`never_cache`）
- `X-Robots-Tag: noindex, nofollow`

ホーム画面のほか、`work_shift` アプリが全ビューに適用している。
将来 `app/common/` 等へ移動・統合する想定（`decorators.py` にTODOを記載）。

## モデル

**なし**。DBを使わないアプリのため、マイグレーションも空。

## テスト

```bash
pipenv run python manage.py test app.home --settings=config.settings_test
```

18件。主に以下を検証している。

- 未ログイン時に `/home/` がログイン画面へリダイレクトすること
- `no_cache_no_index` が各ヘッダーを正しく付けること
- `config.json` の読み込みと、**ファイル不在・JSON壊れ時に空リストへフォールバック**すること
- お知らせMarkdownのHTML変換と、不在・空のとき「（お知らせ無し）」になること

## 注意事項

- `config.json` が壊れていても画面は落ちないが、**アプリ一覧が空になる**（ログにエラーが出る）。
- `views.py` のコンテキストキーは `system_infomation`（`r` が抜けたスペル）。
  テンプレート側と一致しているため動作に問題はないが、修正する場合は両方を直すこと。
