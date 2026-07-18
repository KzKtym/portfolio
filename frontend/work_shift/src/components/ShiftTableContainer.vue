<script setup lang="ts">
// ShiftTableContainer.vue
// 全体ラッパー。状態管理とAPI通信を担当する。
//
// 通信方針（確定済みの設計判断）:
// - 読み取り: FastAPI(BFF)  GET  /api/v1/shifts/snapshot?year_month=...&team_id=...
// - 書き込み: Django        POST /shift/api/v1/shifts/save/  body: {team_id, changes[]}
// - 「チーム＋年月」が1つのシートとして一意（デモでは単一チーム固定運用）。
// - セル変更はフロントのメモリ内のみで保持し（案B）、保存ボタン押下時に
//   変更差分(changes[])とteam_idをまとめて1回だけDjangoへ送信する。
// - 表示対象メンバー（職員/スポットワーカー/募集枠）は、サーバー側のTeamMembership
//   （所属期間）によって決まる。シフト入力の有無に関わらず、所属期間中は表示され続ける。
//   「メンバーを追加＋」はAddMemberModalでの追加操作の瞬間にDjango側でTeamMembershipが
//   即座に作られるため、フロント側でメモリ内だけの仮追加は行わない（追加後にsnapshotを
//   再取得するだけでよい）。
import { computed, onMounted, ref } from 'vue';
import type { ShiftSnapshotResponse } from '../types/shift';
import TableHeader from './TableHeader.vue';
import EventRow from './EventRow.vue';
import MemberRow from './MemberRow.vue';
import TableFooter from './TableFooter.vue';
import RequirementsGrid from './RequirementsGrid.vue';
import AddMemberModal from './AddMemberModal.vue';
import { apiFetch } from '../lib/api';

// デモでは単一チーム固定運用（複数チームの串刺し表示は今回のスコープ外）
const TEAM_ID = 1;

const snapshotData = ref<ShiftSnapshotResponse | null>(null);
const isLoading = ref(true);
const isSaving = ref(false);
const errorMessage = ref('');
const currentYearMonth = ref(new Date().toISOString().slice(0, 7)); // "YYYY-MM"

// 年月プルダウンの候補（そのチームにシフト実績が1件でも存在する年月。昇順）
const availableYearMonths = ref<string[]>([]);

const lastUpdatedBy = ref('デモ管理者');
const lastUpdatedAt = ref('-');

// ---- タブ切り替え（通常F1 / 予定数F2） ----
const activeTab = ref<'normal' | 'requirements'>('normal');

// ---- 未保存の変更差分（案B: メモリ内のみで保持） ----
const dirtyChanges = ref<Map<string, { member_id: number; date: string; shift_type: string }>>(new Map());
const dirtyKeys = computed(() => new Set(dirtyChanges.value.keys()));
const isDirty = computed(() => dirtyChanges.value.size > 0);

// 予定数タブ(F2)の未保存差分。通常タブとは別のMapで独立管理する
// （キー: `${workShiftTypeId}|${date}`）
const requirementDirtyChanges = ref<Map<string, { work_shift_type_id: number; date: string; required_count: number }>>(new Map());
const requirementDirtyKeys = computed(() => new Set(requirementDirtyChanges.value.keys()));
const isRequirementDirty = computed(() => requirementDirtyChanges.value.size > 0);

// ヘッダーの保存ボタン・未保存件数は、現在アクティブなタブの状態を表示する
const isAnyDirty = computed(() => isDirty.value || isRequirementDirty.value);
const activeIsDirty = computed(() => (activeTab.value === 'normal' ? isDirty.value : isRequirementDirty.value));
const activeDirtyCount = computed(() =>
  activeTab.value === 'normal' ? dirtyChanges.value.size : requirementDirtyChanges.value.size
);

// ---- 並び替え（＝ドラッグ）。チーム単位で1つだけ管理し、確定時に即時DB反映する ----
const draggingMemberId = ref<number | null>(null);
const dragOverMemberId = ref<number | null>(null);

