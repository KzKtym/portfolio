# app/common — アプリ横断の共通層

複数のアプリが必要とするが、どのサービスにも属さない部品を置く。

Django アプリではない（`INSTALLED_APPS` 未登録）。モデルもマイグレーションも持たない
純粋なパッケージとして扱う。

## 置いてある経緯

以前は共通部品の置き場が無く、既存アプリに寄生する形になっていた。

- `no_cache_no_index` … ハブ画面アプリである `app/home` が供給
- `is_superuser` … 認証を担う `accounts` が供給
- `config.json` の読み込み … 各アプリが自前でパスを組み立て、4通りの書き方が並存

依存の向きが実態と合っていなかったため分離した。

## 構成

```
app/common/
├── config.py       # load_app_config / get_app_config_path / resolve_secret
├── decorators.py   # no_cache_no_index
├── permissions.py  # is_superuser
└── tests.py
```

## config.py

### `load_app_config(app_label)`

`<アプリのディレクトリ>/config.json` を読んで dict で返す。

```python
from app.common.config import load_app_config

config = load_app_config('download')
```

パスは Django のアプリレジストリ（`apps.get_app_config(label).path`）から引く。
`app/` 配下という現在のディレクトリ構成に依存しないため、アプリを移動しても壊れない。

ファイルが無い・壊れている場合は例外をそのまま送出する。既定値で握りつぶすと設定漏れに
気付けないため、扱いは呼び出し側の判断に委ねている。実際 `app/home` は空リストに
フォールバックする一方、別のアプリは最低限のデフォルトを返す、と方針が分かれている。

### `resolve_secret(value)`

`'env:NAME'` 形式なら環境変数 `NAME` の値を返す。それ以外はそのまま返す。

```json
// app/download/config.json
{ "api_password": "env:DOWNLOAD_API_PASSWORD" }
```

`config.json` は git 追跡下にあるため、秘密情報を直書きするとリポジトリに残る。
値は `.env` 側に置く。

参照は `os.environ` ではなく `decouple` に任せている。decouple は `os.environ` を先に見てから
`.env` を見るため、`export` でも `.env` でも同じように通る。`os.environ` だけを見ると、
`.env` に書いた値は pipenv 経由で起動したときしか読めず、起動方法によって挙動が変わる。

同じ書式を Excel 連携のローカルクライアント側でも使う（別リポジトリ）。

## 対象外

`app/rag_tr_tool` は独自のパス解決を持つが、アプリ昇格リファクタが控えているため
今回は統合していない。

## テスト

`app/common` は Django アプリではないため、アプリラベルでは指定できない。
ドット付きモジュールパスで指定する。

```bash
python manage.py test app.common --settings=config.settings_test
```

## ここに置くもの・置かないもの

置くのは「特定のサービスに属さないが複数のアプリが必要とするもの」に限る。
業務ロジックは各アプリに置く。1つのアプリしか使わないものも、そのアプリに置く。
