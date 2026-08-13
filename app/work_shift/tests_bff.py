"""
work_shift の FastAPI（読み取り専任BFF）側のテスト

実行: python manage.py test app.work_shift --settings=config.settings_test

対象は main.py / services.py。tests.py（Django側）とはプロセスもフレームワークも
別だが、実体はただの Python なので Django のテストランナーから一緒に走らせる。
別コマンドを覚えなくて済むことを優先した。

DBには接続しない。main.engine を差し替え、SQL文に含まれるテーブル名で応答を振り分ける
テストダブルを使う。ここで検証したいのは SQL の方言ではなく、取得後の分岐
（過去月/当月・将来月、種別ごとの採番、表示名の組み立て、並び順、予定数の0埋め）
であるため。DB接続を伴う検証は Django 側の結合テストとデプロイ手順が担う。

SimpleTestCase を使うのは、誤ってDBに触れたら失敗させるため。
"""
import calendar
from datetime import date, time
from unittest import mock

from django.test import SimpleTestCase
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from . import main as bff
from .main import _format_time_or_none
from .services import generate_events_for_month, is_rule_effective

MEMBER_KIND_STAFF = 0
MEMBER_KIND_SPOT_WORKER = 1
MEMBER_KIND_RECRUITMENT_SLOT = 2

PAST_MONTH = "2020-01"      # 過去月分岐に入る（判定は date.today() 基準）
FUTURE_MONTH = "2999-12"    # 当月・将来月分岐に入る


# ═══════════════════════════════════════════════════════════════
# テストダブル
# ═══════════════════════════════════════════════════════════════

