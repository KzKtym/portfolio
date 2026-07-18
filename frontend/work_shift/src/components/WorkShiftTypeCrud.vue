<script setup lang="ts">
// WorkShiftTypeCrud.vue
// 勤務タイプの簡易CRUD画面（サイドメニュー「デモ用管理」→「勤務タイプ」）。
// グループ単位のマスタ。上部のグループ選択ドロップダウンは、アプリ全体にグループ切替機能が
// まだ存在しない（シフト作成画面はTEAM_ID固定運用）ため、「シフト作成と同じチームが属する
// グループ」を不活性表示するだけに留める（確定仕様）。
import { onMounted, ref } from 'vue';
import type { WorkShiftTypeRecord } from '../types/shift';
import { WORK_SHIFT_TYPE_COLOR_PALETTE } from '../types/shift';
import { apiFetch } from '../lib/api';

// シフト作成画面（ShiftTableContainer.vue）と同じ固定チーム。ここから所属グループを引く。
const TEAM_ID = 1;

const groupId = ref<number | null>(null);
const groupName = ref<string>('-');

const workShiftTypes = ref<WorkShiftTypeRecord[]>([]);
const isLoading = ref(true);
const errorMessage = ref('');

// ---- 新規作成フォーム ----
const newName = ref('');
const newStartTime = ref('');
const newIsOvernight = ref(false);
const newEndTime = ref('');
const newBreakMinutes = ref<string>('');
const newColor = ref<string>(WORK_SHIFT_TYPE_COLOR_PALETTE[0]);
const newOrder = ref<string>('');

// ---- 編集中の行 ----
const editingId = ref<number | null>(null);
const editingName = ref('');
const editingStartTime = ref('');
const editingIsOvernight = ref(false);
const editingEndTime = ref('');
const editingBreakMinutes = ref<string>('');
const editingColor = ref<string>(WORK_SHIFT_TYPE_COLOR_PALETTE[0]);
const editingOrder = ref<string>('');

const fetchGroupContext = async () => {
  const res = await fetch(`/shift/api/v1/teams/${TEAM_ID}/`);
  if (!res.ok) throw new Error(`teams HTTP ${res.status}`);
  const body = await res.json();
  groupId.value = body.group_id;
  groupName.value = body.group_name;
};

const fetchWorkShiftTypes = async () => {
  if (groupId.value === null) return;
  const res = await fetch(`/shift/api/v1/work-shift-types/?group_id=${groupId.value}`);
  if (!res.ok) throw new Error(`work-shift-types HTTP ${res.status}`);
  workShiftTypes.value = (await res.json()).work_shift_types;
};

const fetchAll = async () => {
  isLoading.value = true;
  errorMessage.value = '';
  try {
    await fetchGroupContext();
    await fetchWorkShiftTypes();
  } catch (e) {
    errorMessage.value = `一覧の取得に失敗しました: ${e instanceof Error ? e.message : e}`;
  } finally {
    isLoading.value = false;
  }
};

const resetNewForm = () => {
  newName.value = '';
  newStartTime.value = '';
  newIsOvernight.value = false;
  newEndTime.value = '';
  newBreakMinutes.value = '';
  newColor.value = WORK_SHIFT_TYPE_COLOR_PALETTE[0];
  newOrder.value = '';
};

