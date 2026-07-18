<script setup lang="ts">
// AddMemberModal.vue
// 「メンバーを追加＋」のサブ画面（モーダル）。3タブ構成。
// 「職員」「スポット（指名）」タブはチェックボックスによる複数選択＋「追加」ボタンで一括登録する
// （クリック即時追加は廃止）。選択後の登録は、既存の1件登録APIを選択件数分ループして呼び出す。
// 一覧には、表示中の「チーム＋年月」で現在有効な所属を持つメンバー（＝既に追加済み）は表示しない。
import { computed, onMounted, ref } from 'vue';
import type { SpotWorkerRecord, StaffRecord } from '../types/shift';
import { MEMBER_KIND_SPOT_WORKER, MEMBER_KIND_STAFF } from '../types/shift';
import { apiFetch } from '../lib/api';

interface Props {
  teamId: number;
  yearMonth: string;
}
const props = defineProps<Props>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'added'): void; // 追加成功時（1件でも成功すれば発火）。親はsnapshotを再取得する
}>();

type TabId = 'staff' | 'spot_named' | 'spot_recruit';
const activeTab = ref<TabId>('staff');

const staffs = ref<StaffRecord[]>([]);
const spotWorkers = ref<SpotWorkerRecord[]>([]);
const isLoading = ref(true);
const errorMessage = ref('');
const isSubmitting = ref(false);
const recruitCount = ref(1);

// チェックボックスでの選択状態（タブごとに独立して保持）
const selectedStaffIds = ref<Set<number>>(new Set());
const selectedSpotWorkerIds = ref<Set<number>>(new Set());

