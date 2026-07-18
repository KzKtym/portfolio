<script setup lang="ts">
// TableFooter.vue
// 画面下部の「小計」行。シフト種別ごとに日別の「現在数/予定数」を computed でリアルタイム集計する。
// 予定数(分母)は予定数タブ(F2)で編集された値（shift_type_requirements）を参照する。
// 種別一覧は勤務タイプマスタ（work_shift_types）から。
import { computed } from 'vue';
import type { DayInfo, MemberShift, WorkShiftTypeRecord } from '../types/shift';

interface Props {
  days: DayInfo[];
  memberShifts: MemberShift[];
  requirements: Record<string, Record<string, number>>;
  workShiftTypes: WorkShiftTypeRecord[];
}
const props = defineProps<Props>();

// { [shiftType]: { [date]: currentCount } } をリアルタイム集計
const countsByType = computed(() => {
  const result: Record<string, Record<string, number>> = {};
  for (const t of props.workShiftTypes) result[t.name] = {};
  for (const member of props.memberShifts) {
    for (const [date, shiftType] of Object.entries(member.shifts)) {
      if (result[shiftType]) {
        result[shiftType][date] = (result[shiftType][date] || 0) + 1;
      }
    }
  }
  return result;
});

const requiredCount = (name: string, date: string) => props.requirements[name]?.[date] ?? 0;

const cellClass = (current: number, required: number) => {
  if (current < required) return 'count-short';   // 不足 → 赤
  if (current > required) return 'count-over';    // 超過 → 緑
  return 'count-exact';                           // 一致 → 黒
};
</script>

<template>
  <tfoot>
    <tr v-for="(t, idx) in workShiftTypes" :key="t.id" class="footer-row">
      <td class="footer-label sticky-col">
        <span v-if="idx === 0" class="subtotal-caption">小計</span>
        <span class="type-name">{{ t.name }}</span>
      </td>
      <td
        v-for="day in days"
        :key="day.date"
        class="footer-cell"
        :class="cellClass(countsByType[t.name][day.date] || 0, requiredCount(t.name, day.date))"
      >
        {{ countsByType[t.name][day.date] || 0 }}/{{ requiredCount(t.name, day.date) }}
      </td>
    </tr>
  </tfoot>
</template>

<style scoped>
.footer-row {
  background: #f3f4f6;
}
.footer-label {
  padding: 4px 10px;
  font-size: 12px;
  background: #f3f4f6;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 10px;
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
.sticky-col {
  position: sticky;
  left: 0;
  z-index: 10;
}
.footer-cell {
  padding: 4px 2px;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
}
.count-short { color: #dc2626; }
.count-exact { color: #374151; }
.count-over  { color: #16a34a; }
</style>