class _FakeResult:
    """conn.execute(...) の戻り。mappings().all() / .first() だけを備える。"""

    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeConnection:
    """SQL文に現れるテーブル名で応答を振り分ける接続。

    クエリの発行順に依存しないようにしている。_fetch_names_by_kind は
    メンバー種別の有無で発行本数が変わるため、順番で並べると壊れやすい。
    """

    def __init__(self, tables):
        self.tables = tables
        self.executed = []

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.executed.append(sql)
        return _FakeResult(self._rows_for(sql))

    def _rows_for(self, sql):
        # 判定順が重要。
        #  - wsft_shift_requirements は wsft_work_shift_types を JOIN する
        #  - 過去月のメンバー抽出は主表が wsft_shifts s だが、membership_id を引く
        #    副問い合わせの中に wsft_team_membership tm が現れる。そのため
        #    「wsft_shifts s」を先に判定し、当月・将来月側は "tm JOIN" で見分ける
        if "wsft_shift_requirements" in sql:
            return self.tables.get("requirements", [])
        if "FROM wsft_teams" in sql:
            return self.tables.get("team", [])
        if "wsft_event_definitions" in sql:
            return self.tables.get("event_definitions", [])
        if "FROM wsft_shifts s" in sql:
            return self.tables.get("membership_from_shifts", [])
        if "FROM wsft_team_membership tm JOIN" in sql:
            return self.tables.get("membership", [])
        if "FROM wsft_staffs" in sql:
            return self.tables.get("staffs", [])
        if "FROM wsft_spot_worker" in sql:
            return self.tables.get("spot_workers", [])
        if "FROM wsft_recruitment_slot" in sql:
            return self.tables.get("recruitment_slots", [])
        if "FROM wsft_shifts" in sql:
            return self.tables.get("shifts", [])
        if "FROM wsft_work_shift_types" in sql:
            return self.tables.get("work_shift_types", [])
        raise AssertionError(f"テストダブルが想定していないクエリ: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeEngine:
    def __init__(self, connection):
        self._connection = connection

    def connect(self):
        return self._connection


class _RaisingEngine:
    def connect(self):
        raise SQLAlchemyError("接続できません")


def _team_row(team_id=1):
    return {"id": team_id, "team_name": "Aチーム", "group_id": 10, "group_name": "第1グループ"}


def _membership_row(membership_id, member_id, kind, ref_id, sort_key, order):
    return {
        "membership_id": membership_id,
        "member_id": member_id,
        "sort_key": sort_key,
        "member_order": order,
        "member_kind": kind,
        "ref_id": ref_id,
    }


def _work_shift_type_row(type_id=1, name="日1", order=0):
    return {
        "id": type_id,
        "name": name,
        "start_time": time(9, 0),
        "is_overnight": False,
        "end_time": time(18, 0),
        "break_minutes": 60,
        "color": "#7cb342",
        "order": order,
    }


class _BffTestBase(SimpleTestCase):
    """main.engine を差し替えて BFF を呼ぶ土台"""

    def call(self, tables, year_month=FUTURE_MONTH, team_id=1):
        connection = _FakeConnection(tables)
        with mock.patch.object(bff, "engine", _FakeEngine(connection)):
            client = TestClient(bff.app)
            return client.get(
                "/api/v1/shifts/snapshot",
                params={"year_month": year_month, "team_id": team_id},
            )

    def minimal_tables(self, **overrides):
        tables = {
            "team": [_team_row()],
            "event_definitions": [],
            "membership": [],
            "membership_from_shifts": [],
            "staffs": [],
            "spot_workers": [],
            "recruitment_slots": [],
            "shifts": [],
            "work_shift_types": [],
            "requirements": [],
        }
        tables.update(overrides)
        return tables


# ═══════════════════════════════════════════════════════════════
# services.is_rule_effective
# ═══════════════════════════════════════════════════════════════

class IsRuleEffectiveTest(SimpleTestCase):
    """有効期間 [effective_from, effective_until) の判定"""

    def test_before_start_is_not_effective(self):
        self.assertFalse(is_rule_effective("2026-06", "2026-07", None))

    def test_start_month_is_effective(self):
        """開始月は含む（閉じている側）"""
        self.assertTrue(is_rule_effective("2026-07", "2026-07", None))

    def test_open_ended_stays_effective(self):
        """effective_until が None なら以降ずっと有効"""
        self.assertTrue(is_rule_effective("2099-12", "2026-07", None))

    def test_until_month_is_not_effective(self):
        """終了月は含まない（開いている側）"""
        self.assertFalse(is_rule_effective("2026-09", "2026-07", "2026-09"))

    def test_month_before_until_is_effective(self):
        self.assertTrue(is_rule_effective("2026-08", "2026-07", "2026-09"))

    def test_year_boundary_compares_chronologically(self):
        """ゼロ埋め YYYY-MM の辞書順比較が時系列比較になっている"""
        self.assertTrue(is_rule_effective("2027-01", "2026-12", None))
        self.assertFalse(is_rule_effective("2026-09", "2026-10", None))


# ═══════════════════════════════════════════════════════════════
# services.generate_events_for_month
# ═══════════════════════════════════════════════════════════════

class GenerateEventsForMonthTest(SimpleTestCase):
    """繰り返しルールの日付展開"""

    def test_weekly_expands_to_matching_weekdays(self):
        """2026-07 の月曜は 6/13/20/27 日"""
        events = generate_events_for_month(2026, 7, "会議", "weekly", ["MON"])

        self.assertEqual(
            [e.date for e in events],
            ["2026-07-06", "2026-07-13", "2026-07-20", "2026-07-27"],
        )

    def test_weekly_handles_multiple_days(self):
        """複数曜日は日付順に混ざって返る"""
        events = generate_events_for_month(2026, 7, "点検", "weekly", ["MON", "WED"])
        expected_count = sum(
            1
            for d in range(1, calendar.monthrange(2026, 7)[1] + 1)
            if date(2026, 7, d).weekday() in (0, 2)
        )

        self.assertEqual(len(events), expected_count)
        self.assertEqual([e.date for e in events], sorted(e.date for e in events))

    def test_title_is_carried_over(self):
        events = generate_events_for_month(2026, 7, "避難訓練", "weekly", ["FRI"])

        self.assertTrue(all(e.title == "避難訓練" for e in events))

    def test_unknown_weekday_is_ignored(self):
        """WEEKDAY_MAP に無い値は黙って捨てる"""
        events = generate_events_for_month(2026, 7, "会議", "weekly", ["MON", "XXX"])

        self.assertTrue(all(date.fromisoformat(e.date).weekday() == 0 for e in events))

    def test_empty_days_produces_nothing(self):
        self.assertEqual(generate_events_for_month(2026, 7, "会議", "weekly", []), [])

    def test_monthly_is_out_of_scope(self):
        """monthly は未実装（拡張ポイント）。空で返る"""
        self.assertEqual(generate_events_for_month(2026, 7, "会議", "monthly", ["MON"]), [])


# ═══════════════════════════════════════════════════════════════
# main._format_time_or_none
# ═══════════════════════════════════════════════════════════════

class FormatTimeOrNoneTest(SimpleTestCase):
    """DBから返る time 値の "HH:MM" 整形"""

    def test_none_stays_none(self):
        """「休」のように時刻を持たない種別は None のまま"""
        self.assertIsNone(_format_time_or_none(None))

    def test_time_object_is_formatted(self):
        self.assertEqual(_format_time_or_none(time(9, 5)), "09:05")

    def test_string_is_truncated_to_hhmm(self):
        """文字列で返る場合は先頭5文字を採る"""
        self.assertEqual(_format_time_or_none("18:30:00"), "18:30")


# ═══════════════════════════════════════════════════════════════
# エンドポイント: 入力検証・異常系
# ═══════════════════════════════════════════════════════════════

class SnapshotValidationTest(_BffTestBase):
    """クエリパラメータの検証（ハンドラに入る前に弾かれる）"""

    def test_malformed_year_month_returns_422(self):
        self.assertEqual(self.call(self.minimal_tables(), year_month="2026-7").status_code, 422)

    def test_non_date_year_month_returns_422(self):
        self.assertEqual(self.call(self.minimal_tables(), year_month="abcd-ef").status_code, 422)

    def test_missing_team_id_returns_422(self):
        with mock.patch.object(bff, "engine", _FakeEngine(_FakeConnection(self.minimal_tables()))):
            response = TestClient(bff.app).get(
                "/api/v1/shifts/snapshot", params={"year_month": FUTURE_MONTH}
            )

        self.assertEqual(response.status_code, 422)

    def test_non_integer_team_id_returns_422(self):
        self.assertEqual(self.call(self.minimal_tables(), team_id="abc").status_code, 422)


class SnapshotErrorTest(_BffTestBase):
    """異常系"""

    def test_unknown_team_returns_404(self):
        response = self.call(self.minimal_tables(team=[]))

        self.assertEqual(response.status_code, 404)
        self.assertIn("見つかりません", response.json()["detail"])

    def test_database_failure_returns_503(self):
        """接続不能は 503。原因が分かるよう WSFT_DATABASE_URL に言及する"""
        with mock.patch.object(bff, "engine", _RaisingEngine()):
            response = TestClient(bff.app).get(
                "/api/v1/shifts/snapshot",
                params={"year_month": FUTURE_MONTH, "team_id": 1},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("WSFT_DATABASE_URL", response.json()["detail"])


# ═══════════════════════════════════════════════════════════════
# エンドポイント: シート見出し・日付
# ═══════════════════════════════════════════════════════════════

class SnapshotSheetHeaderTest(_BffTestBase):
    """チーム・グループ情報と日付リスト"""

    def test_team_and_group_are_returned(self):
        body = self.call(self.minimal_tables()).json()

        self.assertEqual(body["team_name"], "Aチーム")
        self.assertEqual(body["group_id"], 10)
        self.assertEqual(body["group_name"], "第1グループ")

    def test_days_cover_the_whole_month(self):
        """2020-01 は31日ある"""
        body = self.call(self.minimal_tables(), year_month="2020-01").json()

        self.assertEqual(len(body["days_in_month"]), 31)
        self.assertEqual(body["days_in_month"][0]["date"], "2020-01-01")
        self.assertEqual(body["days_in_month"][-1]["date"], "2020-01-31")

    def test_leap_february_has_29_days(self):
        body = self.call(self.minimal_tables(), year_month="2020-02").json()

        self.assertEqual(len(body["days_in_month"]), 29)

    def test_day_of_week_is_english_abbreviation(self):
        """2020-01-01 は水曜"""
        body = self.call(self.minimal_tables(), year_month="2020-01").json()

        self.assertEqual(body["days_in_month"][0]["day_of_week"], "WED")


# ═══════════════════════════════════════════════════════════════
# エンドポイント: 表示名と採番（9節の設計原則）
# ═══════════════════════════════════════════════════════════════

class SnapshotDisplayNameTest(_BffTestBase):
    """種別ごとの表示名書式"""

    def test_staff_name_format(self):
        tables = self.minimal_tables(
            membership=[_membership_row(1, 100, MEMBER_KIND_STAFF, 500, "2026-01-01", 1)],
            staffs=[{"id": 500, "name": "山田"}],
        )

        body = self.call(tables).json()

        self.assertEqual(body["member_shifts"][0]["member_name"], "山田 職員1")

    def test_spot_worker_name_format(self):
        tables = self.minimal_tables(
            membership=[_membership_row(1, 100, MEMBER_KIND_SPOT_WORKER, 600, "2026-01-01", 1)],
            spot_workers=[{"id": 600, "name": "佐藤"}],
        )

        body = self.call(tables).json()

        self.assertEqual(body["member_shifts"][0]["member_name"], "佐藤 Spot1")

    def test_recruitment_slot_name_uses_slot_number(self):
        """募集枠は採番の対象外で、slot_number をそのまま出す"""
        tables = self.minimal_tables(
            membership=[_membership_row(1, 100, MEMBER_KIND_RECRUITMENT_SLOT, 700, "2026-01-01", 1)],
            recruitment_slots=[{"id": 700, "slot_number": 3}],
        )

        body = self.call(tables).json()

        self.assertEqual(body["member_shifts"][0]["member_name"], "Spot募集3")

    def test_missing_staff_master_is_reported_inline(self):
        """マスタが引けなくても落とさず、名前で分かるようにする"""
        tables = self.minimal_tables(
            membership=[_membership_row(1, 100, MEMBER_KIND_STAFF, 999, "2026-01-01", 1)],
            staffs=[],
        )

        body = self.call(tables).json()

        self.assertIn("不明な職員", body["member_shifts"][0]["member_name"])


class SnapshotNumberingTest(_BffTestBase):
    """種別ごとに独立した採番（母集団が別）"""

    def test_numbering_is_independent_per_kind(self):
        """職員とスポットワーカーがそれぞれ 1 から始まる"""
        tables = self.minimal_tables(
            membership=[
                _membership_row(1, 100, MEMBER_KIND_STAFF, 500, "2026-01-01", 1),
                _membership_row(2, 101, MEMBER_KIND_SPOT_WORKER, 600, "2026-01-01", 2),
                _membership_row(3, 102, MEMBER_KIND_STAFF, 501, "2026-02-01", 3),
            ],
            staffs=[{"id": 500, "name": "山田"}, {"id": 501, "name": "鈴木"}],
            spot_workers=[{"id": 600, "name": "佐藤"}],
        )

        names = [m["member_name"] for m in self.call(tables).json()["member_shifts"]]

        self.assertEqual(names, ["山田 職員1", "佐藤 Spot1", "鈴木 職員2"])

    def test_numbering_follows_start_date_for_future_month(self):
        """当月・将来月の採番は start_date の早い順（member_order とは独立）"""
        tables = self.minimal_tables(
            membership=[
                _membership_row(1, 100, MEMBER_KIND_STAFF, 500, "2026-05-01", 1),
                _membership_row(2, 101, MEMBER_KIND_STAFF, 501, "2026-01-01", 2),
            ],
            staffs=[{"id": 500, "name": "遅い"}, {"id": 501, "name": "早い"}],
        )

        names = [m["member_name"] for m in self.call(tables).json()["member_shifts"]]

        # 表示順は member_order 昇順、採番は start_date 昇順
        self.assertEqual(names, ["遅い 職員2", "早い 職員1"])

    def test_null_sort_key_is_numbered_last(self):
        """sort_key が NULL のメンバーは採番の最後に回る"""
        tables = self.minimal_tables(
            membership=[
                _membership_row(1, 100, MEMBER_KIND_STAFF, 100, None, 1),
                _membership_row(2, 101, MEMBER_KIND_STAFF, 101, "2026-01-01", 2),
            ],
            staffs=[{"id": 100, "name": "未設定"}, {"id": 101, "name": "設定あり"}],
        )

        names = [m["member_name"] for m in self.call(tables).json()["member_shifts"]]

        self.assertEqual(names, ["未設定 職員2", "設定あり 職員1"])


# ═══════════════════════════════════════════════════════════════
# エンドポイント: 過去月／当月・将来月の分岐（最重要の設計原則）
# ═══════════════════════════════════════════════════════════════

class SnapshotPastMonthBranchTest(_BffTestBase):
    """過去分はマスターの変更の影響を受けない"""

    def _tables(self):
        return self.minimal_tables(
            membership=[_membership_row(1, 100, MEMBER_KIND_STAFF, 500, "2026-01-01", 1)],
            membership_from_shifts=[
                _membership_row(9, 200, MEMBER_KIND_STAFF, 501, 5, 5)
            ],
            staffs=[{"id": 500, "name": "現在の所属"}, {"id": 501, "name": "実績のみ"}],
        )

    def test_past_month_uses_shift_records(self):
        """過去月は wsft_shifts に実績があるメンバーだけを出す"""
        body = self.call(self._tables(), year_month=PAST_MONTH).json()

        self.assertEqual([m["member_id"] for m in body["member_shifts"]], [200])

    def test_current_or_future_month_uses_membership(self):
        """当月・将来月は生きたマスター（TeamMembership）に従う"""
        body = self.call(self._tables(), year_month=FUTURE_MONTH).json()

        self.assertEqual([m["member_id"] for m in body["member_shifts"]], [100])

    def test_past_month_does_not_query_membership_table(self):
        """過去月では TeamMembership を主表として引かない"""
        connection = _FakeConnection(self._tables())
        with mock.patch.object(bff, "engine", _FakeEngine(connection)):
            TestClient(bff.app).get(
                "/api/v1/shifts/snapshot",
                params={"year_month": PAST_MONTH, "team_id": 1},
            )

        self.assertFalse(
            any("FROM wsft_team_membership tm JOIN" in sql for sql in connection.executed)
        )


# ═══════════════════════════════════════════════════════════════
# エンドポイント: 並び順・シフト実績
# ═══════════════════════════════════════════════════════════════

class SnapshotOrderingTest(_BffTestBase):
    """表示順は member_order 優先、未設定は末尾"""

    def test_sorted_by_member_order(self):
        tables = self.minimal_tables(
            membership=[
                _membership_row(1, 100, MEMBER_KIND_STAFF, 500, "2026-01-01", 3),
                _membership_row(2, 101, MEMBER_KIND_STAFF, 501, "2026-01-02", 1),
                _membership_row(3, 102, MEMBER_KIND_STAFF, 502, "2026-01-03", 2),
            ],
            staffs=[{"id": 500, "name": "C"}, {"id": 501, "name": "A"}, {"id": 502, "name": "B"}],
        )

        body = self.call(tables).json()

        self.assertEqual([m["member_id"] for m in body["member_shifts"]], [101, 102, 100])

    def test_null_order_goes_last(self):
        tables = self.minimal_tables(
            membership=[
                _membership_row(1, 100, MEMBER_KIND_STAFF, 500, "2026-01-01", None),
                _membership_row(2, 101, MEMBER_KIND_STAFF, 501, "2026-01-02", 1),
            ],
            staffs=[{"id": 500, "name": "順序なし"}, {"id": 501, "name": "順序あり"}],
        )

        body = self.call(tables).json()

        self.assertEqual([m["member_id"] for m in body["member_shifts"]], [101, 100])


class SnapshotShiftsTest(_BffTestBase):
    """シフト実績の詰め替え"""

    def _tables(self, shifts):
        return self.minimal_tables(
            membership=[_membership_row(1, 100, MEMBER_KIND_STAFF, 500, "2026-01-01", 1)],
            staffs=[{"id": 500, "name": "山田"}],
            shifts=shifts,
        )

    def test_shifts_are_keyed_by_iso_date(self):
        tables = self._tables([{"member_id": 100, "date": date(2999, 12, 3), "shift_type": "日1"}])

        body = self.call(tables).json()

        self.assertEqual(body["member_shifts"][0]["shifts"], {"2999-12-03": "日1"})

    def test_member_without_shifts_gets_empty_dict(self):
        body = self.call(self._tables([])).json()

        self.assertEqual(body["member_shifts"][0]["shifts"], {})

    def test_other_members_shifts_are_not_mixed_in(self):
        tables = self._tables(
            [
                {"member_id": 100, "date": date(2999, 12, 3), "shift_type": "日1"},
                {"member_id": 999, "date": date(2999, 12, 3), "shift_type": "夜1"},
            ]
        )

        body = self.call(tables).json()

        self.assertEqual(body["member_shifts"][0]["shifts"], {"2999-12-03": "日1"})


# ═══════════════════════════════════════════════════════════════
# エンドポイント: 勤務タイプ・予定数
# ═══════════════════════════════════════════════════════════════

class SnapshotWorkShiftTypeTest(_BffTestBase):
    """勤務タイプマスタの整形"""

    def test_times_are_formatted_as_hhmm(self):
        tables = self.minimal_tables(work_shift_types=[_work_shift_type_row()])

        body = self.call(tables).json()

        self.assertEqual(body["work_shift_types"][0]["start_time"], "09:00")
        self.assertEqual(body["work_shift_types"][0]["end_time"], "18:00")

    def test_type_without_time_keeps_none(self):
        """「休」のような種別は時刻が None のまま渡る"""
        row = _work_shift_type_row(name="休")
        row["start_time"] = None
        row["end_time"] = None

        body = self.call(self.minimal_tables(work_shift_types=[row])).json()

        self.assertIsNone(body["work_shift_types"][0]["start_time"])
        self.assertIsNone(body["work_shift_types"][0]["end_time"])


class SnapshotRequirementsTest(_BffTestBase):
    """予定数（「小計」行の分母）"""

    def test_zero_filled_for_every_day(self):
        """未保存の日は0で埋める"""
        tables = self.minimal_tables(work_shift_types=[_work_shift_type_row(name="日1")])

        body = self.call(tables, year_month="2020-01").json()

        self.assertEqual(len(body["shift_type_requirements"]["日1"]), 31)
        self.assertTrue(all(v == 0 for v in body["shift_type_requirements"]["日1"].values()))

    def test_saved_value_overrides_zero(self):
        tables = self.minimal_tables(
            work_shift_types=[_work_shift_type_row(name="日1")],
            requirements=[
                {"date": date(2020, 1, 5), "required_count": 4, "work_shift_type_name": "日1"}
            ],
        )

        body = self.call(tables, year_month="2020-01").json()

        self.assertEqual(body["shift_type_requirements"]["日1"]["2020-01-05"], 4)
        self.assertEqual(body["shift_type_requirements"]["日1"]["2020-01-06"], 0)

    def test_unknown_type_name_is_ignored(self):
        """マスタに無い勤務タイプ名の行は捨てる（KeyError にしない）"""
        tables = self.minimal_tables(
            work_shift_types=[_work_shift_type_row(name="日1")],
            requirements=[
                {"date": date(2020, 1, 5), "required_count": 4, "work_shift_type_name": "存在しない"}
            ],
        )

        body = self.call(tables, year_month="2020-01").json()

        self.assertNotIn("存在しない", body["shift_type_requirements"])


# ═══════════════════════════════════════════════════════════════
# エンドポイント: 施設イベント
# ═══════════════════════════════════════════════════════════════

class SnapshotFacilityEventTest(_BffTestBase):
    """繰り返しルールの展開結果がレスポンスに載る"""

    def _rule(self, days, effective_from="2000-01", effective_until=None):
        return {
            "title": "全体会議",
            "recurrence_type": "weekly",
            "recurrence_days": days,
            "effective_from": effective_from,
            "effective_until": effective_until,
        }

    def test_events_are_expanded_into_dates(self):
        tables = self.minimal_tables(event_definitions=[self._rule(["WED"])])

        body = self.call(tables, year_month="2020-01").json()

        self.assertEqual(
            [e["date"] for e in body["events"]["facility"]],
            ["2020-01-01", "2020-01-08", "2020-01-15", "2020-01-22", "2020-01-29"],
        )

    def test_recurrence_days_accepts_json_string(self):
        """DBが JSON 文字列で返す場合もある"""
        tables = self.minimal_tables(event_definitions=[self._rule('["WED"]')])

        body = self.call(tables, year_month="2020-01").json()

        self.assertEqual(len(body["events"]["facility"]), 5)

    def test_expired_rule_is_filtered_out(self):
        """SQLで粗く絞った後、Python側でも有効期間を確認している"""
        tables = self.minimal_tables(
            event_definitions=[self._rule(["WED"], effective_from="2000-01", effective_until="2019-01")]
        )

        body = self.call(tables, year_month="2020-01").json()

        self.assertEqual(body["events"]["facility"], [])

    def test_null_recurrence_days_is_tolerated(self):
        tables = self.minimal_tables(event_definitions=[self._rule(None)])

        body = self.call(tables, year_month="2020-01").json()

        self.assertEqual(body["events"]["facility"], [])
