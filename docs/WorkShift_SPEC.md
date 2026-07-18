# work_shift デモアプリ 仕様書


## 1. 目的とコンセプト

- **目的**: TypeScript + Vue.js、および FastAPI + Django + PostgreSQL 構成の技術検証用デモ版アプリ開発。
- **コンセプト**: 
  - 既存の介護職員シフト作成アプリ（メイン画面、カレンダー/ガントチャート形式のマトリックス画面）の画像を元に、実動作するPocを開発する。
  - 技術スタックは近似アプリの案件情報で必須要件を参考に構成する。

---

## 2. 全体アーキテクチャ

### 2.1 コンポーネント構成

```
[ Vue 3 + TypeScript フロントエンド ]
        │                    │
        │ GET (読み取り)       │ POST/PUT/DELETE (書き込み)
        ▼                    ▼
[ FastAPI (読み取り専任BFF) ]   [ Django (書き込み・マスタ管理) ]
        │                    │
        └──────────┬─────────┘
                    ▼
         [ PostgreSQL (wsft_* テーブル) ]
```

- **FastAPI**: `GET /api/v1/shifts/snapshot` のみを提供する読み取り専任のBFF。
  複数テーブルの結合・繰り返しイベントの展開など、比較的重い集計・整形処理をここに閉じ込め、
  レスポンス速度の向上とロジックの一元化を図る。書き込みは一切行わない。
- **Django**: マスタ管理（グループ／職員）のCRUD、繰り返しイベント定義の登録、シフトの保存など、
  すべての書き込み系処理を担当する。DRFは導入せず、標準の Django（`JsonResponse` + 生JSON parse）
  で実装する。加えて、ビルド済みSPAの配信（`GET /shift/`）と、本番相当経路でのFastAPIへの
  中継（`fastapi_proxy`）も担当する（2.6節）。
- **フロントエンド**: 読み取りはFastAPI、書き込みはDjangoへ、それぞれ直接HTTPリクエストを送る
  （書き込みをFastAPI経由にしない）。フロントの`fetch`は常に相対パスで書き、宛先の振り分けは
  経路側（開発時はVite proxy、本番相当時はDjangoの中継ビュー）が担う（2.4節・2.6節）。

### 2.2 なぜFastAPIとDjangoを両方使うのか

- **FastAPI**: 「読み取り集計・整形専任のBFF」という具体的な役割によって存在意義を持たせる。
  `GET /api/v1/shifts/snapshot` は、複数職員×1ヶ月分のシフト実績と繰り返しイベント展開を
  サーバー側で結合・整形して1回のレスポンスで返す、比較的重くアクセス頻度の高い処理であり、
  これを非同期・軽量なFastAPIに切り出す意味は大きい。
- **Django**: 書き込み系（保存・マスタCRUD）を直接担当する。「読み取りはFastAPI、書き込みは
  Djangoが直接」という役割分担により、FastAPIが単なる素通しのプロキシにならないようにしている。
- **将来の拡張ポイント（今回はスコープ外）**: 保存前の整合性チェック（同一日重複、無効なシフト種別、
  必須イベント日との整合等）をFastAPI側でまとめて実施してからDjangoへ転送する「バリデーション・
  ゲートウェイ」としての役割拡張は、FastAPIの存在意義をさらに強化する将来の拡張候補として認識して
  いるが、現時点では実装しない。

### 2.3 却下した設計理由（記録として）

「フロントをTypeScript+Vueで作る前提があるので、バックエンドとの橋渡しとしてFastAPIを入れておく
べき」という理由付けは、以下の理由で**採用しない**。

- Django側もDRFやdjango-ninja等で、TypeScript+VueへJSONを直接返すAPIは普通に構築できる。
  「バックエンドがPython、フロントがTypeScript」という組み合わせ自体はDjango+Vue構成で広く成立
  しており、それだけでは別途FastAPIを挟む必然性にならない。
- Pydantic⇔TypeScriptの型駆動連携（OpenAPIからのTS型自動生成）は開発体験上のメリットではあるが、
  「なくても困らないが、あると良い」レベルの付加価値であり、採用の主理由にはしない。
- 結論: FastAPIを入れる主目的は「読み取り集計・整形のBFF」という役割そのものであり、
  「証明したいスキルセットの一部として採用した」という説明は本末転倒（先に有効な設計・実装があって
  こそスキル証明になる）として却下した。

### 2.4 通信方式（開発時 / 本番相当時の2経路）

フロントの `fetch` は**常に相対パス**で書き、宛先の振り分けは経路側が担う。これにより、
開発時とビルド配信時でフロントのコードを一切変更しなくてよい。

**(a) 開発時（`npm run dev`, :5173）** — Vite の dev proxy が中継する。

- `/api/*` → FastAPI (`http://127.0.0.1:8090`)
- `/shift/api/*` → Django (`http://127.0.0.1:8000`)

**(b) 本番相当時（`npm run build` → Django の `/shift/` から配信）** — Vite は介在しないため、
代わりに Django 側の中継ビューが同じ役割を果たす（2.6節）。

- `/shift/api/*` → Django 自身（同一オリジンなので中継不要）
- `/api/v1/shifts/snapshot` → `config/urls.py` に登録した `spa_views.fastapi_proxy` が
  `http://127.0.0.1:8090` へ中継する

**CORSについて**: 上記いずれの経路でも、ブラウザから見た通信は同一オリジンに閉じるため
CORS設定は本質的には不要。ただし FastAPI 側には保険として `CORSMiddleware` が設定してあり、
`allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]`、`allow_methods=["GET"]`、
`allow_credentials=True` となっている（`main.py`）。Django 側には django-cors-headers 等は
導入していない。

### 2.5 SPA配信・認証・CSRF（2026-07-07以降の構成）

当初は「Vite dev server から使うデモ」を前提にしていたが、ポートフォリオサイト本体
（`app/home` のサービスカード）から遷移できるようにするため、**Django からビルド済みSPAを
配信し、全体をログイン必須にする**構成を追加した。**これは確定仕様**であり、7節の
「認証・CSRF対策はスコープ外」という旧記述は撤回されている。

- **SPA本体**: `GET /shift/`（`work_shift:spa` → `spa_views.spa_index`）。
  `app/work_shift/static/work_shift/index.html` を読んでそのまま返す（Djangoのテンプレート
  エンジンは通さない）。ビルド成果物が無い場合は **503** とし、本文で
  「`npm run build` を実行してください」と案内する。
  なお `app/work_shift/static/` は `.gitignore` で除外している（ビルド成果物はコミットしない方針）。
- **認証**: `urls.py` の `protected()` ヘルパーで、**全ビューを一律に**
  `login_required` + `no_cache_no_index`（`app.home.decorators`）でラップする。個々のビュー関数側では
  実装しない。未認証時は 302 で `/accounts/login/?next=...` へリダイレクトする（JSONの401ではない）。
- **CSRF**: `@csrf_exempt` は**使用しない**（`views.py` 内に一箇所も無い）。書き込み系は
  すべて `X-CSRFToken` ヘッダーが必須で、欠落時は Django 標準の **403**。
  トークンの発行元は2つ:
  - `spa_index`（`@ensure_csrf_cookie`）— ビルド配信経路ではこれで `csrftoken` クッキーが配られる
  - `GET /shift/api/v1/csrf/`（`work_shift:csrf-token`）— `npm run dev` では `index.html` を Vite が
    配信して `spa_index` を通らないため、フロントが書き込み前にこれを叩いてクッキーを得る
    （`src/lib/api.ts` の `ensureCsrfToken()`）
- **FastAPIへの中継**（`spa_views.fastapi_proxy`）: 転送先は `http://127.0.0.1:8090` 固定で、
  ユーザー入力でホスト部を変えられない。許可パスは
  `_ALLOWED_FASTAPI_PATHS = {"/api/v1/shifts/snapshot"}` の**完全一致1件のみ**（SSRF対策）。
  `config/urls.py` 側でも許可パスを1件ずつ明示登録しており、二重防御になっている。
  - GET以外 → 405（JSON）、ホワイトリスト外 → 403（JSON）
  - タイムアウト 10秒。FastAPI未起動（`URLError`）→ **502**（デモ中に画面全体が落ちないようにするため）
  - upstream の `HTTPError`（404/422等）は status・body をそのまま透過する
  - **リクエストヘッダーは一切転送しない**（Cookie・Authorization等は渡らない）。
    レスポンスは `Content-Type` のみ転送する

### 2.6 認可（デモ範囲）

ログイン済みであれば全データにアクセスできる。ユーザー単位・グループ単位の認可は実装していない
（`views.py` に明記）。デモの公開範囲がごく少数である前提の割り切り。

### 2.7 ファイル構成

```
app/work_shift/
  ├── main.py                          # FastAPI (読み取り専任BFF)
  ├── db.py                            # SQLAlchemy接続層（WSFT_DATABASE_URLで接続先指定）
  ├── schemas.py                       # Pydanticスキーマ
  ├── services.py                      # 繰り返しイベント展開ロジック（履歴フィルタ・週次展開）
  ├── models.py                        # Django ORM モデル（Groupe/Team/Staff/SpotWorker/
  │                                     #   RecruitmentSlot/Member/TeamMembership/EventDefinition/
  │                                     #   Shift/WorkShiftType/ShiftRequirement）
  ├── views.py                         # Django ビュー（書き込み・マスタCRUD）
  ├── spa_views.py                     # SPA配信(spa_index)・CSRFトークン発行・FastAPI中継(fastapi_proxy)
  ├── urls.py                          # Django URLconf（app_name="work_shift"。全ビューをprotected()で包む）
  ├── apps.py                          # Django AppConfig
  ├── tests.py                         # Djangoテスト 109件（8.3節）
  ├── migrations/
  │     ├── 0001_initial.py
  │     ├── ...（0002〜0007。Groupe/Team/Shift再構成・Member体系・order統合等）
  │     ├── 0008_work_shift_type.py           # WorkShiftType新設
  │     ├── 0009_work_shift_type_order.py     # WorkShiftType.order追加
  │     ├── 0010_shift_requirement.py         # ShiftRequirement新設（旧名ShiftTypeRequirementから改名済み）
  │     └── 0011_alter_shiftrequirement_id_alter_workshifttype_id.py
  │                                    #   0008/0010で AutoField だったidを BigAutoField へ補正
  ├── static/work_shift/               # Viteのビルド成果物の出力先（.gitignore対象。npm run buildで生成）
  └── management/commands/
        └── seed_work_shift.py         # デモデータ投入コマンド（8.4節）

frontend/work_shift/
  ├── index.html / vite.config.ts / package.json / tsconfig.json
  └── src/
        ├── main.ts
        ├── App.vue                    # サイドバー＋画面切替（vue-router不使用）
        ├── lib/api.ts                 # CSRF対応fetchラッパ（apiFetch / ensureCsrfToken）
        ├── types/shift.ts             # 型定義一式（スナップショット/保存ペイロード/マスタレコード）
        └── components/
              ├── Sidebar.vue          # 左メニュー（「デモ用管理」配下にスポット・勤務タイプ）
              ├── ShiftTableContainer.vue  # シフト作成画面の親（状態管理・API通信・タブ切替）
              ├── TableHeader.vue      # ステータスバー・年月プルダウン・タブ（シフト表/予定数、両方有効）
              ├── EventRow.vue         # 施設/チームイベント行
              ├── MemberRow.vue        # シフト表タブのメンバー1行分（職員/スポットワーカー/募集枠共通。
              │                        #   旧StaffRow.vue。シフトセルは自作の色分けパネル方式、3.16節）
              ├── TableFooter.vue      # シフト表タブの小計行（現在数/予定数。予定数はShiftRequirement参照）
              ├── RequirementsGrid.vue # 予定数タブの編集グリッド（勤務タイプ×日付の必要人数を直接入力）
              ├── AddMemberModal.vue   # 「メンバーを追加＋」サブ画面（職員/スポット指名/スポット募集の3タブ。
              │                        #   職員・スポット指名タブはチェックボックス複数選択＋一括登録）
              ├── GroupeCrud.vue       # グループCRUD画面
              ├── StaffCrud.vue        # 職員CRUD画面
              ├── SpotWorkerCrud.vue   # スポットワーカーCRUD画面（サイドメニュー「デモ用管理」→「スポット」）
              └── WorkShiftTypeCrud.vue # 勤務タイプCRUD画面（サイドメニュー「デモ用管理」→「勤務タイプ」）
```

