<script setup lang="ts">
// StaffCrud.vue
// 職員の簡易CRUD画面。default_team はゆるい参照のため、Team一覧から選ばせるが
// バリデーション（存在チェック）は行わない。
import { onMounted, ref } from 'vue';
import type { StaffRecord, TeamRecord } from '../types/shift';
import { apiFetch } from '../lib/api';

const staffs = ref<StaffRecord[]>([]);
const teams = ref<TeamRecord[]>([]);
const isLoading = ref(true);
const errorMessage = ref('');

const newName = ref('');
const newDefaultTeam = ref<string>('');

const editingId = ref<number | null>(null);
const editingName = ref('');
const editingDefaultTeam = ref<string>('');

const teamLabel = (teamId: number | null) => {
  if (teamId === null) return '(未設定)';
  const t = teams.value.find(t => t.id === teamId);
  return t ? t.name : `(不明なチームID: ${teamId})`;
};

const fetchAll = async () => {
  isLoading.value = true;
  errorMessage.value = '';
  try {
    const [staffRes, teamRes] = await Promise.all([
      fetch('/shift/api/v1/staffs/'),
      fetch('/shift/api/v1/teams/'),
    ]);
    if (!staffRes.ok) throw new Error(`staffs HTTP ${staffRes.status}`);
    if (!teamRes.ok) throw new Error(`teams HTTP ${teamRes.status}`);
    staffs.value = (await staffRes.json()).staffs;
    teams.value = (await teamRes.json()).teams;
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
    const res = await apiFetch('/shift/api/v1/staffs/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newName.value.trim(),
        default_team: newDefaultTeam.value ? Number(newDefaultTeam.value) : null,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    newName.value = '';
    newDefaultTeam.value = '';
    await fetchAll();
  } catch (e) {
    errorMessage.value = `作成に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

const startEdit = (s: StaffRecord) => {
  editingId.value = s.id;
  editingName.value = s.name;
  editingDefaultTeam.value = s.default_team !== null ? String(s.default_team) : '';
};

const cancelEdit = () => {
  editingId.value = null;
  editingName.value = '';
  editingDefaultTeam.value = '';
};

const handleUpdate = async (id: number) => {
  if (!editingName.value.trim()) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/staffs/${id}/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: editingName.value.trim(),
        default_team: editingDefaultTeam.value ? Number(editingDefaultTeam.value) : null,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    cancelEdit();
    await fetchAll();
  } catch (e) {
    errorMessage.value = `更新に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

const handleDelete = async (id: number) => {
  if (!window.confirm('この職員を削除しますか？')) return;
  errorMessage.value = '';
  try {
    const res = await apiFetch(`/shift/api/v1/staffs/${id}/`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await fetchAll();
  } catch (e) {
    errorMessage.value = `削除に失敗しました: ${e instanceof Error ? e.message : e}`;
  }
};

onMounted(fetchAll);
</script>

<template>
  <div class="crud-root">
    <h2 class="crud-title">職員管理</h2>

    <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>

    <div class="new-row">
      <input v-model="newName" placeholder="新規職員名" class="text-input" @keyup.enter="handleCreate" />
      <select v-model="newDefaultTeam" class="select-input">
        <option value="">既定チーム: 未設定</option>
        <option v-for="t in teams" :key="t.id" :value="t.id">{{ t.name }}</option>
      </select>
      <button class="btn-primary" @click="handleCreate">追加</button>
    </div>

    <div v-if="isLoading" class="loading">読み込み中...</div>

    <table v-else class="crud-table">
      <thead>
        <tr><th>ID</th><th>名前</th><th>既定チーム（参考値）</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="s in staffs" :key="s.id">
          <td>{{ s.id }}</td>
          <td>
            <input v-if="editingId === s.id" v-model="editingName" class="text-input" @keyup.enter="handleUpdate(s.id)" />
            <span v-else>{{ s.name }}</span>
          </td>
          <td>
            <select v-if="editingId === s.id" v-model="editingDefaultTeam" class="select-input">
              <option value="">未設定</option>
              <option v-for="t in teams" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
            <span v-else>{{ teamLabel(s.default_team) }}</span>
          </td>
          <td class="actions">
            <template v-if="editingId === s.id">
              <button class="btn-small btn-primary" @click="handleUpdate(s.id)">保存</button>
              <button class="btn-small" @click="cancelEdit">取消</button>
            </template>
            <template v-else>
              <button class="btn-small" @click="startEdit(s)">編集</button>
              <button class="btn-small btn-danger" @click="handleDelete(s.id)">削除</button>
            </template>
          </td>
        </tr>
        <tr v-if="staffs.length === 0"><td colspan="4" class="empty-row">職員がまだいません</td></tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.crud-root { padding: 24px; max-width: 760px; }
.crud-title { font-size: 18px; font-weight: 700; color: #111827; margin-bottom: 16px; }
.error-banner { margin-bottom: 12px; padding: 10px 14px; border: 1px solid #fca5a5; background: #fef2f2; color: #b91c1c; border-radius: 6px; font-size: 13px; }
.new-row { display: flex; gap: 8px; margin-bottom: 16px; }
.text-input { flex: 1; padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }
.select-input { padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }
.loading { color: #6b7280; font-size: 14px; }
.crud-table { width: 100%; border-collapse: collapse; background: #fff; }
.crud-table th, .crud-table td { border: 1px solid #e5e7eb; padding: 8px 12px; font-size: 14px; text-align: left; }
.crud-table th { background: #f9fafb; }
.actions { display: flex; gap: 6px; white-space: nowrap; }
.empty-row { text-align: center; color: #9ca3af; }
.btn-primary { padding: 6px 16px; background: #2f6fb0; color: #fff; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }
.btn-small { padding: 4px 10px; border: 1px solid #d1d5db; background: #fff; border-radius: 4px; font-size: 12px; cursor: pointer; }
/* .btn-small.btn-primary（編集時の「保存」ボタン）は、.btn-smallの背景が後勝ちして
   白背景×白文字で見えなくなっていたため、組み合わせ用のルールで明示的に上書きする */
.btn-small.btn-primary { background: #2f6fb0; color: #fff; border-color: transparent; }
.btn-danger { color: #dc2626; border-color: #fca5a5; }
</style>