const handleDragStart = (memberId: number) => {
  draggingMemberId.value = memberId;
};
const handleDragOver = (memberId: number) => {
  dragOverMemberId.value = memberId;
};
const handleDragEnd = () => {
  draggingMemberId.value = null;
  dragOverMemberId.value = null;
};
const handleDrop = async (targetMemberId: number) => {
  const sourceMemberId = draggingMemberId.value;
  draggingMemberId.value = null;
  dragOverMemberId.value = null;
  if (!snapshotData.value || sourceMemberId === null || sourceMemberId === targetMemberId) return;

  const list = snapshotData.value.member_shifts;
  const fromIndex = list.findIndex(m => m.member_id === sourceMemberId);
  const toIndex = list.findIndex(m => m.member_id === targetMemberId);
  if (fromIndex === -1 || toIndex === -1) return;

  const [moved] = list.splice(fromIndex, 1);
  list.splice(toIndex, 0, moved);

  // ドラッグ確定＝即時DB反映（保存ボタンとは独立した操作）
  try {
    const memberOrder = list.map(m => m.member_id);
    const res = await apiFetch(`/shift/api/v1/teams/${TEAM_ID}/member-order/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ member_order: memberOrder }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (error) {
    console.error('並び順の保存に失敗しました:', error);
    errorMessage.value = `並び順の保存に失敗しました: ${error instanceof Error ? error.message : error}`;
  }
};

// ---- メンバー削除（×。対象TeamMembership行のis_deletedを立てるだけ。確認ダイアログ後に即時DB反映）
// Shiftレコード（シフト実績の値）には一切触れない。復元時にそのまま使えるよう温存する。
// 削除後はsnapshotを再取得する（職員番号(n)はサーバー側で組み立て済みの文字列のため、
// ローカルで行を取り除くだけでは残ったメンバーの番号が再計算されず古いままになるバグがあった）。
const handleDeleteMember = async (membershipId: number | null) => {
  if (!snapshotData.value) return;
  const member = snapshotData.value.member_shifts.find(m => m.membership_id === membershipId);
  if (!member) return;

  if (membershipId === null) {
    errorMessage.value = 'このメンバーは所属情報が見つからないため削除できません（過去月の実績のみのメンバーである可能性があります）。';
    return;
  }

  const ok = window.confirm(`「${member.member_name}」をこのシートから外しますか？（シフトの記録は保持されます）`);
  if (!ok) return;

  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/team-memberships/${membershipId}/delete/`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    // 未保存差分を破棄したうえで、サーバーから最新状態を再取得する（番号(n)の再計算のため）
    const memberId = member.member_id;
    for (const key of Array.from(dirtyChanges.value.keys())) {
      if (key.startsWith(`${memberId}|`)) dirtyChanges.value.delete(key);
    }
    dirtyChanges.value = new Map(dirtyChanges.value);
    await fetchShiftSnapshot(currentYearMonth.value);
  } catch (error) {
    console.error('メンバーの削除に失敗しました:', error);
    errorMessage.value = `メンバーの削除に失敗しました: ${error instanceof Error ? error.message : error}`;
  }
};

// ---- メンバーを追加＋（サブ画面。追加確定は即時DB反映のため、閉じたらsnapshotを再取得する） ----
const showAddMemberModal = ref(false);
const handleMemberAdded = () => {
  fetchShiftSnapshot(currentYearMonth.value);
};

// ---- スナップショット取得（FastAPI / 読み取り専任BFF） ----
const fetchShiftSnapshot = async (yearMonth: string) => {
  isLoading.value = true;
  errorMessage.value = '';
  try {
    const response = await fetch(`/api/v1/shifts/snapshot?year_month=${yearMonth}&team_id=${TEAM_ID}`);
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail ?? `HTTP error! status: ${response.status}`);
    }
    snapshotData.value = await response.json();
    dirtyChanges.value = new Map(); // 月を読み直したら差分はリセット
    requirementDirtyChanges.value = new Map();
  } catch (error) {
    console.error('データ取得に失敗しました:', error);
    errorMessage.value = `データ取得に失敗しました: ${error instanceof Error ? error.message : error}`;
    snapshotData.value = null;
  } finally {
    isLoading.value = false;
  }
};