補足: プロジェクト側（`app/work_shift/` の外）で必要な変更は以下の4点。**いずれも本リポジトリに
反映済み**（旧版では「本リポジトリには含まれない」としていたが、ポートフォリオ本体へ統合した
ため現在は含まれる）。

| ファイル | 変更内容 |
|---|---|
| `config/settings.py` | `INSTALLED_APPS` に `"app.work_shift.apps.WorkShiftConfig"` を追加 |
| `config/urls.py` | `path('shift/', include('app.work_shift.urls'))` を追加（**`shift/api/v1/`ではない**。3.1節） |
| `config/urls.py` | `path('api/v1/shifts/snapshot', ...fastapi_proxy..., name='work_shift_fastapi_proxy')` を追加（2.5節） |
| `app/home/config.json` | サービスカードを1件追加（`url_name: "work_shift:spa"`） |

依存パッケージ（`fastapi` / `sqlalchemy` / `uvicorn`）は Pipfile に追加済み（8.5節）。

---

## 3. データベース設計

### 3.1 命名規則

- 全テーブル名は `wsft_` プレフィックスを付与する（例: `wsft_teams`）。
- Djangoアプリは `app.work_shift`（`AppConfig.name = "app.work_shift"`, `label = "work_shift"`,
  `verbose_name = "シフト管理"`）。
- **Django側のURLマウント（2026-07-07に変更）**: `config/urls.py` では
  `path("shift/", include("app.work_shift.urls"))` とし、`api/v1/` プレフィックスは
  `app/work_shift/urls.py` 側の各パスに付ける。
  - 変更理由: SPA本体（`/shift/`）も同じ `work_shift` 名前空間に含めたかったため。これにより
    `app/home/config.json` の `url_name: "work_shift:spa"` が解決できる。
  - したがって全エンドポイントの実効パスは `/shift/api/v1/...` で、旧版の記述と最終的な
    URLは同じだが、**プレフィックスを付ける場所が違う**点に注意。
- FastAPI側のルート: `/api/v1/` プレフィックス（マウント方法はDjangoと独立、ポートも別）。

### 3.2 テーブル定義

#### `wsft_groupe`（Groupeモデル）

施設グループ（例:「介護老人保健施設 さくら」）。

| カラム | 型 | 備考 |
|---|---|---|
| id | BigAutoField | PK |
| name | CharField(100) | |

#### `wsft_teams`（Teamモデル）

チーム。**組織上の所属ではなく、「フロア1F」のような場所ラベル**として扱う。
シフト作成画面は「チーム＋年月」で一意なシートとして表示される（3.5節）。

| カラム | 型 | 備考 |
|---|---|---|
| id | BigAutoField | PK |
| name | CharField(100) | |
| group_id | FK → wsft_groupe | `on_delete=PROTECT`（Groupeを消すには先にTeamを削除する必要がある） |

#### `wsft_staffs`（Staffモデル）

職員。**スポットワーカー等も含まれ、必ずしも1つのチームに固定所属しない**という前提を持つ。

| カラム | 型 | 備考 |
|---|---|---|
| id | BigAutoField | PK |
| name | CharField(100) | |
| default_team | IntegerField(null可) | **FK制約なし・存在チェックなし**。テストデータ作成時に「シフト表に人員を割り当てる際、優先的に紐づける」参考値としてのみ使う。正職員／臨時職員の区別は将来の課題としてデモ版では省略。 |

#### `wsft_event_definitions`（EventDefinitionモデル）

繰り返しイベント定義（**履歴管理版**）。詳細な運用ルールは3.4節を参照。

| カラム | 型 | 備考 |
|---|---|---|
| id | BigAutoField | PK |
| target_type | CharField(10) choices | `facility`（施設） / `team`（チーム）。チーム対象イベントは今回未実装（3.6節） |
| target_id | IntegerField(null可) | target_type="team"の場合のみTeam.idを設定。facilityの場合はNULL |
| title | CharField(100) | |
| recurrence_type | CharField(10) choices | `weekly`（毎週）/ `monthly`（毎月、今回未実装） |
| recurrence_days | JSONField(list) | 例: `["MON","THU"]` |
| effective_from | CharField(7) | "YYYY-MM"。このルールの適用開始年月 |
| effective_until | CharField(7, null可) | "YYYY-MM"。NULLは無期限。半開区間 `[from, until)` |
| created_at / updated_at | DateTimeField | |

インデックス: `(target_type, effective_from)`

#### `wsft_shifts`（Shiftモデル）

個別シフト実績。

| カラム | 型 | 備考 |
|---|---|---|
| id | BigAutoField | PK |
| staff_id | FK → wsft_staffs | `on_delete=CASCADE` |
| date | DateField | |
| shift_type | CharField(20) | 例: '日1','早1','遅1','夜勤','休' |
| team | IntegerField | **FK制約なし**。このシフトが「どのチーム（場所）のシートで記録されたか」を示す履歴的な値（3.5節） |
| deleted_at | DateTimeField(null可) | 「メンバーを削除(×)」による論理削除フラグ。NULL=有効。値は保持したまま除外表示する |
| updated_at | DateTimeField | |

制約: `unique_together = (staff, date)`（職員1人につき1日1レコード）

**※この表は初期版の姿。3.9節で`staff` FK→`member` FKへ、3.10節で`order`列追加へと変更済み。
最終形は3.9節末尾・3.10節を参照。**

#### `wsft_team_staff_order`（TeamStaffOrderモデル）※**テーブルごと削除済み**

チーム内での職員の並び順（＝ドラッグによる並び替え）を管理する目的で当初導入したテーブル。
以下の経緯で、**現在のDBにこのテーブルは存在しない**（設計判断の記録としてのみ残す）。

1. マイグレーション0004で `wsft_team_staff_order` として新設
2. 0005でメンバー体系の再設計（3.9節）に伴い `TeamMemberOrder`（`wsft_team_member_order`）へ改名
3. **0007で `DeleteModel` により物理削除**。並び順は `TeamMembership.order`（当月・将来月）／
   `Shift.order`（過去月の凍結値）へ統合された（3.10節）

旧定義: `id` / `team_id`(FK, CASCADE) / `staff_id`(FK, CASCADE) / `order`(IntegerField)、
`unique_together = (team, staff)`。

#### `wsft_work_shift_types`（WorkShiftTypeモデル）※2026-07-07追加

勤務タイプマスタ（グループ単位。日1・早1・遅1・夜勤・休等）。サイドメニュー
「デモ用管理」→「勤務タイプ」で管理する（3.13節）。

| カラム | 型 | 備考 |
|---|---|---|
| id | BigAutoField | PK |
| group_id | FK → wsft_groupe | `on_delete=CASCADE` |
| name | CharField(20) | 例: "日1"。同一グループ内での重複はAPI側でチェック（DB制約はなし） |
| start_time | TimeField(null可) | 「休」等、実働時間を持たない種別はNULL |
| is_overnight | BooleanField | 「翌」チェック。Trueなら`end_time`は翌日の時刻として扱う |
| end_time | TimeField(null可) | 同上 |
| break_minutes | IntegerField(null可) | 休憩時間（分）。「休」等はNULL |
| color | CharField(7) | 表示色（例: "#7cb342"）。CRUD画面では固定10色スウォッチから選択 |
| order | IntegerField | 並び順。一覧・シフトセルの選択パネル・小計行の並びに使う（`ORDER BY order, id`） |

デフォルト順序（`ordering`）: `["order", "id"]`

#### `wsft_shift_requirements`（ShiftRequirementモデル）※2026-07-07追加

予定数（勤務タイプ×日付ごとの必要人数）。旧称`ShiftTypeRequirement`から改名済み
（「予定数においてTypeは本質ではない」という判断による）。詳細は3.14節。

| カラム | 型 | 備考 |
|---|---|---|
| id | BigAutoField | PK |
| team_id | FK → wsft_teams | `on_delete=CASCADE` |
| date | DateField | |
| work_shift_type_id | FK → wsft_work_shift_types | `on_delete=CASCADE` |
| required_count | IntegerField | 必要人数。未保存の(team, date, work_shift_type)は0扱い |

制約: `unique_together = (team, date, work_shift_type)`

### 3.3 モデル間の関係性の要点（誤解しやすいポイント）

- `Team.group`（FK, PROTECT）と `Shift.team`（IntegerField, FKなし）は**設計思想が異なる**。
  前者は純粋なマスタ参照、後者は「記録当時のコンテキストを固定するための、あえてFKにしない履歴値」。
- `Staff.default_team` も同様に**FKにしない**。理由は「職員はチームに拘束される組織メンバーではない」
  という業務前提のため。存在しないTeam.idが入っていてもアプリは特に検証しない
  （表示時に「不明なチームID」として出す程度の緩い扱いで十分という合意）。

### 3.4 繰り返しイベント定義の履歴管理方式

「翌月以降のみ反映・実績データに影響を与えない」という制約を満たすため、以下の運用とする。

- **編集**: 既存行をUPDATEしない。
  1. 既存行の `effective_until` に「変更を適用する年月」をセットして世代を閉じる
  2. 新しい内容の行を `effective_from = 変更を適用する年月` で新規作成する
