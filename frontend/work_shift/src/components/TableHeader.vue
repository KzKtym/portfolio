<script setup lang="ts">
// TableHeader.vue
// 画面上部のステータスバー（グループ/チーム/最終更新者/最終更新日時/ステータス）と
// 年月切り替え・タブ（通常F1/予定数F2）を担当するコンポーネント。
import { computed } from 'vue';
interface Props {
  groupName: string;
  teamName: string;
  yearMonth: string;          // "YYYY-MM"
  availableYearMonths: string[]; // シフト実績が存在する年月（昇順）。年月プルダウンの候補
  activeTab: 'normal' | 'requirements'; // 通常(F1) / 予定数(F2)
  isDirty: boolean;           // 未保存の変更があるか
  dirtyCount: number;         // 未保存セル数
  lastUpdatedBy: string;
  lastUpdatedAt: string;
  isSaving: boolean;
}
const props = defineProps<Props>();

const emit = defineEmits<{
  (e: 'change-month', delta: number): void;
  (e: 'select-month', yearMonth: string): void;
  (e: 'change-tab', tab: 'normal' | 'requirements'): void;
  (e: 'save'): void;
}>();

const formatYearMonth = (ym: string) => {
  const [y, m] = ym.split('-');
  return `${y}年${Number(m)}月`;
};

const onSelectMonth = (event: Event) => {
  const target = event.target as HTMLSelectElement;
  emit('select-month', target.value);
};

// 矢印(←→)で、実績のない年月へ移動した場合でもプルダウンの選択値が必ず一致するよう、
// 現在の年月が候補一覧になければ一時的に補って表示する
const yearMonthOptions = computed(() => {
  if (props.availableYearMonths.includes(props.yearMonth)) return props.availableYearMonths;
  return [...props.availableYearMonths, props.yearMonth].sort();
});
</script>

<template>
  <div class="header-root">
    <!-- ステータスバー -->
    <div class="status-bar">
      <div class="status-item">
        <span class="status-label">グループ</span>
        <span class="status-value">{{ groupName }}</span>
      </div>
      <div class="status-item">
        <span class="status-label">チーム</span>
        <span class="status-value">{{ teamName }}</span>
      </div>
      <div class="status-item">
        <span class="status-label">最終更新者</span>
        <span class="status-value">{{ lastUpdatedBy }}</span>
      </div>
      <div class="status-item">
        <span class="status-label">最終更新日時</span>
        <span class="status-value">{{ lastUpdatedAt }}</span>
      </div>
      <div class="status-item">
        <span class="status-label">ステータス</span>
        <span class="status-value" :class="{ 'status-editing': isDirty }">
          {{ isDirty ? '編集中' : '保存済み' }}
        </span>
      </div>
      <div class="status-item action-item">
        <button
          class="save-button"
          :disabled="!isDirty || isSaving"
          @click="emit('save')"
        >
          {{ isSaving ? '保存中...' : `保存${dirtyCount > 0 ? ` (${dirtyCount})` : ''}` }}
        </button>
      </div>
    </div>

    <!-- タブ + 年月切り替え -->
    <div class="toolbar">
      <div class="tabs">
        <button
          class="tab"
          :class="{ 'tab-active': activeTab === 'normal' }"
          @click="emit('change-tab', 'normal')"
        >シフト表</button>
        <button
          class="tab"
          :class="{ 'tab-active': activeTab === 'requirements' }"
          @click="emit('change-tab', 'requirements')"
        >予定数</button>
      </div>
      <div class="month-nav">
        <button class="month-arrow" @click="emit('change-month', -1)" aria-label="前月">←</button>
        <select class="month-label month-select" :value="yearMonth" @change="onSelectMonth">
          <option v-for="ym in yearMonthOptions" :key="ym" :value="ym">{{ formatYearMonth(ym) }}</option>
        </select>
        <button class="month-arrow" @click="emit('change-month', 1)" aria-label="翌月">→</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.header-root {
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
}
.status-bar {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 10px 16px;
  border-bottom: 1px solid #e5e7eb;
  flex-wrap: wrap;
}
.status-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.status-label {
  font-size: 11px;
  color: #9ca3af;
}
.status-value {
  font-size: 14px;
  color: #374151;
  font-weight: 500;
}
.status-editing {
  color: #d97706;
}
.action-item {
  margin-left: auto;
}
.save-button {
  padding: 8px 20px;
  background: #2f6fb0;
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}
.save-button:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
.toolbar {
  position: relative;
  display: flex;
  align-items: center;
  padding: 8px 16px;
}
.tabs {
  display: flex;
  gap: 4px;
}
.tab {
  padding: 6px 16px;
  font-size: 13px;
  border: 1px solid #d1d5db;
  border-bottom: none;
  border-radius: 6px 6px 0 0;
  background: #f3f4f6;
  color: #6b7280;
  cursor: pointer;
}
.tab-active {
  background: #ffffff;
  color: #111827;
  font-weight: 600;
  border-color: #9ca3af;
}
.tab:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.month-nav {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  gap: 12px;
}
.month-arrow {
  border: none;
  background: transparent;
  color: #2563eb;
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
}
.month-label {
  font-size: 15px;
  font-weight: 600;
  color: #111827;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 4px 14px;
}
.month-select {
  cursor: pointer;
  background: #ffffff;
}
</style>