// ---- セル変更（メモリ内のみ / O(1)更新） ----
const handleShiftChange = (payload: { memberId: number; date: string; shiftType: string }) => {
  if (!snapshotData.value) return;
  const member = snapshotData.value.member_shifts.find(m => m.member_id === payload.memberId);
  if (!member) return;

  if (payload.shiftType === '') {
    delete member.shifts[payload.date];
  } else {
    member.shifts[payload.date] = payload.shiftType;
  }

  dirtyChanges.value.set(`${payload.memberId}|${payload.date}`, {
    member_id: payload.memberId,
    date: payload.date,
    shift_type: payload.shiftType,
  });
  dirtyChanges.value = new Map(dirtyChanges.value);
};

// ---- 予定数セル変更（メモリ内のみ / O(1)更新） ----
const handleRequirementChange = (payload: { workShiftTypeId: number; date: string; requiredCount: number }) => {
  if (!snapshotData.value) return;
  const workShiftType = snapshotData.value.work_shift_types.find(w => w.id === payload.workShiftTypeId);
  if (!workShiftType) return;

  if (!snapshotData.value.shift_type_requirements[workShiftType.name]) {
    snapshotData.value.shift_type_requirements[workShiftType.name] = {};
  }
  snapshotData.value.shift_type_requirements[workShiftType.name][payload.date] = payload.requiredCount;

  requirementDirtyChanges.value.set(`${payload.workShiftTypeId}|${payload.date}`, {
    work_shift_type_id: payload.workShiftTypeId,
    date: payload.date,
    required_count: payload.requiredCount,
  });
  requirementDirtyChanges.value = new Map(requirementDirtyChanges.value);
};

// ---- 予定数の保存（Django / 一括反映） ----
const handleSaveRequirements = async () => {
  if (!isRequirementDirty.value || isSaving.value) return;
  isSaving.value = true;
  errorMessage.value = '';
  try {
    const changes = Array.from(requirementDirtyChanges.value.values());
    const response = await apiFetch('/shift/api/v1/shift-requirements/save/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team_id: TEAM_ID, changes }),
    });
    if (!response.ok) {
      throw new Error(`保存に失敗しました (status: ${response.status})`);
    }
    const result = await response.json();
    if (result.errors?.length) {
      console.warn('一部の予定数が保存できませんでした:', result.errors);
      errorMessage.value = `一部の予定数が保存できませんでした（${result.errors.length}件）。詳細はコンソールを確認してください。`;
    }
    requirementDirtyChanges.value = new Map();
    lastUpdatedAt.value = new Date().toLocaleString('ja-JP');
  } catch (error) {
    console.error('予定数の保存に失敗しました:', error);
    errorMessage.value = `${error instanceof Error ? error.message : error}`;
  } finally {
    isSaving.value = false;
  }
};

// ヘッダーの保存ボタンは、現在アクティブなタブに応じてどちらかを実行する
const handleSaveActive = () => {
  if (activeTab.value === 'normal') {
    handleSave();
  } else {
    handleSaveRequirements();
  }
};
const handleSave = async () => {
  if (!isDirty.value || isSaving.value) return;
  isSaving.value = true;
  errorMessage.value = '';
  try {
    const changes = Array.from(dirtyChanges.value.values());
    const response = await apiFetch('/shift/api/v1/shifts/save/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team_id: TEAM_ID, changes }),
    });
    if (!response.ok) {
      throw new Error(`保存に失敗しました (status: ${response.status})`);
    }
    const result = await response.json();
    if (result.errors?.length) {
      console.warn('一部の変更が保存できませんでした:', result.errors);
      errorMessage.value = `一部の変更が保存できませんでした（${result.errors.length}件）。詳細はコンソールを確認してください。`;
    }
    dirtyChanges.value = new Map();
    lastUpdatedAt.value = new Date().toLocaleString('ja-JP');
    await fetchShiftSnapshot(currentYearMonth.value);
  } catch (error) {
    console.error('シフトの保存に失敗しました:', error);
    errorMessage.value = `${error instanceof Error ? error.message : error}`;
  } finally {
    isSaving.value = false;
  }
};

