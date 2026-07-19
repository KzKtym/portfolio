# Work Shift（シフト作成アプリ PoC）

介護施設向けのシフト作成アプリを想定した、技術検証用PoC。
既存アプリのシフト作成画面の画像（行=職員 / 列=日付）を参考に、実際に入力・保存ができるデモ版を作成。

**Vue 3 + TypeScript / FastAPI + Django / PostgreSQL** の組み合わせで、
「読み取りはFastAPI、書き込みはDjango」という役割分担の仕組みも試みた。

## 技術検証ポイント

- **FastAPIとDjangoの役割分担**: FastAPIを「素通しのプロキシ」にせず、
  読み取り集計・整形専任のBFFとして存在意義を持たせる設計
- **月次データの履歴設計**: 「シフト表は月単位で確定する」という業務原則を、
  過去月がマスタ変更の影響を受けない構造として実装する
- **繰り返しイベントの世代管理**: 定義をUPDATEせず、有効期間の半開区間で新旧を管理し、
  過去の実績に影響を与えない
- **SPAをDjangoの認証下で配信する構成**: ビルド済みVueをDjangoから配信し、
  全エンドポイントをログイン必須＋CSRF保護下に置く

## 主な機能

**シフト作成画面**

- 行=メンバー・列=日付のマトリックス表示（月切替、土日の色分け、施設イベント行）
- セルクリックで勤務タイプごとに色分けされたパネルから選択（`夜勤 18:00-翌08:00` 形式）
- 未保存セルのハイライトと件数表示、保存ボタンで差分のみ一括送信
- メンバーの追加（職員 / スポット指名 / スポット募集の3タブ、複数選択の一括登録）
- ドラッグによる並び替え、シートからのメンバー除外（論理削除。シフト実績は保持）
- 小計行に勤務タイプ別の「現在数 / 予定数」をリアルタイム集計（不足=赤・超過=緑）
- 予定数タブで「勤務タイプ × 日付」の必要人数を直接編集
- 注： デモのため**チームは`TEAM_ID = 1`固定**。グループ・チームの切替UIは未実装。

**マスタ管理**

- グループ / 職員 / スポットワーカー / 勤務タイプ（時刻・休憩・色・並び順）のCRUD

## アーキテクチャ

```
[ Vue 3 + TypeScript (SPA) ]
        │                    │
        │ GET (読み取り)       │ POST/PUT/DELETE (書き込み)
        ▼                    ▼
[ FastAPI (読み取り専任BFF) ]   [ Django (書き込み・マスタ管理・SPA配信) ]
        │                    │
        └──────────┬─────────┘
                    ▼
         [ PostgreSQL (wsft_* テーブル) ]
```

- **FastAPI**: `GET /api/v1/shifts/snapshot` の1本のみ。複数テーブルの結合、繰り返しイベントの
  日付展開、表示名の採番、過去月/当月の表示ロジック分岐をここに集約し、1回のレスポンスで返す。
  書き込みは一切行わない（SQLは全てSELECT）。
- **Django**: マスタCRUD・シフト保存などの書き込み系に加え、ビルド済みSPAの配信と、
  本番相当経路でのFastAPIへの中継を担当する。DRFは使わず標準Djangoで実装。
- フロントの`fetch`は常に相対パス。宛先の振り分けは、開発時はVite proxy、
  ビルド配信時はDjango側の中継ビューが担うため、フロントのコードは両経路で共通。

## 設計上の要点

**過去月は「凍結」する**

「シフト表は月単位で作成・確定する」という原則から、過去分はマスタ変更の影響を受けない。

| | 当月・将来月 | 過去月 |
|---|---|---|
| 表示対象 | 所属期間が対象月と重なるメンバー全員 | その月にシフト実績があるメンバーのみ |
| 並び順 | `TeamMembership.order`（生きたマスタ） | `Shift.order`（保存時点の凍結値） |

**繰り返しイベントは世代管理する**

定義の編集時に既存行をUPDATEせず、旧行の`effective_until`を閉じて新行を作る。
有効判定は`YYYY-MM`文字列の半開区間 `[from, until)`。削除も`effective_until`をセットする論理削除。

**「誰か」を`Member`に抽象化する**

職員 / スポットワーカー / 募集枠という異なる種別を、`Member`（`member_kind` + `member_id`）で
統一的に扱う。`Shift`と`TeamMembership`は必ず`Member`経由で参照する。