- **削除**: 物理削除ではなく、`effective_until` に「削除を反映する年月」をセットする論理削除。
- **有効判定**: 対象年月 `ym` に対して `effective_from <= ym AND (effective_until IS NULL OR ym < effective_until)`。
- **実績データへの非影響**: `wsft_shifts` は `wsft_event_definitions` と完全に別テーブル・別FKツリー
  であり、イベント定義側の変更（新世代追加・論理削除）の影響を構造上まったく受けない。この構造自体が
  「実績データに影響を与えない」という制約を満たしている、という理解で確定している。

### 3.5 「チーム＋年月」の一意性とシートの単位

- シフト作成画面（1つの表）は、業務上「チーム＋年月」で一意なシートである
  （DB設計的にはグループはTeam経由で辿れるため、実質的な一意キーは「チーム＋年月」）。
- 保存API呼び出し1回は、必ず「1チーム・1月分の変更」を送る、という業務制約に対応するため、
  保存APIのペイロードは `team_id` をリクエスト直下に1つだけ持つ形にしている（4.3節）。
- **現状のフロント実装は、デモとして単一チーム固定（`TEAM_ID = 1`）で1シートのみを表示する**。
  参考画像にある「1つのグループ画面内に複数チーム帯（フロア1F、フロア2F…）が並ぶ」形の、
  複数チームを串刺しにした単一画面表示は**未実装・スコープ外**（3.6節）。実装する場合は、
  グループ配下のチーム一覧を取得し、チームごとに `snapshot` を呼び分けて画面内に複数帯として
  レンダリングする形が候補となる。

### 3.6 「メンバーを追加＋」の仕様

- 「メンバーを追加＋」で職員をシートに加えると、画面上にはシフト未入力の空枠行が表示されるが、
  **この時点ではDBに一切書き込まれない**。
- 保存ボタン押下時、その職員に一切シフト入力がなければ `changes[]` に含まれないため、
  `wsft_shifts` にも何も残らない。
- **シートを開き直したとき、シフト未入力の職員の行は表示されない**（残す仕組みは持たない、確定仕様）。
- 上記に伴う離脱確認メッセージ（「保存せずに閉じますか」等）は、今回は実装しない。
- 追加対象として選択できる職員は、`default_team` が異なる職員も含め**全職員**（スポットワーカー含む、
  グループを超えて共有される可能性があるため）。

**訂正（2026-07-07）**: 上記の「全職員」は、その後「表示中のチーム＋年月に現在有効な所属を
持つ人は一覧から除外する」方式に変更された。また職員・スポット（指名）タブは単一クリックでの
即時追加からチェックボックスによる複数選択＋一括登録に変更されている。詳細は3.12節を参照。

### 3.7 予定数（シフト種別ごとの必要人数）※3.14節で再設計・上書き済み

- 予定数専用のテーブルは作らず、**FastAPI側の固定・仮データ**として返す（決定事項）。
- 小計行の表示ロジックは「シフト種別ごとに、現在数の合計 / 予定数の合計」を表示するのみ
  （複雑な重み付けや按分ロジックは行わない）。

**訂正（2026-07-07に確定した最終仕様）**: 上記の「専用テーブルは作らない」は撤回された。
予定数タブの入力・保存を実現するため、`ShiftRequirement`テーブルを新設し、
チーム×日付×勤務タイプ単位で個別に保存・編集できるようにした。詳細は3.14節を参照。

### 3.8 メンバー削除（×）・並び替え（＝）

- **削除（×）**: 表示中の「チーム＋年月」のシフトのみを対象とした**論理削除**。職員マスタ
  （`wsft_staffs`）や他の月・他チームのシフトには影響しない。×押下→確認ダイアログ→即時DB反映
  （保存ボタンとは独立した経路）。`shift_type`等の値は保持したまま`deleted_at`をセットするだけなので、
  同じ職員・同じ日付に対して通常の保存フロー（4.3節）で再度シフトを入力すると、
  `update_or_create`により`deleted_at`がNULLに戻る（＝実質的な復元導線として機能する。ただし
  「×で消したものをそのまま元に戻すUI」ではない点に注意。復元専用の導線は今後の検討課題）。
- **並び替え（＝）**: チーム単位で1つだけ管理し、月ごとの個別の並びは持たない。
  ドラッグ確定時に即時DB反映（保存ボタンとは独立）。ある月で並び替えると、
  過去・未来問わずそのチームの全ての月の表示順に反映される。
  - **訂正**: 格納先として挙げていた`wsft_team_staff_order`は削除済み。現在は
    `TeamMembership.order`（当月・将来月の表示順）と`Shift.order`（過去月の凍結値）に
    分かれている（3.10節）。なお「＝」操作は常に`TeamMembership.order`を書き換えるため、
    過去月で並び替えても`Shift.order`は更新されず、過去月の表示順は変わらない。
- アイコンはいずれも全角文字（`＝`, `×`）をテキストとして表示する（ライブラリ追加なし）。

### 3.9 メンバー体系の再設計（Member / TeamMembership / SpotWorker / RecruitmentSlot）

当初「チームは場所ラベルで、所属の概念はない」としていたが、これは誤りだった。所属の概念は必要で、
かつ「日単位で管理できる所属」（例: 16日以降は別チームへ移動、この日・この週だけ他チームへ応援）
が必要という結論に至り、以下のモデルを追加した。**これにより3.6節・3.8節で述べた
「シフト未入力なら次回消える」という職員向けの旧仕様は上書きされている**（詳細下記）。

#### `wsft_member`（Memberモデル）

「誰か」を指す汎用識別子。`member_kind`（0=職員/1=スポットワーカー/2=募集枠）と`member_id`
（各テーブルでの実際のID）の組で表現する。DBレベルのFKは張らない（種別によって参照先テーブルが
変わるため）。`Shift`や`TeamMembership`は、`Staff`等を直接参照せず、必ずこの`Member`経由で
「誰か」を扱う。`unique_together(member_kind, member_id)`。

#### `wsft_team_membership`（TeamMembershipモデル）

チームへの所属期間（`team` FK, `member` FK, `start_date`, `end_date`）。
**このチームのシートに表示するかどうかだけを制御する**。シフトの実データ（`Shift`）が
何を記録するかとは無関係（`Shift`は`member`経由で`Member`を直接参照し、`TeamMembership`を
経由しない。所属期間の編集・削除が過去のシフト実績に影響しないようにするための独立性）。

- 表示ロジック: シートに表示されるメンバーは、`TeamMembership`の所属期間が対象月と重なっている
  メンバー全員（種別問わず）。**シフト入力の有無に関わらず表示され続ける**。
- 「メンバーを追加＋」のいずれのタブから追加した場合も、追加した瞬間に
  `start_date=当日, end_date=NULL(無期限)` で`TeamMembership`が即座に作成される。
- 「×」ボタン（シフトの論理削除）は、この`TeamMembership`には一切影響しない。所属の終了は
  将来の「所属管理」専用画面で行う想定（今回はスコープ外。ダイアログでは「今日から無期限」の
  即時追加のみ対応）。
- 重複期間のバリデーションは行わない（同じメンバーが期間の重なる複数チームに同時所属することも
  許容する。「移動」と「応援」を区別する特別な仕組みは持たず、単純に期間データの積み重ねで表現する）。

**訂正（このあと確定した最終仕様）**: 上記の「×はTeamMembershipに影響しない」は、実装過程で
「シフトの論理削除」と「所属の終了」を混同していたための誤りだった。最終的に以下へ変更している。

- `TeamMembership`に`is_deleted`（BooleanField, default=False）を追加
- **「×」の挙動**: `start_date`/`end_date`（実際の所属期間の事実）には一切触れず、
  「×」を押した**その`TeamMembership`行そのもの**の`is_deleted`を`True`にするだけ
- **シートへの表示条件**: 従来の期間重なり判定に加えて`is_deleted = False`であることも必要
  （`NOT tm.is_deleted`）
- **`Shift`レコード**: 一切変更しない。`×`はTeamMembership側だけを操作するため、シフト実績は
  復元に備えてそのまま保持される（旧仕様で使っていた`Shift.deleted_at`列は、現在どの操作からも
  能動的にセットされなくなった。将来的な用途のため列自体は残してある）
- フロントは、削除対象を`member_id`ではなく**`membership_id`**（`wsft_team_membership.id`）で
  指定する。`GET /api/v1/shifts/snapshot`のレスポンス（`MemberShift`）に`membership_id`を含めて
  返し、「×」押下時は`POST /shift/api/v1/team-memberships/<membership_id>/delete/`を呼ぶ
- 復元（`is_deleted`を`False`に戻す）の専用UIは今回未実装（所属管理画面での対応予定）

#### `wsft_spot_worker`（SpotWorkerモデル）

スポットワーカー。職員(`Staff`)とは明確に別モデルで管理する。項目は`name`のみ。

#### `wsft_recruitment_slot`（RecruitmentSlotモデル）

「スポット（募集）」の枠（`team` FK, `year_month`, `slot_number`）。実在の人物ではなく、
まだ誰も割り当たっていない募集枠を表す。表示名は`スポット（募集）{slot_number}`。
通常の職員・スポットワーカーと同様にシフト種別の入力・保存対象になる（仮の人物として扱う）。
`unique_together(team, year_month, slot_number)`。

#### `wsft_shifts`（Shiftモデルの変更）

`staff` FKを廃止し、`member`（FK→`Member`）に置き換えた。`team`（履歴値、FK無し）、`date`、
`shift_type`、`deleted_at`は変更なし。`unique_together(member, date)`。

### 3.10 並び順・過去月の扱いの再設計（大原則の明確化）

「シフト表は月（月度）単位で作成・確定する」という大原則を明確化した。**過去分は、メンバー構成も
並び順もマスターの変更の影響を受けるべきではない**。この原則に基づき、旧`TeamMemberOrder`
（3.9節で導入したもの）を廃止し、以下へ再構成した。

#### `TeamMembership.order`（旧`TeamMemberOrder`の統合先）

`TeamMemberOrder`テーブルは廃止し、`TeamMembership`に`order`（IntegerField, null可）を追加した。
**当月・将来月**の並び順はこちらを使う。

- 「メンバーを追加＋」で新規作成される`TeamMembership`は、その時点のチーム内最大`order`+1
  （＝末尾）を自動採番する（`_next_order()`）
- 「＝」ドラッグ確定時は、対象チームの**現在有効な**`TeamMembership`行の`order`を書き換える

#### `Shift.order`（過去月用の凍結スナップショット）

`Shift`に`order`（IntegerField, null可）を新設。シフト保存（`shifts_bulk_save`）のたびに、
その時点の`TeamMembership.order`をスナップショットとして書き込む。**過去月**の並び順は、
生きたマスターではなくこちらの凍結値を使う。