// ---- 年月切り替え ----
const fetchAvailableYearMonths = async () => {
  try {
    const res = await fetch(`/shift/api/v1/teams/${TEAM_ID}/available-year-months/`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    availableYearMonths.value = (await res.json()).year_months;
  } catch (error) {
    console.error('年月一覧の取得に失敗しました:', error);
  }
};

const handleChangeMonth = (delta: number) => {
  if (isAnyDirty.value) {
    const ok = window.confirm('未保存の変更があります。破棄して月を切り替えますか？');
    if (!ok) return;
  }
  const [y, m] = currentYearMonth.value.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  currentYearMonth.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  fetchShiftSnapshot(currentYearMonth.value);
};

// 年月プルダウンからの直接選択。矢印操作と同様に未保存の変更があれば確認する
const handleSelectMonth = (yearMonth: string) => {
  if (yearMonth === currentYearMonth.value) return;
  if (isAnyDirty.value) {
    const ok = window.confirm('未保存の変更があります。破棄して月を切り替えますか？');
    if (!ok) return;
  }
  currentYearMonth.value = yearMonth;
  fetchShiftSnapshot(yearMonth);
};

// ---- チーム名変更（📝。シンプルにwindow.promptで完結させる） ----
const handleRenameTeam = async () => {
  if (!snapshotData.value) return;
  const newName = window.prompt('新しいチーム名を入力してください', snapshotData.value.team_name);
  if (newName === null || newName.trim() === '') return;

  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/teams/${TEAM_ID}/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName.trim() }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    snapshotData.value.team_name = body.name;
  } catch (error) {
    console.error('チーム名の変更に失敗しました:', error);
    errorMessage.value = `チーム名の変更に失敗しました: ${error instanceof Error ? error.message : error}`;
  }
};

// ---- 表示用ヘルパー ----
const dayNumber = (date: string) => Number(date.split('-')[2]);
const JP_DOW: Record<string, string> = {
  MON: '月', TUE: '火', WED: '水', THU: '木', FRI: '金', SAT: '土', SUN: '日',
};
const dowClass = (dow: string) =>
  dow === 'SUN' ? 'dow-sun' : dow === 'SAT' ? 'dow-sat' : '';

onMounted(() => {
  fetchShiftSnapshot(currentYearMonth.value);
  fetchAvailableYearMonths();
});
</script>

<template>
  <div class="page-root">
    <TableHeader
      :group-name="snapshotData?.group_name ?? '-'"
      :team-name="snapshotData?.team_name ?? '-'"
      :year-month="currentYearMonth"
      :available-year-months="availableYearMonths"
      :active-tab="activeTab"
      :is-dirty="activeIsDirty"
      :dirty-count="activeDirtyCount"
      :last-updated-by="lastUpdatedBy"
      :last-updated-at="lastUpdatedAt"
      :is-saving="isSaving"
      @change-month="handleChangeMonth"
      @select-month="handleSelectMonth"
      @change-tab="(tab) => (activeTab = tab)"
      @save="handleSaveActive"
    />

    <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>

    <div v-if="isLoading" class="loading">データを読み込み中...</div>

    <div v-else-if="snapshotData && activeTab === 'normal'" class="table-scroll">
      <table class="shift-table">
        <thead>
          <tr class="day-header-row">
            <th class="corner-cell sticky-col"></th>
            <th
              v-for="day in snapshotData.days_in_month"
              :key="day.date"
              class="day-header"
              :class="dowClass(day.day_of_week)"
            >
              {{ dayNumber(day.date) }} {{ JP_DOW[day.day_of_week] }}
            </th>
          </tr>
          <EventRow
            label="施設イベント"
            variant="facility"
            :days="snapshotData.days_in_month"
            :records="snapshotData.events.facility"
          />
        </thead>

        <tbody>
          <tr class="team-band">
            <td class="team-band-cell sticky-col">
              <span class="team-icon team-icon-inactive" data-tip="開発中...">↑</span>
              <span class="team-icon team-icon-inactive" data-tip="開発中...">↓</span>
              <span class="team-icon team-icon-inactive" data-tip="開発中...">×</span>
              <span class="team-band-name">{{ snapshotData.team_name }}</span>
              <button class="team-icon team-icon-active" title="チーム名を変更" @click="handleRenameTeam">📝</button>
              <span class="team-icon team-icon-inactive" data-tip="開発中...">＋</span>
            </td>
            <td :colspan="snapshotData.days_in_month.length" class="team-band-fill"></td>
          </tr>
          <EventRow
            label="チームイベント"
            variant="team"
            :days="snapshotData.days_in_month"
            :records="[]"
          />
          <MemberRow
            v-for="member in snapshotData.member_shifts"
            :key="member.member_id"
            :member="member"
            :days="snapshotData.days_in_month"
            :dirty-keys="dirtyKeys"
            :is-drag-over="dragOverMemberId === member.member_id"
            :work-shift-types="snapshotData.work_shift_types"
            @update-cell="handleShiftChange"
            @delete-member="handleDeleteMember"
            @drag-start="handleDragStart"
            @drag-over="handleDragOver"
            @drop="handleDrop"
            @drag-end="handleDragEnd"
          />
          <tr class="add-member-row">
            <td class="sticky-col add-member-cell" :colspan="1">
              <button class="add-member-button" @click="showAddMemberModal = true">
                メンバーを追加＋
              </button>
            </td>
            <td :colspan="snapshotData.days_in_month.length"></td>
          </tr>
        </tbody>

        <TableFooter
          :days="snapshotData.days_in_month"
          :member-shifts="snapshotData.member_shifts"
          :requirements="snapshotData.shift_type_requirements"
          :work-shift-types="snapshotData.work_shift_types"
        />
      </table>
    </div>

    <RequirementsGrid
      v-else-if="snapshotData && activeTab === 'requirements'"
      :days="snapshotData.days_in_month"
      :work-shift-types="snapshotData.work_shift_types"
      :requirements="snapshotData.shift_type_requirements"
      :dirty-keys="requirementDirtyKeys"
      @update-cell="handleRequirementChange"
    />

    <AddMemberModal
      v-if="showAddMemberModal"
      :team-id="TEAM_ID"
      :year-month="currentYearMonth"
      @close="showAddMemberModal = false"
      @added="handleMemberAdded"
    />
  </div>
