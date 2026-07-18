<script setup lang="ts">
// GroupeCrud.vue
// グループの簡易CRUD画面。フィールドは name のみ。
import { onMounted, ref } from 'vue';
import type { GroupeRecord } from '../types/shift';
import { apiFetch } from '../lib/api';

const groupes = ref<GroupeRecord[]>([]);
const isLoading = ref(true);
const errorMessage = ref('');

const newName = ref('');
const editingId = ref<number | null>(null);
const editingName = ref('');

const fetchGroupes = async () => {
  isLoading.value = true;
  errorMessage.value = '';
  try {
    const res = await fetch('/shift/api/v1/groupes/');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    groupes.value = body.groupes;
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
    const res = await apiFetch('/shift/api/v1/groupes/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName.value.trim() }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    newName.value = '';
    await fetchGroupes();
  } catch (e) {
    errorMessage.value = `作成に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

const startEdit = (g: GroupeRecord) => {
  editingId.value = g.id;
  editingName.value = g.name;
};

const cancelEdit = () => {
  editingId.value = null;
  editingName.value = '';
};

const handleUpdate = async (id: number) => {
  if (!editingName.value.trim()) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/groupes/${id}/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: editingName.value.trim() }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    cancelEdit();
    await fetchGroupes();
  } catch (e) {
    errorMessage.value = `更新に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

const handleDelete = async (id: number) => {
  if (!window.confirm('このグループを削除しますか？')) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/groupes/${id}/`, { method: 'DELETE' });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.error ?? `HTTP ${res.status}`);
    }
    await fetchGroupes();
  } catch (e) {
    errorMessage.value = `${e instanceof Error ? e.message : e}`;
  }
};

onMounted(fetchGroupes);
</script>

<template>
  <div class="crud-root">
    <h2 class="crud-title">グループ管理</h2>

    <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>

    <div class="new-row">
      <input v-model="newName" placeholder="新規グループ名" class="text-input" @keyup.enter="handleCreate" />
      <button class="btn-primary" @click="handleCreate">追加</button>
    </div>

    <div v-if="isLoading" class="loading">読み込み中...</div>

    <table v-else class="crud-table">
      <thead>
        <tr><th>ID</th><th>名前</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="g in groupes" :key="g.id">
          <td>{{ g.id }}</td>
          <td>
            <input v-if="editingId === g.id" v-model="editingName" class="text-input" @keyup.enter="handleUpdate(g.id)" />
            <span v-else>{{ g.name }}</span>
          </td>
          <td class="actions">
            <template v-if="editingId === g.id">
              <button class="btn-small btn-primary" @click="handleUpdate(g.id)">保存</button>
              <button class="btn-small" @click="cancelEdit">取消</button>
            </template>
            <template v-else>
              <button class="btn-small" @click="startEdit(g)">編集</button>
              <button class="btn-small btn-danger" @click="handleDelete(g.id)">削除</button>
            </template>
          </td>
        </tr>
        <tr v-if="groupes.length === 0"><td colspan="3" class="empty-row">グループがまだありません</td></tr>
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
/* .btn-small.btn-primary（編集時の「保存」ボタン）は、.btn-smallの背景が後勝ちして
   白背景×白文字で見えなくなっていたため、組み合わせ用のルールで明示的に上書きする */
.btn-small.btn-primary { background: #2f6fb0; color: #fff; border-color: transparent; }
.btn-danger { color: #dc2626; border-color: #fca5a5; }
</style>