#### 過去月／当月・将来月の判定と表示ロジックの分岐

FastAPI(`GET /api/v1/shifts/snapshot`)は、`year_month`が「今日を含む月より前（過去月）」か
「今日を含む月・それ以降（当月・将来月）」かで、表示対象メンバー・並び順・職員番号(n)の
決定方法を分岐させる（判定は単純な文字列比較 `year_month < 今日を含む年月`）。

| | 当月・将来月 | 過去月 |
|---|---|---|
| 表示対象メンバー | `TeamMembership`の所属期間が重なる全員（`is_deleted=False`） | その月に`Shift`実績が1件でもあるメンバーのみ（`TeamMembership`の現在状態は無視） |
| 並び順 | `TeamMembership.order` | `Shift.order`（同一メンバーの複数行がある場合はMAXを代表値とする） |
| 職員番号(n) | `TeamMembership.start_date`の早い順 | `Shift.order`の小さい順 |
| `membership_id`（×用） | 対象の`TeamMembership.id`をそのまま返す | 関連する最新の`TeamMembership`行をベストエフォートで探して返す（見つからない場合は`null`） |

**今後の課題（今回未実装。10節にも記載）**:

- **月の「確定」操作**: 現在は「今日の日付」だけで過去/当月・将来を機械的に判定している。
  実際には参考画像にあった「シフト提出」「ステータス: 編集中/提出済み」のような、
  ユーザーが明示的に確定する操作が必要になる可能性がある（例: 翌月分を早めに確定したい等）。
- **過去月での「＝」「メンバーを追加＋」「×」操作の扱い**: 今回は特に制限を設けず、
  過去月でもこれらの操作を許可している（デモのプレゼン用に過去データを作成する検討の
  余地を残すため、意図的に開放）。ただし「＝」は常に`TeamMembership.order`（生きたマスター）
  を書き換えるため、過去月限定の並び替え（`Shift.order`のみ更新）にはならない点に注意。
  本来は過去月では非活性にする（またはShift.orderのみを更新する専用の並び替えにする）のが
  原則に忠実だが、今回はスコープ外とした。

#### 職員の表示書式・番号(n)の採番

職員の表示名は `{Staff.name} 職員{n}` 形式（例:「田中 職員1」）。`Staff.name`は素の氏名のみを
持つ（旧仕様では"田中 職員2"のような文字列をそのまま`name`に入れていたが、今回から分離した）。
番号(n)の採番基準（当月・将来月はstart_date順、過去月はShift.order順）は3.10節を参照。


- 採番対象は**職員(Staff種別)のみ**（スポットワーカー・募集枠は含めない。「現在の職員が何人いるか
  を常に把握する」という目的のための番号のため）。
- 対象月に**有効な**（`TeamMembership`が重なっている）職員だけを母集団とし、その中で
  所属開始日(`start_date`)が古い順に1,2,3...と採番する。
- 動的に繰り上がる: 例えば1〜6番のうち1番が離脱（`end_date`設定）すると、残りは1〜5に
  繰り上がる。元1番が復帰（新しい`TeamMembership`区間としてstart_dateが最新になる）すると6番になる。
  つまり番号は固定値ではなく、**表示のたびに計算し直される**。

#### 「メンバーを追加＋」のサブ画面化

ドロップダウンから、3タブ構成のサブ画面（モーダル）に変更した。

- **職員タブ**: 全職員から選択（絞り込みなし）
- **スポット（指名）タブ**: `SpotWorker`から選択（絞り込みなし）
- **スポット（募集）タブ**: 人数のみ入力。入力人数分の`RecruitmentSlot`を作成し、
  「スポット（募集）1」「スポット（募集）2」…として追加する

いずれのタブも、選択・入力した瞬間に`TeamMembership`が即座に作成される（保存ボタンを待たない）。

#### サイドメニューの追加（初出時点。6.1節で最新版に更新）

```
デモ用データ
  スポット → SpotWorkerの簡易CRUD画面
```

### 3.11 チーム名変更（📝）※2026-07-06

- `wsft_teams`の`name`のみを変更するPUT（`/shift/api/v1/teams/<id>/`）を実装した。
- 当初の想定では「チームの作成・編集UIは今回スコープ外（参照専用APIのみ）」としていたが、
  実装レビューの過程で「シフト表の見出し部分に📝ボタンによる名称変更機能（`window.prompt`で
  新しい名前を入力）」がすでに実装済みであることが判明し、暫定でこれを正式仕様として扱うことに
  した（名称変更のみ・グループの付け替え等は引き続きスコープ外）。
- `GET/PUT /shift/api/v1/teams/<id>/` のレスポンスには`group_name`も含める（3.13節の
  勤務タイプCRUD画面で、固定グループ名を表示するために利用）。

### 3.12 「メンバーを追加＋」の複数選択化・除外フィルタ※2026-07-06

- **除外フィルタ**: 職員・スポット（指名）タブの一覧から、表示中の「チーム＋年月」に
  **現在有効な所属（`TeamMembership`の期間が対象月と重なり`is_deleted=False`）を持つ人**を
  除外するようにした。過去に所属していたが現在は対象外（`end_date`経過済み、または×で
  `is_deleted=True`にした人）は、除外されず再度一覧に表示される。
  - サーバー側: `GET /staffs/` `GET /spot-workers/` に、オプションのクエリパラメータ
    `exclude_active_team`（チームID）・`year_month`を追加。両方指定時のみ除外処理を行う
    （未指定時は`StaffCrud.vue`/`SpotWorkerCrud.vue`からの呼び出しと同様に全件返す。後方互換）。
- **チェックボックスによる複数選択＋一括登録**: 職員・スポット（指名）タブは、単一クリックでの
  即時1件追加から、チェックボックスでの複数選択＋タブ下部の「追加」ボタン押下時にまとめて
  登録する方式に変更した。
  - 登録方式は、新規の一括登録APIは追加せず、既存の`POST /team-memberships/`（1件登録）を
    選択件数分ループして呼び出す（`Promise.allSettled`で並行実行）。
  - 全件成功時はモーダルを閉じてsnapshotを再取得。1件でも失敗した場合はエラーメッセージを
    表示のうえモーダルは閉じず、一覧を再取得する（成功分は登録済みのまま。失敗分だけ選び直せる）。
- スポット（募集）タブは変更なし（人数入力→`RecruitmentSlot`の一括作成のまま）。

### 3.13 勤務タイプマスタ（WorkShiftType）※2026-07-06

- サイドメニュー「デモ用管理」→「勤務タイプ」で管理するグループ単位のマスタ。テーブル定義は
  3.2節の`wsft_work_shift_types`を参照。
- 「休」のように実働時間を持たない種別も許容するため、`start_time`/`end_time`/`break_minutes`は
  いずれもNULL可。`is_overnight`（「翌」チェック）がTrueの場合、`end_time`は翌日の時刻として扱う
  （例: 開始18:00・終了08:00・is_overnight=True →「18:00～翌08:00」）。
- CRUD画面（`WorkShiftTypeCrud.vue`）の列: 名称・並び順・開始時間・翌・終了時間・休憩(分)・
  シフト上の色。画面上部のグループ選択ドロップダウンは不活性固定で、「シフト作成画面と同じ
  チーム（`TEAM_ID`固定）が属するグループ」を表示するのみ（アプリ全体にグループ切替機能が
  まだ存在しないため）。
- 色は固定10色スウォッチからの選択方式（既存5色の色調に合わせて拡張）。任意カラーピッカーは
  今回不採用。
- **既存シフト種別（`Shift.shift_type`）との整合**: `Shift.shift_type`自体は従来通り自由文字列の
  まま変更していない（FK化は見送り）。ただし、シフト保存時（`shifts_bulk_save`）に、その値が
  対象チームの属するグループの勤務タイプマスタに存在する名称かどうかをAPI側でチェックするように
  した（存在しない名称は保存エラーとして`errors[]`に積む）。
- **表示への反映**: セル編集パネル（3.16節）・小計行（`TableFooter.vue`）の種別一覧・色は、
  いずれもハードコードを廃止し、このマスタ（`order`昇順）を参照するように変更した。
- スポットワーカーの表示名も`{name} 職員{n}`と同様の書式に統一し、`{name} Spot{n}`とした
  （3.10節時点では「素の名前」だったものを変更）。募集枠の表示名も、幅を抑えるため
  `スポット（募集）{slot_number}` → `Spot募集{slot_number}` に変更した。

### 3.14 予定数のテーブル化（ShiftRequirement）※2026-07-07

3.7節の「専用テーブルは作らない」方針を撤回し、予定数タブの入力・保存を実現するため
`ShiftRequirement`テーブル（3.2節）を新設した。

- **保存粒度**: 「チーム × 年月日 × 勤務タイプ」ごとに個別の`required_count`を持つ
  （旧仕様の「勤務タイプ→固定値1つ、全日一律」から変更）。
- **保存方式**: シフト表タブのシフト保存と同じ**一括保存方式**を踏襲する。セル編集はフロントの
  メモリ内のみで保持し、保存ボタン押下時に変更差分をまとめて1回、`POST
  /shift/api/v1/shift-requirements/save/`へ送信する（5.1節と同様の考え方。ただし通常タブの
  未保存差分とは別のMapで独立管理し、保存ボタンは現在アクティブなタブに応じてどちらかを実行する）。
- 未入力の日は`required_count=0`として扱う（入力必須にはしない）。
- **表示範囲**: シフト表タブと同じ「年月」・年月切り替えUIを共有する。行は勤務タイプマスタの
  `order`順に**全種別**を表示する（そのチームで実際に使われているかどうかに関わらず）。
  過去月についても、シフト実績同様に予定数の編集を可能にしている（制限を設けていない）。
- **シフト表タブ側の小計行との連動**: `TableFooter.vue`（小計行の分母）は、`GET
  /api/v1/shifts/snapshot`が返す`shift_type_requirements`（{勤務タイプ名: {日付: 必要人数}}の
  ネスト構造）を`RequirementsGrid.vue`と共通で参照する。そのため、予定数タブでの編集は
  （保存前でも）同じ画面内で通常タブの小計行にリアルタイムに反映される。
