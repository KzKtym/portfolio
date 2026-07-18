<script setup lang="ts">
// MemberRow.vue (旧 StaffRow.vue から改称)
// メンバー（職員/スポットワーカー/募集枠のいずれも）1行分。
// コンポーネントを軽量化し、1セルの変更時に他メンバーの不要な再レンダリングを防ぐ。
//
// 左端に「＝」（ドラッグで並び替え）「×」（このシートからシフト実績を論理削除）を表示する。
// アイコンは全角文字をそのまま使う（ライブラリ追加なし、確定仕様）。
//
// シフトセルは、ネイティブの<select>ではなく自作のポップアップパネルで実装する（確定仕様）。
// 閉じたセルには名称のみ（時刻なし）を中央寄せで表示し、クリックすると勤務タイプごとに
// 色分けされた選択パネルが開く（各行に「名称 開始-終了」を表示。「休」等は時刻なし）。
//
// 既知の制約: パネルはセル直下に絶対配置しているだけのため、表の横スクロール領域
// （ShiftTableContainer.vue の .table-scroll、overflow-x: auto）の右端に近いセルで
// クリックすると、パネルの一部が見切れる場合がある。将来的な改善候補（9節「今後の課題」）。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import type { DayInfo, MemberShift, WorkShiftTypeRecord } from '../types/shift';
import { formatWorkShiftTypeLabel } from '../types/shift';

interface Props {
  member: MemberShift;
  days: DayInfo[];
  // 未保存セルの判定用（キー: `${memberId}|${date}`）
  dirtyKeys: Set<string>;
  isDragOver: boolean;
  workShiftTypes: WorkShiftTypeRecord[]; // 勤務タイプマスタ（パネル候補・色分けの元データ）
}
const props = defineProps<Props>();

const emit = defineEmits<{
  (e: 'update-cell', payload: { memberId: number; date: string; shiftType: string }): void;
  (e: 'delete-member', membershipId: number | null): void;
  (e: 'drag-start', memberId: number): void;
  (e: 'drag-over', memberId: number): void;
  (e: 'drop', memberId: number): void;
  (e: 'drag-end'): void;
}>();

const colorByName = computed(() => {
  const map: Record<string, string> = {};
  for (const w of props.workShiftTypes) map[w.name] = w.color;
  return map;
});

// 1行内で同時に開くパネルは1つだけ。開いている日付をrefで管理する
const openDate = ref<string | null>(null);

const displayStyle = (shiftType: string | undefined) => {
  if (!shiftType) return {};
  const color = colorByName.value[shiftType];
  if (!color) return {};
  return { backgroundColor: color, color: '#ffffff' };
};

const isDirty = (date: string) =>
  props.dirtyKeys.has(`${props.member.member_id}|${date}`);

const togglePanel = (date: string) => {
  openDate.value = openDate.value === date ? null : date;
};

const closePanel = () => {
  openDate.value = null;
};

const selectShiftType = (date: string, shiftType: string) => {
  emit('update-cell', { memberId: props.member.member_id, date, shiftType });
  closePanel();
};

// パネル外クリックで閉じる。パネル内・トグルボタンのクリックは@click.stopで
// document まで伝播しないため、ここに届く時点で「外クリック」であると判断できる
const onDocumentClick = () => {
  if (openDate.value !== null) closePanel();
};
const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') closePanel();
};
onMounted(() => {
  document.addEventListener('click', onDocumentClick);
  document.addEventListener('keydown', onKeydown);
});
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick);
  document.removeEventListener('keydown', onKeydown);
});

const onDragStart = (event: DragEvent) => {
  event.dataTransfer?.setData('text/plain', String(props.member.member_id));
  emit('drag-start', props.member.member_id);
};
const onDragOver = (event: DragEvent) => {
  event.preventDefault(); // dropを許可するために必須
  emit('drag-over', props.member.member_id);
};
const onDrop = (event: DragEvent) => {
  event.preventDefault();
  emit('drop', props.member.member_id);
};
</script>

<template>
  <tr
    class="member-row"
    :class="{ 'member-row-drag-over': isDragOver }"
    @dragover="onDragOver"
    @drop="onDrop"
  >
    <td class="member-name sticky-col">
      <span
        class="drag-handle"
        draggable="true"
        title="ドラッグで並び替え"
        @dragstart="onDragStart"
        @dragend="emit('drag-end')"
      >＝</span>
      <button
        class="delete-handle"
        title="このシートから削除"
        @click="emit('delete-member', member.membership_id)"
      >×</button>
      <span class="member-name-text">{{ member.member_name }}</span>
    </td>
    <td
      v-for="day in days"
      :key="day.date"
      class="shift-cell"
      :class="{ 'shift-cell-dirty': isDirty(day.date) }"
    >
      <div class="shift-cell-wrapper">
        <button
          type="button"
          class="shift-display"
          :style="displayStyle(member.shifts[day.date])"
          @click.stop="togglePanel(day.date)"
        >{{ member.shifts[day.date] || '-' }}</button>

        <div v-if="openDate === day.date" class="shift-popup" @click.stop>
          <button
            type="button"
            class="shift-popup-row shift-popup-row-clear"
            @click="selectShiftType(day.date, '')"
          >-</button>
          <button
            v-for="t in workShiftTypes"
            :key="t.id"
            type="button"
            class="shift-popup-row"
            :style="{ backgroundColor: t.color, color: '#ffffff' }"
            @click="selectShiftType(day.date, t.name)"
          >{{ formatWorkShiftTypeLabel(t) }}</button>
        </div>
      </div>
    </td>
  </tr>
</template>

<style scoped>
.member-name {
  padding: 6px 10px;
  font-size: 13px;
  font-weight: 500;
  color: #111827;
  background: #ffffff;
  white-space: nowrap;
  box-shadow: 2px 0 5px -2px rgba(0, 0, 0, 0.1);
  display: flex;
  align-items: center;
  gap: 6px;
}
.drag-handle {
  cursor: grab;
  color: #9ca3af;
  font-weight: 700;
  user-select: none;
  padding: 0 2px;
}
.drag-handle:active {
  cursor: grabbing;
}
.delete-handle {
  border: none;
  background: transparent;
  color: #9ca3af;
  font-weight: 700;
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
}
.delete-handle:hover {
  color: #dc2626;
}
.member-name-text {
  flex: 1;
}
.sticky-col {
  position: sticky;
  left: 0;
  z-index: 10;
}
.shift-cell {
  padding: 2px;
  text-align: center;
}
.shift-cell-dirty {
  outline: 2px solid #f59e0b;
  outline-offset: -2px;
}
.shift-cell-wrapper {
  position: relative;
}
.shift-display {
  width: 100%;
  min-width: 52px;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  background: #ffffff;
  color: #6b7280;
  cursor: pointer;
}
.member-row:hover .shift-cell {
  background: #f9fafb;
}
.member-row-drag-over {
  outline: 2px dashed #2563eb;
  outline-offset: -2px;
}

/* 自作ポップアップパネル（勤務タイプ選択）。ネイティブ<select>は使わない確定仕様のため */
.shift-popup {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 60;
  margin-top: 2px;
  min-width: 150px;
  max-height: 240px;
  overflow-y: auto;
  background: #ffffff;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.18);
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.shift-popup-row {
  display: block;
  width: 100%;
  text-align: left;
  padding: 6px 10px;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.shift-popup-row:hover {
  filter: brightness(0.94);
}
.shift-popup-row-clear {
  background: #f3f4f6;
  color: #6b7280;
}
</style>
