<script setup lang="ts">
// EventRow.vue
// 施設イベント/チームイベント行。日付とイベントをマッピングして自動描画する。
// ※チームイベントは今回スコープ外のため、行だけ表示し常に空セルとなる。
import { computed } from 'vue';
import type { DayInfo, EventRecord } from '../types/shift';

interface Props {
  label: string;            // 例: '施設イベント', 'チームイベント'
  days: DayInfo[];
  records: EventRecord[];
  variant?: 'facility' | 'team';
}
const props = withDefaults(defineProps<Props>(), { variant: 'facility' });

// 日付→イベントタイトルのO(1)参照マップ
const titleByDate = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {};
  for (const rec of props.records) {
    map[rec.date] = map[rec.date] ? `${map[rec.date]} / ${rec.title}` : rec.title;
  }
  return map;
});
</script>

<template>
  <tr :class="variant === 'facility' ? 'event-row-facility' : 'event-row-team'">
    <td class="event-label sticky-col">{{ label }}</td>
    <td v-for="day in days" :key="day.date" class="event-cell">
      {{ titleByDate[day.date] || '' }}
    </td>
  </tr>
</template>

<style scoped>
.event-label {
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.event-cell {
  padding: 4px 2px;
  font-size: 11px;
  text-align: center;
  white-space: nowrap;
}
.event-row-facility .event-label,
.event-row-facility .event-cell {
  background: #fffbeb;
  color: #92400e;
}
.event-row-team .event-label,
.event-row-team .event-cell {
  background: #f0f9ff;
  color: #0c4a6e;
}
.sticky-col {
  position: sticky;
  left: 0;
  z-index: 10;
}
</style>
