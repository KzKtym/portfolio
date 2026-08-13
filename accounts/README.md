# accounts — 認証・ログイン履歴・商談用アクセス

Django 標準認証をベースに、ログイン試行のロック、ログイン履歴の記録、
商談用のゲストアクセスを担当する。

`AUTH_USER_MODEL` は未設定で、`django.contrib.auth.User` をそのまま使う。
ユーザーにフィールドを足さず、必要な情報は外付けのテーブルに持たせている。

## 構成

```
accounts/
├── models.py       # LoginHistory / LoginLockout / MeetingAccess
├── views.py        # ログイン・サインアップ・商談用アクセス
├── urls.py         # /accounts/ 配下
├── urls_guest.py   # /guest/ 配下（商談相手に渡す短いURL）
├── lockout.py      # 失敗回数のカウントとロック判定
├── middleware.py   # user_logged_in シグナルの受け口・クライアントIP取得
├── admin.py        # LoginHistory は閲覧専用で登録
└── management/commands/prune_login_history.py
```

## ログイン試行のロック

連続失敗でロックする。ID/PWログインと商談用アクセスの両方に適用される。

閾値は運用しながら調整する前提なので、すべて `.env` から変更できる
（既定値は `config/settings.py` 参照）。

| 設定 | 内容 |
| --- | --- |
| `LOGIN_LOCK_THRESHOLD` | 連続何回の失敗でロックするか |
| `LOGIN_LOCK_SECONDS` | 最初のロック秒数。以降の失敗ごとに倍化する |
| `LOGIN_LOCK_MAX_SECONDS` | 倍化の上限秒数 |
| `LOGIN_LOCK_SCOPE` | ロックの単位。`user_ip`（既定）か `user` |

カウンタは成功時のみリセットする。時間窓で自然回復させると総当たりを素通しするため。

`LOGIN_LOCK_SCOPE=user` はユーザー名のみでロックするため分散攻撃に強い反面、
第三者が管理者を締め出せてしまう（自DoS）。既定を `user_ip` にしているのはこのため。

## ログイン履歴

`user.last_login` はログインの度に現在時刻へ更新されるため「前回のログイン」を
表示できない。外付けの `LoginHistory` に1行ずつ積む方式にしている。

保存するのは日時・IPアドレス・User-Agent。IPは画面には出さない。
履歴の保存に失敗しても認証は止めない（例外は握りつぶしてログに残す）。

保持期間を過ぎた履歴の削除はコマンドで行う。自動スケジュールは未設定（cron 運用想定）。

```bash
python manage.py prune_login_history --days 90
python manage.py prune_login_history --days 90 --dry-run
```

## 商談用アクセス（ゲスト）

トークンURL＋パスワードの2要素で、アカウント発行なしに閲覧させる仕組み。
相手に渡すURLなので `/guest/` と短くしてある（実体は accounts のビュー）。

| 設定 | 内容 |
| --- | --- |
| `MEETING_REVOKE_THRESHOLD` | 累計失敗が何回でトークンを失効させるか |
| `MEETING_EXPIRE_DAYS` | 発行時の既定有効日数（絶対期限） |
| `MEETING_IDLE_DAYS` | 最終アクセスからの無操作期限。0 で無効化 |
| `MEETING_TOKEN_LENGTH` | URLに載るトークンの桁数 |
| `MEETING_PASSWORD_LENGTH` | 自動生成パスワードの桁数 |

トークンは既定15桁（約77bit相当）。総当たりはロックと失効で抑える前提で、
URLの短さを優先している。DBにはハッシュ化して保存する。

発行と失効の操作画面は `app/home` のサービス管理メニューにある。

## 動作要件

- `django.contrib.auth` / `django.contrib.sessions` が有効であること
- 権限判定の述語は `app/common/permissions.py` にある

## テスト

```bash
python manage.py test accounts --settings=config.settings_test
```

## 関連ドキュメント

- [docs/Home_AUTH_SPEC.md](../docs/Home_AUTH_SPEC.md) — ログイン方式の横断仕様