const toggleStaffSelection = (id: number) => {
  const next = new Set(selectedStaffIds.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  selectedStaffIds.value = next;
};

const toggleSpotWorkerSelection = (id: number) => {
  const next = new Set(selectedSpotWorkerIds.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  selectedSpotWorkerIds.value = next;
};

const staffSelectedCount = computed(() => selectedStaffIds.value.size);
const spotWorkerSelectedCount = computed(() => selectedSpotWorkerIds.value.size);

const fetchOptions = async () => {
  isLoading.value = true;
  errorMessage.value = '';
  try {
    // exclude_active_team / year_month を付与すると、表示中の「チーム＋年月」に現在有効な
    // 所属を持つメンバーはサーバー側で除外される（既に追加済みのメンバーを一覧に出さないため）。
    const staffQuery = `/shift/api/v1/staffs/?exclude_active_team=${props.teamId}&year_month=${props.yearMonth}`;
    const spotQuery = `/shift/api/v1/spot-workers/?exclude_active_team=${props.teamId}&year_month=${props.yearMonth}`;
    const [staffRes, spotRes] = await Promise.all([
      fetch(staffQuery),
      fetch(spotQuery),
    ]);
    if (!staffRes.ok) throw new Error(`staffs HTTP ${staffRes.status}`);
    if (!spotRes.ok) throw new Error(`spot-workers HTTP ${spotRes.status}`);
    staffs.value = (await staffRes.json()).staffs;
    spotWorkers.value = (await spotRes.json()).spot_workers;
    // 一覧の入れ替えに伴い、既存の選択状態は破棄する（存在しないIDが残らないようにするため）
    selectedStaffIds.value = new Set();
    selectedSpotWorkerIds.value = new Set();
  } catch (e) {
    errorMessage.value = `一覧の取得に失敗しました: ${e instanceof Error ? e.message : e}`;
  } finally {
    isLoading.value = false;
  }
};

const postMembership = async (memberKind: number, memberId: number): Promise<void> => {
  const res = await apiFetch('/shift/api/v1/team-memberships/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ team_id: props.teamId, member_kind: memberKind, member_id: memberId }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
};

// チェック済みメンバーをまとめて登録する。既存の1件登録APIを選択件数分ループしてPOSTする
// （新規の一括登録APIは追加しない方針）。全件並行実行し、1件でも失敗があればエラー表示のうえ
// モーダルは閉じずに一覧を再取得する（成功分は登録済みのまま。失敗分だけ選び直せるようにする）。
const submitSelection = async (memberKind: number, ids: number[]) => {
  if (ids.length === 0) return;
  isSubmitting.value = true;
  errorMessage.value = '';
  try {
    const results = await Promise.allSettled(ids.map((id) => postMembership(memberKind, id)));
    const failedCount = results.filter((r) => r.status === 'rejected').length;

    emit('added'); // 1件でも成功していればsnapshotを再取得させる

    if (failedCount > 0) {
      errorMessage.value = `${failedCount}件の追加に失敗しました（成功した分は登録済みです。一覧を更新しました）`;
      await fetchOptions(); // 成功済みのメンバーを一覧から除外し、選択状態もリセットする
    } else {
      emit('close');
    }
  } finally {
    isSubmitting.value = false;
  }
};

const submitStaffSelection = () => submitSelection(MEMBER_KIND_STAFF, Array.from(selectedStaffIds.value));
const submitSpotWorkerSelection = () => submitSelection(MEMBER_KIND_SPOT_WORKER, Array.from(selectedSpotWorkerIds.value));

const addRecruitmentSlots = async () => {
  if (recruitCount.value <= 0) return;
  isSubmitting.value = true;
  errorMessage.value = '';
  try {
    const res = await apiFetch('/shift/api/v1/team-memberships/recruitment-slots/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team_id: props.teamId, year_month: props.yearMonth, count: recruitCount.value }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    emit('added');
    emit('close');
  } catch (e) {
    errorMessage.value = `追加に失敗しました: ${e instanceof Error ? e.message : e}`;
  } finally {
    isSubmitting.value = false;
  }
};

onMounted(fetchOptions);
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-panel">
      <div class="modal-header">
        <h3 class="modal-title">メンバーを追加</h3>
        <button class="modal-close" @click="emit('close')">×</button>
      </div>

      <div class="tabs">
        <button class="tab" :class="{ 'tab-active': activeTab === 'staff' }" @click="activeTab = 'staff'">職員</button>
        <button class="tab" :class="{ 'tab-active': activeTab === 'spot_named' }" @click="activeTab = 'spot_named'">スポット（指名）</button>
        <button class="tab" :class="{ 'tab-active': activeTab === 'spot_recruit' }" @click="activeTab = 'spot_recruit'">スポット（募集）</button>
      </div>

      <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>
      <div v-if="isLoading" class="loading">読み込み中...</div>

      <div v-else class="tab-content">
        <!-- 職員タブ: 既にこのチーム・年月に追加済みの職員は一覧から除外済み。チェック＋一括追加 -->
        <div v-if="activeTab === 'staff'" class="option-list">
          <div v-if="staffs.length === 0" class="empty-hint">追加できる職員がいません（全員追加済み、または未登録です）</div>
          <label v-for="s in staffs" :key="s.id" class="option-item option-item-checkbox">
            <input
              type="checkbox"
              :checked="selectedStaffIds.has(s.id)"
              :disabled="isSubmitting"
              @change="toggleStaffSelection(s.id)"
            />
            <span>{{ s.name }}</span>
          </label>
          <div v-if="staffs.length > 0" class="tab-footer">
            <button
              class="btn-primary"
              :disabled="isSubmitting || staffSelectedCount === 0"
              @click="submitStaffSelection"
            >
              追加（{{ staffSelectedCount }}件選択中）
            </button>
          </div>
        </div>

        <!-- スポット（指名）タブ: 既にこのチーム・年月に追加済みの人は一覧から除外済み。チェック＋一括追加 -->
        <div v-else-if="activeTab === 'spot_named'" class="option-list">
          <div v-if="spotWorkers.length === 0" class="empty-hint">
            追加できるスポットワーカーがいません（全員追加済み、または未登録です。サイドメニュー
            「デモ用データ」→「スポット」から登録できます）
          </div>
          <label v-for="w in spotWorkers" :key="w.id" class="option-item option-item-checkbox">
            <input
              type="checkbox"
              :checked="selectedSpotWorkerIds.has(w.id)"
              :disabled="isSubmitting"
              @change="toggleSpotWorkerSelection(w.id)"
            />
            <span>{{ w.name }}</span>
          </label>
          <div v-if="spotWorkers.length > 0" class="tab-footer">
            <button
              class="btn-primary"
              :disabled="isSubmitting || spotWorkerSelectedCount === 0"
              @click="submitSpotWorkerSelection"
            >
              追加（{{ spotWorkerSelectedCount }}件選択中）
            </button>
          </div>
        </div>

        <!-- スポット（募集）タブ: 人数のみ入力 -->
        <div v-else class="recruit-form">
          <label class="recruit-label">
            募集人数
            <input v-model.number="recruitCount" type="number" min="1" class="recruit-input" />
          </label>
          <button class="btn-primary" :disabled="isSubmitting" @click="addRecruitmentSlots">
            この人数分を追加
          </button>
          <p class="recruit-hint">「Spot募集1」のように、仮称＋連番でシートに追加されます。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-panel {
  width: 420px;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #e5e7eb;
}
.modal-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}
.modal-close {
  border: none;
  background: transparent;
  font-size: 18px;
  color: #6b7280;
  cursor: pointer;
  line-height: 1;
}
.tabs {
  display: flex;
  border-bottom: 1px solid #e5e7eb;
}
.tab {
  flex: 1;
  padding: 10px 4px;
  font-size: 13px;
  border: none;
  background: #f9fafb;
  color: #6b7280;
  cursor: pointer;
}
.tab-active {
  background: #ffffff;
  color: #ea580c;
  font-weight: 700;
  box-shadow: inset 0 -2px 0 #ea580c;
}
.error-banner {
  margin: 10px 16px 0;
  padding: 8px 12px;
  border: 1px solid #fca5a5;
  background: #fef2f2;
  color: #b91c1c;
  border-radius: 6px;
  font-size: 12px;
}
.loading {
  padding: 24px 16px;
  color: #6b7280;
  font-size: 13px;
}
.tab-content {
  padding: 8px;
  overflow-y: auto;
}
.option-list {
  display: flex;
  flex-direction: column;
}
.option-item {
  text-align: left;
  padding: 10px 12px;
  border: none;
  background: transparent;
  font-size: 14px;
  color: #374151;
  cursor: pointer;
  border-radius: 4px;
}
.option-item:hover {
  background: #f3f4f6;
}
.option-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.option-item-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
}
.option-item-checkbox input[type='checkbox'] {
  cursor: pointer;
}
.tab-footer {
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid #e5e7eb;
}
.empty-hint {
  padding: 16px 12px;
  font-size: 12px;
  color: #9ca3af;
}
.recruit-form {
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.recruit-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #374151;
}
.recruit-input {
  width: 80px;
  padding: 6px 8px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 14px;
}
.recruit-hint {
  margin: 0;
  font-size: 12px;
  color: #9ca3af;
}
.btn-primary {
  align-self: flex-start;
  padding: 8px 18px;
  background: #2f6fb0;
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}
.btn-primary:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
</style>
