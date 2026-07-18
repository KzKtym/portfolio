<script setup lang="ts">
// SpotWorkerCrud.vue
// スポットワーカーの簡易CRUD画面。フィールドは name のみ。
// サイドメニュー「デモ用データ」→「スポット」からアクセスする。
import { onMounted, ref } from 'vue';
import type { SpotWorkerRecord } from '../types/shift';
import { apiFetch } from '../lib/api';

const workers = ref<SpotWorkerRecord[]>([]);
const isLoading = ref(true);
const errorMessage = ref('');

const newName = ref('');
const editingId = ref<number | null>(null);
const editingName = ref('');

const fetchWorkers = async () => {
  isLoading.value = true;
  errorMessage.value = '';
  try {
    const res = await fetch('/shift/api/v1/spot-workers/');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    workers.value = body.spot_workers;
  } catch (e) {
    errorMessage.value = `一覧の取得に失敗しました: ${e instanceof Error ? e.message : e}`;
  } finally {
    isLoading.value = false;
  }
};

const handleCreate = async () => {
  if (!newName.value.trim()) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch('/shift/api/v1/spot-workers/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName.value.trim() }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    newName.value = '';
    await fetchWorkers();
  } catch (e) {
    errorMessage.value = `作成に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

const startEdit = (w: SpotWorkerRecord) => {
  editingId.value = w.id;
  editingName.value = w.name;
};

const cancelEdit = () => {
  editingId.value = null;
  editingName.value = '';
};

const handleUpdate = async (id: number) => {
  if (!editingName.value.trim()) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/spot-workers/${id}/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: editingName.value.trim() }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    cancelEdit();
    await fetchWorkers();
  } catch (e) {
    errorMessage.value = `更新に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

const handleDelete = async (id: number) => {
  if (!window.confirm('このスポットワーカーを削除しますか？')) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/spot-workers/${id}/`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await fetchWorkers();
  } catch (e) {
    errorMessage.value = `削除に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

onMounted(fetchWorkers);
</script>

<template>
  <div class="crud-root">
    <h2 class="crud-title">スポットワーカー管理</h2>

    <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>

    <div class="new-row">
      <input v-model="newName" placeholder="新規スポットワーカー名" class="text-input" @keyup.enter="handleCreate" />
      <button class="btn-primary" @click="handleCreate">追加</button>
    </div>

    <div v-if="isLoading" class="loading">読み込み中...</div>

    <table v-else class="crud-table">
      <thead>
        <tr><th>ID</th><th>名前</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="w in workers" :key="w.id">
          <td>{{ w.id }}</td>
          <td>
            <input v-if="editingId === w.id" v-model="editingName" class="text-input" @keyup.enter="handleUpdate(w.id)" />
            <span v-else>{{ w.name }}</span>
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
        <tr v-if="workers.length === 0"><td colspan="3" class="empty-row">スポットワーカーがまだいません</td></tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.crud-root { padding: 24px; max-width: 640px; }
.crud-title { font-size: 18px; font-weight: 700; color: #111827; margin-bottom: 16px; }
.error-banner { margin-bottom: 12px; padding: 10px 14px; border: 1px solid #fca5a5; background: #fef2f2; color: #b91c1c; border-radius: 6px; font-size: 13px; }
.new-row { display: flex; gap: 8px; margin-bottom: 16px; }
.text-input { flex: 1; padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }
.loading { color: #6b7280; font-size: 14px; }
.crud-table { width: 100%; border-collapse: collapse; background: #fff; }
.crud-table th, .crud-table td { border: 1px solid #e5e7eb; padding: 8px 12px; font-size: 14px; text-align: left; }
.crud-table th { background: #f9fafb; }
.actions { display: flex; gap: 6px; }
.empty-row { text-align: center; color: #9ca3af; }
.btn-primary { padding: 6px 16px; background: #2f6fb0; color: #fff; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }
.btn-small { padding: 4px 10px; border: 1px solid #d1d5db; background: #fff; border-radius: 4px; font-size: 12px; cursor: pointer; }
.btn-small.btn-primary { background: #2f6fb0; color: #fff; border-color: transparent; }
.btn-danger { color: #dc2626; border-color: #fca5a5; }
</style>
