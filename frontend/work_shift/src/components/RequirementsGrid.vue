<script setup lang="ts">
// RequirementsGrid.vue
// 予定数タブ(F2)のメイン表。勤務タイプマスタ(order順)を行に、日付を列にした
// 編集可能なグリッド。「小計」欄のみを表示し、分母（必要人数）だけを直接入力する
// （現在数/職員の割り当てはこの画面では扱わない。確定仕様）。
//
// セルの値は「未保存の変更差分（案B）」としてメモリ内のみで保持し、保存ボタン押下時に
// ShiftTableContainer.vue 側でまとめてDjangoへ送信する（通常タブF1のシフト保存と同じ考え方）。
import type { DayInfo, WorkShiftTypeRecord } from '../types/shift';

interface Props {
  days: DayInfo[];
  workShiftTypes: WorkShiftTypeRecord[];
  requirements: Record<string, Record<string, number>>;
  // 未保存セルの判定用（キー: `${workShiftTypeId}|${date}`）
  dirtyKeys: Set<string>;
}
const props = defineProps<Props>();

const emit = defineEmits<{
  (e: 'update-cell', payload: { workShiftTypeId: number; date: string; requiredCount: number }): void;
}>();

const JP_DOW: Record<string, string> = {
  MON: '月', TUE: '火', WED: '水', THU: '木', FRI: '金', SAT: '土', SUN: '日',
};
const dayNumber = (date: string) => Number(date.split('-')[2]);
const dowClass = (dow: string) => (dow === 'SUN' ? 'dow-sun' : dow === 'SAT' ? 'dow-sat' : '');

const cellValue = (name: string, date: string) => props.requirements[name]?.[date] ?? 0;

const isDirty = (workShiftTypeId: number, date: string) =>
  props.dirtyKeys.has(`${workShiftTypeId}|${date}`);

const onChange = (workShiftTypeId: number, date: string, event: Event) => {
  const target = event.target as HTMLInputElement;
  const raw = target.value.trim();
  const requiredCount = raw === '' ? 0 : Math.max(0, Math.floor(Number(raw)));
  emit('update-cell', { workShiftTypeId, date, requiredCount });
};
</script>

<template>
  <div class="requirements-scroll">
    <table class="requirements-table">
      <thead>
        <tr class="day-header-row">
          <th class="corner-cell sticky-col"></th>
          <th
            v-for="day in days"
            :key="day.date"
            class="day-header"
            :class="dowClass(day.day_of_week)"
          >
            {{ dayNumber(day.date) }} {{ JP_DOW[day.day_of_week] }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(t, idx) in workShiftTypes" :key="t.id" class="requirement-row">
          <td class="requirement-label sticky-col">
            <span v-if="idx === 0" class="subtotal-caption">小計</span>
            <span class="type-name">{{ t.name }}</span>
          </td>
          <td
            v-for="day in days"
            :key="day.date"
            class="requirement-cell"
            :class="{ 'requirement-cell-dirty': isDirty(t.id, day.date) }"
          >
            <input
              type="number"
              min="0"
              step="1"
              class="requirement-input"
              :value="cellValue(t.name, day.date)"
              @change="onChange(t.id, day.date, $event)"
            />
          </td>
        </tr>
        <tr v-if="workShiftTypes.length === 0">
          <td class="empty-row" :colspan="days.length + 1">勤務タイプが登録されていません（サイドメニュー「デモ用管理」→「勤務タイプ」から登録できます）</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.requirements-scroll {
  margin: 12px 16px;
  overflow-x: auto;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}
.requirements-table {
  border-collapse: collapse;
  width: 100%;
}
.corner-cell {
  background: #f9fafb;
  width: 140px;
  min-width: 140px;
}
.sticky-col {
  position: sticky;
  left: 0;
  z-index: 10;
  background: #ffffff;
}
.day-header-row .sticky-col {
  background: #f9fafb;
}
.day-header {
  padding: 6px 4px;
  font-size: 12px;
  font-weight: 600;
  color: #374151;
  background: #f9fafb;
  border-bottom: 1px solid #e5e7eb;
  min-width: 52px;
  text-align: center;
}
.dow-sat { color: #2563eb; }
.dow-sun { color: #dc2626; }
.requirement-row:nth-child(even) {
  background: #fafafa;
}
.requirement-label {
  padding: 6px 10px;
  font-size: 13px;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 2px 0 5px -2px rgba(0, 0, 0, 0.1);
}
.subtotal-caption {
  font-weight: 700;
  color: #374151;
}
.type-name {
  color: #4b5563;
  font-weight: 600;
  margin-left: auto;
}
.requirement-cell {
  padding: 2px;
  text-align: center;
}
.requirement-cell-dirty {
  outline: 2px solid #f59e0b;
  outline-offset: -2px;
}
.requirement-input {
  width: 100%;
  min-width: 52px;
  padding: 4px 6px;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  background: #ffffff;
  color: #111827;
}
.empty-row {
  text-align: center;
  color: #9ca3af;
  padding: 24px;
}
</style>