- **モデル名の改名（重要・引き継ぎ注意）**: 初期実装では`ShiftTypeRequirement`
  （テーブル名`wsft_shift_type_requirements`）としたが、「予定数においてTypeは本質ではない」
  という指摘を受けて`ShiftRequirement`（`wsft_shift_requirements`）に改名した。マイグレーション
  0010は**新規追加ではなく、ファイル自体を直接書き換える方式（方法A）**で対応した。デモ環境で
  0010が適用済みだった場合、`makemigrations --merge`は使わず、以下の手順で対応する
  （8.2節にも同様の運用知見を追記）。
  1. 旧ファイル名（改名前の内容）を一時的に元へ戻す
  2. `python manage.py migrate work_shift 0009` で0010を巻き戻す（テーブルごと削除される）
  3. 改名後のファイルに差し替え、`python manage.py migrate work_shift` で再適用する
  - 途中で新旧2つの「0010」ファイルを同時に`migrations/`フォルダへ置くと、
    `Conflicting migrations detected; multiple leaf nodes`エラーになる（両方が`0009`を親とする
    リーフとして扱われるため）。**常にどちらか1つだけを`migrations/`フォルダに置く**のが鉄則。

### 3.15 年月プルダウン※2026-07-07

- シフト作成画面上部の「←　年月　→」の中央部分をプルダウン化し、選択で表示月を直接
  切り替えられるようにした。
- 候補一覧は「そのチームにシフト実績（`wsft_shifts`）が1件でも存在する年月」を新規エンドポイント
  `GET /shift/api/v1/teams/<id>/available-year-months/`から取得する（`TeamMembership`のみで
  実績のない月は候補に含めない）。一覧は古い月→新しい月の昇順。
- 矢印(←→)で候補一覧に含まれない月（実績のない月）へ移動した場合でも、プルダウンの選択値が
  必ず一致するよう、フロント側で現在の年月を一時的に候補へ補うフォールバックを実装している。
- プルダウンからの月変更時も、矢印操作と同様に未保存の変更がある場合は確認ダイアログを出す
  （シフト表タブ・予定数タブ、双方の未保存状態を合わせてチェックする）。
- 「←　年月　→」自体の配置は、タブの文言・幅に関わらずツールバー中央に確実に固定されるよう、
  `position: absolute; left: 50%; transform: translate(-50%, -50%)`方式に変更した（従来は
  `justify-content: space-between`でタブとの兼ね合いにより右寄りに見えていた）。

### 3.16 シフトセルの自作パネル化（日付クリックのプルダウン）※2026-07-07

- `MemberRow.vue`のシフトセルは、ネイティブの`<select>`から自作のポップアップパネル方式に
  変更した。理由は、勤務タイプごとに背景色を変えた選択肢一覧（既存の介護シフトアプリの
  UIを参考）を実現するため（ネイティブ`<select>`の`<option>`は、ブラウザ依存でCSSによる
  背景色指定が効かないことが多い）。
- **閉じたセル**: 勤務タイプの名称のみ（時刻なし）を中央寄せで表示する。
- **開いたパネル**: 各行を該当勤務タイプの`color`を背景色にして表示し、「名称＋時間」
  （例:「早番 07:00-16:00」、「夜勤 18:00-翌08:00」）を左寄せで表示する。「休」のように
  時刻を持たない種別は、名称の後ろに半角スペースのみを付けて表示する（例:「休 」）。
  パネル内の行は勤務タイプマスタの`order`順。
- パネルを閉じる操作は、外クリック・Escapeキー・行選択のいずれか（検索ボックスや
  ホバー時の詳細ツールチップは今回のスコープ外とした）。
- **既知の制約**: パネルはセル直下に`position: absolute`で重ねているだけのため、表の横スクロール
  領域（`.table-scroll`、`overflow-x: auto`）の右端に近いセルでは、パネルの一部が見切れる
  場合がある。6.3節の「メンバーを追加＋」で採用した`<Teleport to="body">`方式への統一は、
  今後の拡張候補（10節）とした。

---

## 4. API設計

本章は2026-07-18のソース照合により、実装との差分を修正済み（照合対象:
`main.py` / `views.py` / `urls.py` / `spa_views.py` / `schemas.py` / `services.py`）。

### 4.1 FastAPI（読み取り専任BFF）

#### `GET /api/v1/shifts/snapshot`

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| year_month | string | ○ | "YYYY-MM" 形式（`pattern=^\d{4}-\d{2}$`） |
| team_id | int | ○ | 表示対象チームのID（3.5節: シート＝チーム＋年月） |

**レスポンス例（2026-07-07時点。3.9〜3.16節の再設計を反映）**

```json
{
  "year_month": "2026-07",
  "team_id": 1,
  "team_name": "フロア1F",
  "group_id": 1,
  "group_name": "介護老人保健施設 さくら",
  "days_in_month": [{"date": "2026-07-01", "day_of_week": "WED"}, ...],
  "events": {
    "facility": [{"date": "2026-07-06", "title": "3階入浴"}, ...],
    "team_events": []
  },
  "member_shifts": [
    {
      "member_id": 55,
      "membership_id": 12,
      "member_name": "佐藤 職員1",
      "shifts": {"2026-07-01": "日1", "2026-07-02": "休", ...}
    },
    {
      "member_id": 58,
      "membership_id": 15,
      "member_name": "伊藤 Spot1",
      "shifts": {"2026-07-01": "早1", ...}
    },
    {
      "member_id": 61,
      "membership_id": 20,
      "member_name": "Spot募集1",
      "shifts": {}
    }
  ],
  "shift_type_requirements": {
    "日1": {"2026-07-01": 1, "2026-07-02": 1, ...},
    "早1": {"2026-07-01": 1, ...},
    "遅1": {...},
    "夜勤": {...},
    "休":  {...}
  },
  "work_shift_types": [
    {
      "id": 1, "name": "日1", "start_time": "09:00", "is_overnight": false,
      "end_time": "18:00", "break_minutes": 60, "color": "#7cb342", "order": 1
    },
    {
      "id": 4, "name": "夜勤", "start_time": "18:00", "is_overnight": true,
      "end_time": "08:00", "break_minutes": 60, "color": "#7e57c2", "order": 4
    },
    {
      "id": 5, "name": "休", "start_time": null, "is_overnight": false,
      "end_time": null, "break_minutes": null, "color": "#ec6a8a", "order": 5
    }
  ]
}
```

**実装上の要点（最新）**

- `member_shifts`（旧`staff_shifts`から改名。3.9節）は、当月・将来月では`TeamMembership`の
  所属期間が対象月と重なるメンバー全員（シフト入力の有無に関わらず表示）、過去月ではその月に
  `wsft_shifts`の実績が1件でもあるメンバーのみ（3.10節）。並び順・番号(n)の採番も3.10節・3.13節
  参照。
- `shift_type_requirements`は`{勤務タイプ名: {日付: 必要人数}}`のネスト構造（3.14節）。
  未保存の(日付, 勤務タイプ)は`0`で埋めてから返す。
- `work_shift_types`は対象チームが属するグループの勤務タイプマスタを`order`昇順で返す（3.13節）。
  セル編集パネル・小計行・予定数タブの表示は、すべてこの配列を参照する。
- `events.facility` は、`wsft_event_definitions` のうち対象年月に有効な世代（3.4節）だけを、
  `services.generate_events_for_month()` で日付展開したもの。
- `events.team_events` は常に空配列（チーム対象イベントは未実装、7節）。
**エラー時のステータス**

| ステータス | 条件 |
|---|---|
| 422 | `year_month` が `^\d{4}-\d{2}$` に不一致 / `team_id` が整数化不可 / いずれか欠落（FastAPI標準） |
| 404 | `team_id` のチームが存在しない（`detail="team_id=N が見つかりません"`） |
| 503 | `SQLAlchemyError` 全般（接続不可・テーブル欠損・SQLエラー） |
| 500 | 上記以外の未捕捉例外（下記の既知の弱点を参照） |

**接続設定**

- 環境変数 `WSFT_DATABASE_URL`（例: `postgresql+psycopg2://user:pass@host:5432/dbname`）でDB接続先を指定。
  未設定時は `postgresql+psycopg2://postgres:postgres@localhost:5432/postgres` にフォールバックする
  （エラーにはならないため、設定漏れは「接続できない」形で顕在化する点に注意）。
- `create_engine(..., pool_size=5, pool_pre_ping=True)`（`app/work_shift/db.py`）。
  「読み取り専用」はDBの権限設定ではなく、**SQLをSELECTのみに限定するという実装上の規律**で
  担保している（`main.py`のSQLは全9本がSELECT、ルートも`@app.get`の1本のみ）。

**既知の弱点（2026-07-18のコード照合で判明。未修正・改善候補）**

- `year_month="2026-13"` のような不正な月は正規表現 `^\d{4}-\d{2}$` を通過してしまい、
  `calendar.monthrange()` が `IllegalMonthError` を送出して **500** になる（422ではない）。
  月の範囲（01〜12）まで検証するのが望ましい。
- 503のレスポンスが `detail` にSQLAlchemyの例外文字列をそのまま含めており、
  **接続先情報が漏れうる**。ログにのみ出し、クライアントには定型文を返すべき。
- `try` の対象がSQL実行ブロックのみで、その後の整形処理（`json.loads`・Pydantic検証等）は
  保護されていない。
- `shift_type_requirements` は勤務タイプ**名**をキーにしているため、同一グループ内に同名の
  勤務タイプがあると衝突する（名称重複はDB制約ではなくAPI側チェックで防いでいるだけ。3.13節）。

### 4.2 Django（書き込み・マスタ管理）

ベースパス: `/shift/api/v1/`（`config/urls.py` で `shift/` をinclude、`api/v1/` は
`app/work_shift/urls.py` 側。3.1節）。**全ビューが `protected()`（`login_required` +
`no_cache_no_index`）でラップされ、書き込みはCSRFトークン必須**（2.5節）。