## 詳細仕様

データモデル、全APIの入出力とエラー、過去月判定の分岐ロジック、設計判断に至った経緯
（採用しなかった案とその理由を含む）は以下を参照。

📄 [docs/WorkShift_SPEC.md](../../docs/WorkShift_SPEC.md)

## ディレクトリ構成

```
app/work_shift/
├── main.py            # FastAPI（読み取り専任BFF）
├── db.py              # SQLAlchemy接続層（WSFT_DATABASE_URL）
├── schemas.py         # Pydanticスキーマ
├── services.py        # 繰り返しイベントの展開・有効判定
├── models.py          # Django ORMモデル（wsft_* 11テーブル）
├── views.py           # Djangoビュー（書き込み・マスタCRUD）
├── spa_views.py       # SPA配信・CSRFトークン発行・FastAPI中継
├── urls.py            # URLconf（全ビューをlogin_requiredで包む）
├── tests.py           # Djangoテスト 109件
├── migrations/
├── static/work_shift/ # Viteのビルド成果物（.gitignore対象）
└── management/commands/
      └── seed_work_shift.py   # デモデータ投入

frontend/work_shift/   # Vue 3 + TypeScript + Vite（SPAのソース）
└── src/
      ├── App.vue            # 画面切替（vue-router不使用）
      ├── lib/api.ts         # CSRF対応fetchラッパ
      ├── types/shift.ts     # 型定義一式
      └── components/        # ShiftTableContainer / MemberRow など計12点
```

## セットアップ

### 1. 依存パッケージ

```bash
pipenv install                              # fastapi / sqlalchemy / uvicorn を含む
cd frontend/work_shift && npm install
```

### 2. マイグレーションとデモデータ

```bash
pipenv run python manage.py migrate work_shift
pipenv run python manage.py seed_work_shift --ym 2026-07
```

`seed_work_shift`は既存の`wsft_*`データを**全削除してから**投入する（デモ専用・冪等ではない）。
当月とその1ヶ月前の2ヶ月分を、過去月表示の確認ができる形で生成する。

### 3. 起動

開発時は3プロセスを立てて **http://localhost:5173** を開く。

```bash
# Django（書き込み系API・SPA配信）
pipenv run python manage.py runserver

# FastAPI（読み取り専任BFF。ポートは :8090 固定）
WSFT_DATABASE_URL=postgresql+psycopg2://<user>:<pass>@localhost:5432/<dbname> \
  pipenv run uvicorn app.work_shift.main:app --port 8090 --reload

# Vite dev server
cd frontend/work_shift && npm run dev
```

ビルド版を確認する場合は、`npm run build`後に **http://localhost:8000/shift/** を開く
（FastAPIは同様に:8090で起動しておく）。

## 動作要件

- Python 3.12 / Django（プロジェクト共通のバージョンに準拠）
- PostgreSQL（`WSFT_DATABASE_URL`はDjangoの`DATABASES`と同じDBを指すこと）
- Node.js（Vite 5 / Vue 3.4 / TypeScript 5.5）
- ログイン機能（Django標準認証）が有効になっていること

## テスト

```bash
pipenv run python manage.py test app.work_shift --settings=config.settings_test
```

109件。「仕様が変わっても不変な性質」に絞る方針で、以下を重点的に検証している。

- `urlpatterns`を走査して全URLがログイン必須であること（デコレータの付け忘れ検出）
- CSRFトークン無しの書き込みが403かつ副作用なしであること（`@csrf_exempt`の再混入検出）
- 不正入力が500ではなく400になり、エラー形が統一されていること
- 有効期間判定・繰り返し展開の境界条件（閏年、月末、半開区間の境界）

## 注意事項

- **SPAのビルド成果物はGit管理外**（`app/work_shift/static/`）。クローン直後やデプロイ時は
  `npm run build`が必須で、未ビルドだと`/shift/`が503になる。
- `uvicorn`は`pipenv run`を付けて起動する。付け忘れるとシステム側のPythonが使われ、
  `ModuleNotFoundError: No module named 'fastapi'`になる。
- ログイン済みであれば全データにアクセスできる（ユーザー単位の認可は未実装）。
- 一括保存はlast-write-winsで、編集競合の検出は行っていない。

その他のスコープ外項目と今後の拡張候補は[仕様書](../../docs/WorkShift_SPEC.md)の7節・10節を参照。