</template>

<style scoped>
.page-root {
  min-height: 100vh;
  background: #f3f4f6;
  font-family: 'Hiragino Kaku Gothic ProN', 'Yu Gothic', Meiryo, sans-serif;
}
.error-banner {
  margin: 12px 16px;
  padding: 10px 14px;
  border: 1px solid #fca5a5;
  background: #fef2f2;
  color: #b91c1c;
  border-radius: 6px;
  font-size: 13px;
}
.loading {
  padding: 40px;
  color: #6b7280;
  font-size: 14px;
}
.table-scroll {
  margin: 12px 16px;
  overflow-x: auto;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.shift-table {
  border-collapse: collapse;
  width: max-content;
  min-width: 100%;
}
.shift-table :deep(th),
.shift-table :deep(td) {
  border: 1px solid #e5e7eb;
}
.day-header-row {
  background: #f9fafb;
}
.corner-cell {
  min-width: 140px;
  background: #f9fafb;
}
.sticky-col {
  position: sticky;
  left: 0;
  z-index: 10;
}
.day-header {
  padding: 6px 4px;
  font-size: 12px;
  font-weight: 600;
  color: #374151;
  min-width: 56px;
  text-align: center;
  white-space: nowrap;
}
.dow-sun { color: #dc2626; }
.dow-sat { color: #2563eb; }
.team-band-cell {
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 700;
  color: #1f2937;
  background: #e5e7eb;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 4px;
}
.team-band-name {
  margin: 0 4px;
}
.team-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  border: none;
  background: transparent;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
}
.team-icon-inactive {
  color: #9ca3af;
}
.team-icon-active {
  color: #1f2937;
}
.team-icon-active:hover {
  color: #2563eb;
}
/* 非活性アイコンのホバーバッジ「開発中...」（ツールチップ的に表示） */
.team-icon-inactive::after {
  content: attr(data-tip);
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  margin-bottom: 4px;
  padding: 2px 6px;
  background: #374151;
  color: #ffffff;
  font-size: 10px;
  font-weight: 500;
  white-space: nowrap;
  border-radius: 4px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
  z-index: 30;
}
.team-icon-inactive:hover::after {
  opacity: 1;
}
.team-band-fill {
  background: #e5e7eb;
}
.add-member-row {
  background: #ffffff;
}
.add-member-cell {
  padding: 6px 10px;
  background: #ffffff;
}
.add-member-button {
  border: 1px dashed #9ca3af;
  background: transparent;
  color: #4b5563;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}
</style>