以下の表の「メソッド」は `@require_http_methods` で許可されているもの。不一致は **405**
（body はDjango標準のHTML）。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/shift/`（APIではなくSPA本体） | ビルド済み`index.html`を返す。未ビルド時は503（2.5節） |
| GET | `/csrf/` | `csrftoken` クッキー発行専用。`{"detail": "ok"}` を返す（2.5節） |
| GET/POST | `/groupes/` | グループ一覧取得／新規作成 |
| GET/PUT/DELETE | `/groupes/<id>/` | グループ取得／更新／削除（Team存在時はPROTECT違反で409） |
| GET | `/teams/` | チーム一覧（グループ名込み） |
| GET/PUT | `/teams/<id>/` | チーム取得／**名称変更のみ**（📝ボタン用。3.11節。作成・削除・グループ付け替えはスコープ外） |
| GET | `/teams/<id>/available-year-months/` | 年月プルダウン用。シフト実績が1件でもある年月を昇順で返す（3.15節） |
| POST | `/teams/<id>/member-order/` | チーム内メンバー並び順の一括更新（＝ドラッグ。`TeamMembership.order`へ即時反映。3.10節）※旧版はGETと誤記 |
| GET/POST | `/staffs/` | 職員一覧取得／新規作成。GETは`exclude_active_team`・`year_month`指定時のみ除外フィルタ（3.12節） |
| GET/PUT/DELETE | `/staffs/<id>/` | 職員取得／更新／削除 |
| GET/POST | `/spot-workers/` | スポットワーカー一覧取得／新規作成。GETの除外フィルタは職員と同様（3.12節） |
| GET/PUT/DELETE | `/spot-workers/<id>/` | スポットワーカー取得／更新／削除 |
| GET/POST | `/work-shift-types/` | 勤務タイプ一覧取得（`group_id`指定可）／新規作成（3.13節） |
| GET/PUT/DELETE | `/work-shift-types/<id>/` | 勤務タイプ取得／更新／削除 |
| GET/POST | `/event-definitions/` | イベント定義一覧取得／新規登録（新世代の追加） |
| PATCH | `/event-definitions/<id>/close/` | 世代を閉じる（`effective_until`設定。論理削除にも使う） |
| POST | `/team-memberships/` | 「メンバーを追加＋」（職員／スポット指名タブ共通）。1件登録。複数選択時は選択件数分ループ（3.12節） |
| POST | `/team-memberships/recruitment-slots/` | 「メンバーを追加＋」（スポット募集タブ）。人数分の`RecruitmentSlot`を一括作成 |
| POST | `/team-memberships/<id>/delete/` | メンバー削除（×）。対象`TeamMembership`行の`is_deleted`を立てるだけ（3.9節訂正版） |
| POST | `/shifts/save/` | シフト一括保存（4.3節）。勤務タイプマスタとの名称一致チェックを含む（3.13節） |
| POST | `/shift-requirements/save/` | 予定数一括保存（3.14節）。body: `{team_id, changes: [{work_shift_type_id, date, required_count}, ...]}` |

DRFは使わず、標準Django（`JsonResponse` + 生JSON parse）で実装。

**訂正（2026-07-07以降の確定仕様）**: 旧版には「デモ用途のため `@csrf_exempt` としている。
本番投入時は認証・CSRF対策が必須」と記載していたが、**これは撤回済み**。現在は
`@csrf_exempt` を一切使わず、全ビューがログイン必須＋CSRF保護下にある（2.5節）。
7節のスコープ外一覧からも該当項目を削除した。

#### 4.2.1 エラーモデル（横断仕様）

| 層 | ステータス | body形式 | 発生条件 |
|---|---|---|---|
| 認証 | 302 | HTML（ログイン画面へのリダイレクト） | 未ログイン。**401ではない**点に注意 |
| CSRF | 403 | HTML | 書き込み系で `X-CSRFToken` 欠落・不正 |
| メソッド | 405 | HTML | `@require_http_methods` 不一致 |
| 存在しないID | 404 | HTML | `get_object_or_404`（パスパラメータのID） |
| リクエスト不正 | 400 | JSON `{"error": "..."}` | `json_api` デコレータが `BadRequest` を変換 |
| 参照整合性 | 409 | JSON `{"error": "..."}` | **`DELETE /groupes/<id>/` で配下にTeamがある場合のみ**（`ProtectedError`） |

- 400の主なメッセージ: `invalid JSON` / `body must be a JSON object` / `<key> is required` /
  `<name> must be an integer` / `year_month must be "YYYY-MM"` / `<name>=<pk> not found`。
- **409は上記1箇所のみ**で、編集競合の検出ではない。楽観ロック・`select_for_update`・
  バージョン列は全ファイルで未実装であり、**一括保存はlast-write-wins**（10節の課題）。
- 勤務タイプの名称重複は409ではなく **400**（`「<name>」は既に登録されています`）。
- **一括保存系2本（`/shifts/save/`・`/shift-requirements/save/`）は二層のエラーモデル**を採る。
  リクエスト全体の不備（`team_id`欠落・`changes`が空・チーム不在）のみ400で全体を拒否し、
  要素単位のエラー（メンバー不在・マスタ未登録の勤務タイプ等）は**200のまま`errors[]`に積んで
  他の要素の保存は継続する**（バッチ全体を失敗させない）。
- 404・405・CSRF 403 がHTMLで返るのに対し、`fastapi_proxy` の403/405のみJSONで返る。
  APIクライアントから見るとレスポンス形状が不統一である点は既知の課題（10節）。

#### 4.2.2 補足（実装上の注意）

- `POST /team-memberships/` のレスポンス `{"status": "success", "member_id": N}` の `member_id` は
  **`Member`テーブルのPK**であり、リクエストで渡した `member_id`（Staff/SpotWorkerのPK）とは
  別物。
- 同メンバーを重複追加しても、有効な`TeamMembership`が既にあれば**何も作らず同じ200を返す**
  （冪等。409にはしない）。
- `POST /teams/<id>/member-order/` はチームの存在を検証せず、レスポンスの `count` は
  実際に更新された行数ではなく**入力配列の長さ**を返す。
- `member_kind` が0/1以外（例: 2や99）でも `POST /team-memberships/` は素通しで`Member`を作る。
- `_next_order()` の採番と募集枠の`slot_number`採番に排他制御は無く、同時実行で重複しうる。

### 4.3 シフト保存API（`POST /shift/api/v1/shifts/save/`）

「1回の保存操作＝1チーム・1月のシートに対する変更」という業務制約に合わせ、`team_id` はリクエスト
直下に1つだけ持たせる（各change項目には含めない）。

**リクエスト**

```json
{
  "team_id": 1,
  "changes": [
    {"member_id": 55, "date": "2026-07-01", "shift_type": "日1"},
    {"member_id": 58, "date": "2026-07-02", "shift_type": ""}
  ]
}
```

**動作**

- `shift_type` が空文字の場合は「未定に戻す」＝該当レコードの**削除**として扱う。
- `member_id` が存在しない場合は、そのchangeだけ `errors[]` に積み、他のchangeの保存は継続する
  （バッチ全体を失敗させない）。
- `shift_type`（空文字を除く）が、対象チームの属するグループの勤務タイプマスタに存在しない
  名称の場合も同様に`errors[]`に積む（3.13節）。
- 保存時点の`TeamMembership.order`を`Shift.order`にスナップショットする（3.10節）。
- `team_id` 未指定は `400`。
- レスポンス例: `{"status": "success", "saved": 2, "errors": []}`

---

## 5. 業務フロー・確定済み設計判断

### 5.1 保存方式（フロントの状態管理）

- セル変更は**フロントのメモリ内のみ**で保持する（**一括保存方式**、確定）。
  - 保存ボタン押下時に、変更差分（`changes[]`）と`team_id`をまとめて1回だけDjangoへ送信する。
  - 対案として検討した**都度保存方式**（セルを変更するたびにサーバーへPATCHを送り、
    サーバー側に一時領域を持たせる方式）は不採用とした。理由は、未確定の編集内容を
    サーバーが抱える必要が生じ、破棄・競合の扱いが複雑になるため。
- 未保存の変更があるセルはオレンジ枠でハイライトし、保存ボタンに未保存件数を表示する。
- 未保存のまま年月を切り替えようとすると、確認ダイアログ（`window.confirm`）を出す
  （「メンバー追加のみ・シフト未入力」のケースでは、この確認ダイアログは出さない、3.6節）。
- 保存成功後は、サーバーから最新のsnapshotを再取得して画面を整合させる。
- **予定数タブも同じ一括保存方式を踏襲するが、未保存差分はシフト表タブとは別のMapで独立管理する**
  （3.14節）。ヘッダーの保存ボタン・未保存件数・保存処理は、現在アクティブなタブに応じて
  対象を切り替える。年月切り替え時の確認ダイアログは、両タブの未保存状態をあわせてチェックする。

### 5.2 履歴管理（イベント定義）の運用

3.4節を参照。ポイントは「UPDATEしない」「削除は論理削除」「有効判定は半開区間の文字列比較」の3点。

### 5.3 小計行の集計仕様

- 勤務タイプマスタ（`order`昇順。3.13節）ごとに、日別で「現在数（画面上の実際の入力数）/
  予定数（`ShiftRequirement`。3.14節）」を表示する。
- 現在数 < 予定数: 赤、一致: 黒、超過: 緑、で色分けする。
- 現在数の集計はフロント側の `computed` でクライアントサイド集計する（サーバーに毎回
  問い合わせない）。予定数（分母）は`GET /api/v1/shifts/snapshot`が返す
  `shift_type_requirements`をそのまま参照するため、予定数タブでの編集（保存前でも）が
  同じ画面内でリアルタイムに反映される。

---

## 6. フロントエンド設計

### 6.1 画面構成・ナビゲーション

- **vue-routerは使用しない**。`App.vue` が現在の画面IDを `ref` で保持し、`v-if` で切り替える簡易実装。
- サイドメニュー構成（`Sidebar.vue`。2026-07-06時点の最新版）:

  ```
  勤務シフト  ← ロゴ（幅150pxのサイドバー）

  シフト管理
    シフト作成   → シフト作成画面（ShiftTableContainer.vue）
  マスタ管理
    法人        → ラベルのみ（クリック不可、カーソルも変化なし。行き先は別途作成のため今回は非活性）
    グループ    → グループCRUD画面（GroupeCrud.vue）
    管理者      → ラベルのみ（同上、非活性）
    職員        → 職員CRUD画面（StaffCrud.vue）
  デモ用管理　　← 旧「デモ用データ」から改称
    スポット     → スポットワーカーCRUD画面（SpotWorkerCrud.vue）
    勤務タイプ   → 勤務タイプCRUD画面（WorkShiftTypeCrud.vue。3.13節）
  ```

### 6.2 コンポーネント一覧

| コンポーネント | 役割 |
|---|---|
| `App.vue` | サイドバー＋メイン画面切り替え |
| `Sidebar.vue` | 左メニュー。`navigate` イベントで画面IDを親に通知 |
| `ShiftTableContainer.vue` | シフト作成画面の状態管理・API通信の親コンポーネント。シフト表/予定数タブの切替と、それぞれ独立した未保存差分・保存処理も担当 |
| `TableHeader.vue` | ステータスバー（グループ名/チーム名/最終更新者等）、年月プルダウン（3.15節）、タブ（シフト表/予定数。**両方クリック可能**） |
| `EventRow.vue` | 施設イベント／チームイベント行（日付→タイトルのマッピング表示） |
| `MemberRow.vue` | シフト表タブのメンバー1行分（職員/スポットワーカー/募集枠共通。旧`StaffRow.vue`）。シフトセルは自作の色分けパネル方式（3.16節） |
| `TableFooter.vue` | シフト表タブの小計行（現在数/予定数、色分け。5.3節） |
| `RequirementsGrid.vue` | 予定数タブの編集グリッド。勤務タイプ×日付の必要人数を直接入力（3.14節） |
| `AddMemberModal.vue` | 「メンバーを追加＋」。職員／スポット指名タブは除外フィルタ＋チェックボックス複数選択（3.12節）、スポット募集タブは人数入力のまま |
| `GroupeCrud.vue` | グループの一覧/追加/編集/削除 |
| `StaffCrud.vue` | 職員の一覧/追加/編集/削除（既定チームはTeam一覧からのプルダウン、参考値として扱う） |
| `SpotWorkerCrud.vue` | スポットワーカーの一覧/追加/編集/削除 |
| `WorkShiftTypeCrud.vue` | 勤務タイプの一覧/追加/編集/削除（3.13節）。グループ選択は不活性固定 |
| `types/shift.ts` | 型定義一式（スナップショット、保存ペイロード、マスタレコード等）。`formatWorkShiftTypeLabel()`・固定10色パレットもここ |
| `lib/api.ts` | CSRF対応の`fetch`ラッパ。`apiFetch()`は非セーフメソッド時のみ`X-CSRFToken`を付与し、常に`credentials: 'same-origin'`。`ensureCsrfToken()`はクッキーが無ければ`/shift/api/v1/csrf/`を叩く（**in-flightキャッシュで同時多発を1本に束ねる**。「メンバーを追加＋」の`Promise.allSettled`一括登録対策） |

補足: 状態管理ライブラリ（Pinia等）・`provide/inject`は**未使用**。すべてprops down / emit upで、
アプリの状態は実質`ShiftTableContainer.vue`の`ref`/`computed`が保持している。
未保存差分はタブごとに独立した2つのMap（`dirtyChanges`＝`${memberId}|${date}`、
`requirementDirtyChanges`＝`${workShiftTypeId}|${date}`）で管理し、Vueの反応性を確実に
発火させるため更新のたびに`new Map(...)`で再代入している。

### 6.3 「メンバーを追加＋」UIの実装上の注意

- ドロップダウンパネルは、テーブルの `<td>` 内に `position: absolute` で置くと、
  `overflow-x: auto` のスクロールコンテナやスタッキングコンテキストの制約で他要素の下に
  隠れてしまう問題があった。
- 対策として **`<Teleport to="body">`** でパネルをテーブル外（body直下）に描画し、
  ボタンの `getBoundingClientRect()` から算出した座標で `position: fixed` により重ねる方式にした。
- パネル外クリックで閉じる処理（`document`への`click`リスナー）も実装している。

### 6.4 CSSの既知の注意点

- 同じ詳細度（単一クラスセレクタ）のCSSクラスを複数併用すると、**後に定義された宣言がプロパティ単位で
  勝つ**（例: `.btn-small` と `.btn-primary` を併用した場合、`.btn-small` の `background` が
  `.btn-primary` の `background` を上書きし、`color` だけ`.btn-primary`の値が残るため、
  白背景×白文字で見えなくなる、という不具合が実際に発生した）。
- 対策: 併用するクラスの組み合わせ用に、明示的な複合セレクタ（例: `.btn-small.btn-primary { ... }`）を
  追加して意図した見た目を保証する。

---

## 7. スコープ外（今回のデモでは実装しない）一覧

以下は、検討の結果「今回は実装しない」と明示的に合意した項目。将来必要になった際の参照用に一覧化する。

- チームイベント（`EventRow` variant="team" は常に空。表示行のみで機能なし）
- 「所属管理」専用画面（`TeamMembership`の開始日・終了日を編集する画面。現状「メンバーを追加＋」は
  「今日から無期限」の即時追加のみ対応。所属の終了・日付範囲の指定は今回未実装）
- 正職員／臨時職員（スポットワーカー）を横断した重複バリデーション（同一人物が同時に複数チームへ
  重複所属していても検知しない）
- 「毎月」繰り返し（「第◯曜日」等）の展開ロジック（`services.py` に空実装のまま）
- 法人・管理者マスタ画面（サイドメニューは非活性ラベルのみ）
- チーム（Team）の作成・削除UI（**名称変更(📝)のみ実装済み**。3.11節で訂正） ※改定前は「参照専用APIのみ」としていたが訂正
- 複数チーム帯を1画面に串刺し表示する機能（3.5節。現状は単一チーム固定表示）
- FastAPIによる書き込み時のバリデーション・ゲートウェイ拡張
- ユーザー単位・グループ単位の認可（ログイン済みなら全データにアクセス可。2.6節）
- 楽観ロック・編集競合の検出（一括保存はlast-write-wins。4.2.1節）
- 正職員／臨時職員の区別（`Staff.default_team` の存在チェックも含め、参考値運用のみ）
- 「メンバーを追加＋」時の離脱確認メッセージ
- vue-routerによる本格的なルーティング（state切り替えの簡易実装のまま）
- 勤務タイプCRUD画面でのグループ切り替え（不活性固定。アプリ全体のグループ切替機能自体が未実装）
- 勤務タイプの並び順（`order`）編集は数値直接入力のみ。ドラッグによる並び替えUIは未実装
- シフトセル選択パネル（3.16節）の絞り込み検索ボックス・ホバー時の詳細ツールチップ
- 予定数タブにおける過去月編集の制限（シフト実績と同様、特に制限なく編集可能にしている。
  本来は月の「確定」操作と連動して過去月をロックすべきという議論は3.10節と同様に未決着）

**2026-07-07時点で解消された項目（旧版からの削除・訂正）**:
- ~~予定数タブの実データ化（現状はFastAPIの固定仮データ）~~ → 3.14節で`ShiftRequirement`
  として実装済み・解消
- ~~チーム（Team）の作成・編集UI（参照専用APIのみ実装）~~ → 3.11節の通り、名称変更のみ実装済み
- ~~認証・CSRF対策（`@csrf_exempt` のデモ実装のまま）~~ → **2.5節の通り実装済み・解消**。
  全ビューが`login_required`＋CSRF保護下にあり、`@csrf_exempt`は使用していない
  （ただし認可＝ユーザーごとのデータ分離は引き続きスコープ外。2.6節）

---

## 8. 開発・運用上の知見（引き継ぎ用メモ）

過去のトラブルシューティングで判明した、再発しやすい注意点を記録する。

### 8.1 DB権限・Owner関連

- FastAPI用のDB接続ユーザーがDjangoのマイグレーション実行ユーザーと異なる場合、
  `wsft_*` テーブルへの `SELECT` 権限が無く `permission denied` になることがある。
  同一ユーザーを使うか、読み取り専用ユーザーに明示的に `GRANT SELECT` する。
- `.env` の `DB_USER` と `settings.py` が参照する値が一致しないと、migrate実行時のテーブルOwnerが
  settings.py記載のUSERと異なる状態になりうる。実際にこのプロジェクトでも発生した実例あり
  （原因: `.env`のDB_USERが別ユーザーだった）。Owner側をsettings.pyのUSERに合わせて統一するのが
  シンプルで良い（`ALTER TABLE ... OWNER TO ...`）。

### 8.2 マイグレーション運用

- テーブル名変更（`wsft_`プレフィックス化）等でDjangoが自動生成したマイグレーションを一度コミット
  すると、後から渡された別系統のマイグレーション（依存関係が古いリーフを指したままのもの）と
  衝突し、`Conflicting migrations detected; multiple leaf nodes` エラーになることがある。
  - 対処: 新しいマイグレーションのファイル名・`dependencies` を、実際の最新リーフに向けて
    書き直す（`makemigrations --merge` で空のマージファイルを作る方法もあるが、依存関係を
    直接向け直す方がマイグレーション履歴がきれいになる）。
- FK付きフィールドを既存データがある状態で `AddField`（`default=1`等のプレースホルダー）すると、
  参照先テーブルにそのIDの行がまだ無ければ外部キー制約違反になる。既存データを作り直す前提の
  デモ環境では、**migrate前に該当テーブルを空にしておく**のが簡便（子テーブルから
  `TRUNCATE ... CASCADE` で消すか、FK依存する複数テーブルをまとめて1回のTRUNCATE文で指定する）。
- **マイグレーション適用後にモデル名・テーブル名を変更したくなった場合**（2026-07-07に
  `ShiftTypeRequirement`→`ShiftRequirement`への改名で発生。3.14節）:
  - **未適用**（まだ`migrate`していない）なら、該当マイグレーションファイルを直接書き換えるだけで
    済む。テーブル名も自由に決め直せる。
  - **適用済み**なら、以下のいずれかを選ぶ。
    1. **方法A（ファイル書き換え＋巻き戻し→再適用）**: マイグレーションファイル自体を新名称へ
       書き換え、`migrate <app> <直前の番号>`で一度巻き戻してから`migrate`で再適用する。
       実データを気にしなくてよいデモ環境ではこちらが無駄がない。
    2. **方法B（新規マイグレーションで`RenameModel`）**: 履歴を一切改変しない安全な方法だが、
       「改名だけの世代」が1つ増える。
  - **方法Aを選ぶ場合の注意点（実際にハマった手順）**:
    - ファイル名を変更した場合、`django_migrations`テーブルには**旧ファイル名**で適用記録が
      残っているため、単純に`migrate <app> <直前の番号>`を叩いても「グラフ上は既に直前の番号
      までしか進んでいない」と認識され、**巻き戻しが空振り**する
      （`No migrations to apply.`＋モデル変更未反映の警告が出る）。
    - この場合、**一時的に旧ファイル名（旧内容）を復元してから**巻き戻す必要がある。
    - このとき、新旧2つの「同じ番号」のマイグレーションファイルを同時に`migrations/`フォルダへ
      置くと、両方が同じ親から分岐したリーフとして扱われ、
      `Conflicting migrations detected; multiple leaf nodes` エラーになる。
    - **正しい手順**: ①旧ファイル名を復元し、新ファイルは退避（フォルダから一時的に除く）
      ②`migrate <app> <直前の番号>`で巻き戻す（旧テーブルが正しく削除される）
      ③旧ファイルを削除し、退避していた新ファイルを`migrations/`へ戻す
      ④`migrate`で新ファイルを新規適用する。**常に「同じ番号のファイルは1つだけ」を維持する**のが
      鉄則。

### 8.3 テスト・検証方法

**自動テスト（`app/work_shift/tests.py`。109件）**

```bash
pipenv run python manage.py test app.work_shift --settings=config.settings_test
```

`config/settings_test.py` は本番設定を継承しつつ、DBをSQLiteインメモリに、
パスワードハッシュをMD5に、静的ファイルストレージを素のものに差し替える
（`ManifestStaticFilesStorage`のままだと`collectstatic`未実行で落ちるため）。
PostgreSQLの既定設定（`--settings`省略）でも通る。

方針は「**仕様が変わっても不変な性質**に絞る」こと。`__str__`・デフォルト値・CRUDの詳細な
戻り値検証は意図的に書かない。`main.py`（別プロセスのFastAPI）・`db.py`・`schemas.py`・
`seed_work_shift.py`はテスト対象外。

| クラス | 件数 | 検証内容 |
|---|---|---|
| `AuthBoundaryTest` | 4 | **`urlpatterns`を走査して全URLのログイン必須を検証**。`protected()`の付け忘れを自動検出する |
| `NoCacheNoIndexHeaderTest` | 3 | `Cache-Control: no-store` と `X-Robots-Tag: noindex, nofollow` |
| `CsrfProtectionTest` | 8 | `enforce_csrf_checks=True`で、トークン無しPOST/PUT/DELETEが403かつ副作用なしを検証。`@csrf_exempt`の再混入を検出する |
| `InputRobustnessTest` | 23 | 不正入力が500ではなく400になること、エラー形が`{"error": ...}`で統一されていること |
| `IsRuleEffectiveTest` | 9 | 半開区間の境界（`from`は含む/`until`は含まない/空区間）・年跨ぎ・ゼロ埋め比較 |
| `GenerateEventsForMonthTest` | 13 | 週次展開、月末・平年/閏年2月、未知の曜日コードを無視、`monthly`が空 |
| `DataIntegrityTest` | 11 | PROTECT/CASCADEの伝播、各`unique_together` |
| `RecruitmentSlotNumberingTest` | 5 | 募集枠の連番採番（1始まり・最大値の次・年月ごとに独立） |
| `ActiveMemberFilterTest` | 8 | 「メンバーを追加＋」の除外フィルタの境界（月末開始・月内終了・論理削除済み・他チーム） |
| `SpaIndexTest` | 2 | ビルド成果物の有無で200/503（`mock.patch`で両分岐） |
| `FastapiProxyTest` | 7 | ホワイトリスト外403・GET以外405・透過・`URLError`で502 |
| `SmokeTest` | 16 | 主要CRUDの正常系、一括保存の要素単位エラー、論理削除、並び順更新 |

**手動検証（コード生成のたびに実施してきたもの。再開時も推奨）**

- Django側は実際に `migrate` → `seed_work_shift` → `runserver` した上で `curl` によるAPI疎通確認
- Django（書き込み）とFastAPI（読み取り）を同一DBに向けて同時起動し、保存→再取得の結合テスト
- フロントは `vue-tsc --noEmit`（strict）と `vite build` の両方が通ることを確認
  （`npm run build` は `vue-tsc -b && vite build` なので、ビルドが通れば型検査も通っている）

### 8.4 デモデータ投入

```
python manage.py seed_work_shift --ym 2026-07
```

既存の `wsft_*` データを全削除してから投入する（`--ym`省略時は実行時点の当月）。
「当月」＝`--ym`指定月、「過去月」＝その1ヶ月前として、以下を投入する（2026-07-07時点の最新版。
氏名は仮名。名字ランキング上位から選定）。

- **勤務タイプマスタ**: 日1(order=1)・早1(order=2)・遅1(order=3)・夜勤(order=4)・休(order=5)の5種
- **当月**: 職員2名（佐藤・鈴木）＋ スポット指名1名（伊藤）＋ 募集枠1件（Spot募集1）が現在有効に所属。
  募集枠にもシフト実績を入れる
- **未登録**（「メンバーを追加＋」のテスト用。当月には`TeamMembership`を持たない）:
  職員2名（高橋・田中）＋ スポット指名1名（渡辺）。このうち田中・渡辺は、過去月のみ所属していた
  実績（`TeamMembership`の`end_date`が過去月中）を持つことで、「未登録データ用」と
  「過去月表示の動作確認用データ」を1人ずつで兼用している
- **過去月**: 職員3名（佐藤・鈴木・田中）＋ スポット指名2名（伊藤・渡辺）にシフト実績あり
  （佐藤・鈴木・伊藤は当月から継続所属のため、過去月にも実績が生成される）
- **予定数（`ShiftRequirement`）**: 過去月は、その日・その勤務タイプの実績シフト数をそのまま
  `required_count`として投入する（分子=分母になり、確定済みデータのように見える）。当月は
  全種別・全日で一律`required_count=1`を投入する（従来の固定値表示と同じ見た目）

削除順序: `Member`→`ShiftRequirement`→`Team`（`RecruitmentSlot`はCASCADEで削除）→
`Staff`→`SpotWorker`→`EventDefinition`→`WorkShiftType`→`Groupe`。`Team.group`が`PROTECT`のため、
Groupeより先にTeamを消す必要がある。`Member`の削除で`Shift`・`TeamMembership`はCASCADEで消えるが、
`Staff`・`SpotWorker`は`Member`とFK直結ではない（緩い参照）ため個別削除が必要。

**冪等ではない（破壊的）**点に注意。実行のたびに全削除→再投入するため、手で作ったデモデータも
消える。`--ym`の書式検証は行っていない。

### 8.5 依存パッケージと起動手順

**Python依存**（Pipfileに追加済み）

| パッケージ | 用途 |
|---|---|
| `fastapi` | 読み取り専任BFF（`main.py`） |
| `sqlalchemy` | BFFのDB接続層（`db.py`） |
| `uvicorn` | BFFのASGIサーバー |

`django` / `psycopg2-binary` は既存のプロジェクト共通依存。

```bash
pipenv install          # 依存の取得
```

**起動（開発時。3プロセス）**

```bash
# 1. Django（書き込み系API・SPA配信・FastAPI中継）
pipenv run python manage.py runserver

