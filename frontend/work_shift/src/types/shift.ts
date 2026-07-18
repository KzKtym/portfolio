// frontend/work_shift/src/types/shift.ts

export type DayOfWeek = 'MON' | 'TUE' | 'WED' | 'THU' | 'FRI' | 'SAT' | 'SUN';

export interface DayInfo {
  date: string; // YYYY-MM-DD
  day_of_week: DayOfWeek;
}

export interface EventRecord {
  date: string;
  title: string;
}

export interface TeamEvent {
  team_id: number;
  records: EventRecord[];
}

// シート表示用のメンバー1行分。member_id は wsft_member.id（Staff.idそのものではない）。
// 職員/スポットワーカー/募集枠のいずれも同じ形で扱う。表示名は既にサーバー側で組み立て済み
// （職員: "{name} 職員{n}"、スポット指名: "{name} Spot{n}"、募集枠: "Spot募集{n}"）。
export interface MemberShift {
  member_id: number;
  membership_id: number | null; // 「×」削除時にこのIDをキーとしてDjangoへ送る（過去月ではnullの場合あり）
  member_name: string;
  shifts: Record<string, string>; // 例: { "2026-07-01": "日1", "2026-07-02": "休" }
}

export interface ShiftSnapshotResponse {
  year_month: string;
  team_id: number;
  team_name: string;
  group_id: number;
  group_name: string;
  days_in_month: DayInfo[];
  events: {
    facility: EventRecord[];
    team_events: TeamEvent[];
  };
  member_shifts: MemberShift[];
  // {勤務タイプ名: {日付: 必要人数}}。「小計」行の分母。予定数タブ(F2)で編集可能
  shift_type_requirements: Record<string, Record<string, number>>;
  // 勤務タイプマスタ（対象チームが属するグループのもの）。セル編集プルダウン・下部集計行の
  // 種別一覧・表示色は、ハードコードではなくこちらを参照する
  work_shift_types: WorkShiftTypeRecord[];
}

// セル変更1件分（保存ボタン押下時に team_id とあわせて Django へ一括送信する）
export interface ShiftCellChange {
  member_id: number;
  date: string;
  shift_type: string;
}

// 保存APIのペイロード。team_idはリクエスト直下に1つだけ（1保存操作=1チーム・1月のため）
export interface ShiftBulkSavePayload {
  team_id: number;
  changes: ShiftCellChange[];
}

// メンバー種別（Member.member_kind と対応）
export const MEMBER_KIND_STAFF = 0;
export const MEMBER_KIND_SPOT_WORKER = 1;
export const MEMBER_KIND_RECRUITMENT_SLOT = 2;

// ---- マスタ管理 ----
export interface GroupeRecord {
  id: number;
  name: string;
}

export interface TeamRecord {
  id: number;
  name: string;
  group_id: number;
  group_name: string;
}

export interface StaffRecord {
  id: number;
  name: string;
  default_team: number | null;
}

export interface SpotWorkerRecord {
  id: number;
  name: string;
}

// 勤務タイプマスタ1件分（サイドメニュー「デモ用管理」→「勤務タイプ」で管理。グループ単位）。
// 「休」のように実働時間を持たない種別は start_time/end_time が null になる。
export interface WorkShiftTypeRecord {
  id: number;
  group_id: number;
  name: string;
  start_time: string | null; // "HH:MM"
  is_overnight: boolean;     // 「翌」チェック。trueならend_timeは翌日扱い
  end_time: string | null;   // "HH:MM"
  break_minutes: number | null;
  color: string;             // 例: "#7cb342"
  order: number;             // 並び順（一覧・パネル・下部集計行の並びに使用）
}

// 日付クリックのプルダウン（MemberRow.vueのセル編集セレクト）用の表示ラベルを組み立てる。
// 例: "日1 09:00-18:00"、"夜勤 18:00-翌08:00"、時刻未設定（「休」等）は "休 "（末尾に半角スペース）
export const formatWorkShiftTypeLabel = (w: WorkShiftTypeRecord): string => {
  if (!w.start_time || !w.end_time) return `${w.name} `;
  const endPrefix = w.is_overnight ? '翌' : '';
  return `${w.name} ${w.start_time}-${endPrefix}${w.end_time}`;
};

// 「勤務タイプ」CRUD画面のカラーパレット（固定10色スウォッチ選択方式。既存の色調に合わせている）
export const WORK_SHIFT_TYPE_COLOR_PALETTE = [
  '#7cb342', // 日1相当（黄緑）
  '#26c6da', // 早1相当（シアン）
  '#42a5f5', // 遅1相当（青）
  '#7e57c2', // 夜勤相当（紫）
  '#ec6a8a', // 休相当（ピンク）
  '#fb8c00', // オレンジ
  '#26a69a', // ティール
  '#8d6e63', // ブラウン
  '#5c6bc0', // インディゴ
  '#ef5350', // レッド
] as const;