const handleCreate = async () => {
  if (!newName.value.trim() || groupId.value === null) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch('/shift/api/v1/work-shift-types/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        group_id: groupId.value,
        name: newName.value.trim(),
        start_time: newStartTime.value || null,
        is_overnight: newIsOvernight.value,
        end_time: newEndTime.value || null,
        break_minutes: newBreakMinutes.value !== '' ? Number(newBreakMinutes.value) : null,
        color: newColor.value,
        order: newOrder.value !== '' ? Number(newOrder.value) : 0,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.error ?? `HTTP ${res.status}`);
    }
    resetNewForm();
    await fetchWorkShiftTypes();
  } catch (e) {
    errorMessage.value = `作成に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

const startEdit = (w: WorkShiftTypeRecord) => {
  editingId.value = w.id;
  editingName.value = w.name;
  editingStartTime.value = w.start_time ?? '';
  editingIsOvernight.value = w.is_overnight;
  editingEndTime.value = w.end_time ?? '';
  editingBreakMinutes.value = w.break_minutes !== null ? String(w.break_minutes) : '';
  editingColor.value = w.color;
  editingOrder.value = String(w.order);
};

const cancelEdit = () => {
  editingId.value = null;
};

const handleUpdate = async (id: number) => {
  if (!editingName.value.trim()) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/work-shift-types/${id}/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: editingName.value.trim(),
        start_time: editingStartTime.value || null,
        is_overnight: editingIsOvernight.value,
        end_time: editingEndTime.value || null,
        break_minutes: editingBreakMinutes.value !== '' ? Number(editingBreakMinutes.value) : null,
        color: editingColor.value,
        order: editingOrder.value !== '' ? Number(editingOrder.value) : 0,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.error ?? `HTTP ${res.status}`);
    }
    cancelEdit();
    await fetchWorkShiftTypes();
  } catch (e) {
    errorMessage.value = `更新に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

const handleDelete = async (id: number) => {
  if (!window.confirm('この勤務タイプを削除しますか？（既に保存済みのシフトの表示文字列自体は変わりません。今後の入力候補から消えるだけです）')) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/work-shift-types/${id}/`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await fetchWorkShiftTypes();
  } catch (e) {
    errorMessage.value = `削除に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

onMounted(fetchAll);
</script>

<template>
  <div class="crud-root">
    <h2 class="crud-title">勤務タイプ管理</h2>

    <div class="group-row">
      <label class="group-label">グループ</label>
      <select class="select-input" disabled>
        <option>{{ groupName }}</option>
      </select>
    </div>

    <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>

    <div v-if="isLoading" class="loading">読み込み中...</div>

    <template v-else>
      <div class="new-row">
        <input v-model="newName" placeholder="名称（例: 日1）" class="text-input text-input-name" @keyup.enter="handleCreate" />
        <input v-model="newOrder" type="number" placeholder="並び順" class="text-input text-input-order" />
        <input v-model="newStartTime" type="time" class="time-input" title="開始時間" />
        <label class="overnight-label" title="終了時刻を翌日扱いにする">
          <input v-model="newIsOvernight" type="checkbox" />翌
        </label>
        <input v-model="newEndTime" type="time" class="time-input" title="終了時間" />
        <input v-model="newBreakMinutes" type="number" min="0" placeholder="休憩(分)" class="text-input text-input-break" />
        <div class="palette">
          <button
            v-for="c in WORK_SHIFT_TYPE_COLOR_PALETTE"
            :key="c"
            type="button"
            class="swatch"
            :class="{ 'swatch-selected': newColor === c }"
            :style="{ backgroundColor: c }"
            :title="c"
            @click="newColor = c"
          ></button>
        </div>
        <button class="btn-primary" @click="handleCreate">追加</button>
      </div>

      <table class="crud-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>並び順</th>
            <th>開始時間</th>
            <th>翌</th>
            <th>終了時間</th>
            <th>休憩(分)</th>
            <th>シフト上の色</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in workShiftTypes" :key="w.id">
            <td>
              <input v-if="editingId === w.id" v-model="editingName" class="text-input text-input-name" @keyup.enter="handleUpdate(w.id)" />
              <span v-else>{{ w.name }}</span>
            </td>
            <td>
              <input v-if="editingId === w.id" v-model="editingOrder" type="number" class="text-input text-input-order" />
              <span v-else>{{ w.order }}</span>
            </td>
            <td>
              <input v-if="editingId === w.id" v-model="editingStartTime" type="time" class="time-input" />
              <span v-else>{{ w.start_time ?? '-' }}</span>
            </td>
            <td>
              <input v-if="editingId === w.id" v-model="editingIsOvernight" type="checkbox" />
              <span v-else>{{ w.is_overnight ? '翌' : '-' }}</span>
            </td>
            <td>
              <input v-if="editingId === w.id" v-model="editingEndTime" type="time" class="time-input" />
              <span v-else>{{ w.end_time ?? '-' }}</span>
            </td>
            <td>
              <input v-if="editingId === w.id" v-model="editingBreakMinutes" type="number" min="0" class="text-input text-input-break" />
              <span v-else>{{ w.break_minutes ?? '-' }}</span>
            </td>
            <td>
              <div v-if="editingId === w.id" class="palette">
                <button
                  v-for="c in WORK_SHIFT_TYPE_COLOR_PALETTE"
                  :key="c"
                  type="button"
                  class="swatch"
                  :class="{ 'swatch-selected': editingColor === c }"
                  :style="{ backgroundColor: c }"
                  :title="c"
                  @click="editingColor = c"
                ></button>
              </div>
              <span v-else class="swatch swatch-display" :style="{ backgroundColor: w.color }"></span>
            </td>
            <td class="actions">
              <template v-if="editingId === w.id">
                <button class="btn-small btn-primary" @click="handleUpdate(w.id)">保存</button>
                <button class="btn-small" @click="cancelEdit">取消</button>
              </template>
              <template v-else>
                <button class="btn-small" @click="startEdit(w)">編集</button>
                <button class="btn-small btn-danger" @click="handleDelete(w.id)">削除</button>
              </template>
            </td>
          </tr>
          <tr v-if="workShiftTypes.length === 0"><td colspan="8" class="empty-row">勤務タイプがまだ登録されていません</td></tr>
        </tbody>
      </table>
    </template>
  </div>
</template>

<style scoped>
.crud-root { padding: 24px; max-width: 900px; }
.crud-title { font-size: 18px; font-weight: 700; color: #111827; margin-bottom: 16px; }
.group-row { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.group-label { font-size: 13px; color: #6b7280; }
.error-banner { margin-bottom: 12px; padding: 10px 14px; border: 1px solid #fca5a5; background: #fef2f2; color: #b91c1c; border-radius: 6px; font-size: 13px; }
.new-row { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.text-input { padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }
.text-input-name { width: 110px; }
.text-input-order { width: 70px; }
.text-input-break { width: 90px; }
.time-input { padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }
.select-input { padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; background: #f3f4f6; color: #6b7280; }
.overnight-label { display: flex; align-items: center; gap: 4px; font-size: 13px; color: #374151; white-space: nowrap; }
.loading { color: #6b7280; font-size: 14px; }
.crud-table { width: 100%; border-collapse: collapse; background: #fff; }
.crud-table th, .crud-table td { border: 1px solid #e5e7eb; padding: 8px 12px; font-size: 14px; text-align: left; }
.crud-table th { background: #f9fafb; }
.actions { display: flex; gap: 6px; white-space: nowrap; }
.empty-row { text-align: center; color: #9ca3af; }
.btn-primary { padding: 6px 16px; background: #2f6fb0; color: #fff; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }
.btn-small { padding: 4px 10px; border: 1px solid #d1d5db; background: #fff; border-radius: 4px; font-size: 12px; cursor: pointer; }
.btn-small.btn-primary { background: #2f6fb0; color: #fff; border-color: transparent; }
.btn-danger { color: #dc2626; border-color: #fca5a5; }
.palette { display: flex; gap: 4px; flex-wrap: wrap; }
.swatch {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
}
.swatch-selected { border-color: #111827; }
.swatch-display { cursor: default; display: inline-block; }
</style>