# 2. FastAPI（読み取り専任BFF。必ず :8090）
WSFT_DATABASE_URL=postgresql+psycopg2://<user>:<pass>@localhost:5432/<dbname> \
  pipenv run uvicorn app.work_shift.main:app --port 8090 --reload

# 3. Vite dev server（:5173）
cd frontend/work_shift && npm install && npm run dev
```

- 開発時は **http://localhost:5173** を開く（Vite proxyが両バックエンドへ中継する。2.4節）。
- `uvicorn` は必ず `pipenv run` を付ける。付け忘れるとシステム側の `/usr/bin/uvicorn` が
  実行され、そのPythonには`fastapi`が無いため `ModuleNotFoundError: No module named 'fastapi'`
  になる。`pipenv shell` に入っていても、シェルがコマンドパスをキャッシュしていると同じ症状が
  出る（`hash -r` で解消）。
- `WSFT_DATABASE_URL` は Django の `DATABASES['default']` と**同じDBを指す**こと（8.1節）。

**本番相当の確認（Django単体で完結させる場合）**

```bash
cd frontend/work_shift && npm run build   # app/work_shift/static/work_shift/ へ出力
pipenv run python manage.py runserver
# FastAPIも :8090 で起動しておく（snapshotはDjango経由で中継される）
```

- **http://localhost:8000/shift/** を開く（ログイン必須）。
- `app/work_shift/static/` は`.gitignore`対象のため、**クローン直後やデプロイ時は
  `npm run build` が必須**。未ビルドだと `/shift/` が503になる。

---

## 9. 用語集

| 用語 | 意味 |
|---|---|
| グループ (Groupe) | 施設グループ。複数チームを束ねる最上位のマスタ |
| チーム (Team) | 「フロア1F」等の場所ラベル。職員を拘束する組織ではない |
| 職員 (Staff) | シフトに入る人。正職員相当 |
| スポットワーカー (SpotWorker) | 職員とは別モデルで管理する、指名可能な非正規の働き手 |
| 募集枠 (RecruitmentSlot) | まだ誰も割り当たっていない、人数だけのプレースホルダー枠 |
| Member | 職員/スポットワーカー/募集枠のいずれかを指す汎用識別子（member_kind + member_id） |
| TeamMembership | チームへの所属期間。シートへの表示要否だけを制御し、シフト実データとは無関係 |
| 既定チーム (default_team) | 職員のテストデータ作成時の参考値。FK制約なし |
| シート | 「チーム＋年月」で一意な、1つのシフト作成画面（表） |
| 一括保存方式 | セル変更をフロントのメモリ内のみで保持し、保存ボタン押下時にまとめてサーバーへ送る方式（採用済み。5.1節）。旧称「案B」 |
| 都度保存方式 | セルを変更するたびにサーバーへ送り、サーバー側に一時領域を持たせる方式（不採用。5.1節）。旧称「案A」 |
| 世代管理 | イベント定義の履歴管理方式。`effective_from`/`effective_until`の半開区間で新旧を管理 |
| 勤務タイプ (WorkShiftType) | グループ単位の勤務種別マスタ（日1・早1・遅1・夜勤・休等）。名称・時刻・休憩・色・並び順を持つ |
| 予定数 (ShiftRequirement) | 「チーム×日付×勤務タイプ」ごとの必要人数。小計行の分母。旧称`ShiftTypeRequirement` |

---

## 10. 今後の拡張候補（優先度順ではなく列挙）

- FastAPIのバリデーション・ゲートウェイ化（保存前チェックの一元化）
- 複数チーム帯の単一画面表示（グループ全体のシフト作成画面）
- ~~予定数のテーブル化（`wsft_shift_requirements` 等）~~ → 2026-07-07に`ShiftRequirement`
  （`wsft_shift_requirements`）として実装済み（3.14節）。解消
- 月ごとに個別の職員並び順を持たせる拡張（現状はチーム単位の単一並び順のみ）
- 論理削除したメンバーを画面から復元するための専用UI（現状は同じ日付にシフトを再入力した場合のみ復元される副次的な導線）
- チームイベント・毎月繰り返しの実装
- ~~認証・CSRF対策の本実装~~ → 2.5節で実装済み・解消。残るのは**認可**
  （ユーザー単位・グループ単位のデータ分離。2.6節）
- 編集競合の検出（楽観ロック等）。現在は一括保存がlast-write-winsで、
  同一シートを2人が同時に編集すると後勝ちで上書きされる（4.2.1節）
- APIエラーレスポンス形状の統一（現在は404/405/CSRF 403がHTML、その他がJSONで不統一。4.2.1節）
- FastAPI側の入力検証の強化と情報漏れ対策（`year_month`の月範囲チェック、
  503でのSQLAlchemy例外文字列の露出。4.1節「既知の弱点」）
- 正職員／臨時職員の区別
- vue-routerによる本格的なルーティングとURL共有
- シフトセル選択パネル（3.16節）の`<Teleport to="body">`化（横スクロール領域でのパネル見切れ対策。
  「メンバーを追加＋」用に採用済みの方式への統一）
- 勤務タイプの並び順（`order`）をドラッグ操作で編集できるUI（現状は数値の直接入力のみ）
- 月の「確定（提出）」操作の実装、およびそれに伴う過去月ロック（現状は「今日の日付」だけで
  過去/当月・将来を機械的に判定し、過去月でも各種操作を特に制限なく許可している。3.10節・7節）
- グループ・チームの切替UI自体の実装（現状はデモ用に`TEAM_ID`固定運用。実装できれば
  勤務タイプCRUD画面のグループ選択も不活性固定から解放できる）
