<script setup lang="ts">
// Sidebar.vue
// 左サイドメニュー。vue-routerは使わず、選択中の画面IDをemitで親(App.vue)へ伝える。
export type ScreenId = 'shift' | 'groupe' | 'staff' | 'spotworker' | 'workshifttype';

interface Props {
  activeScreen: ScreenId;
}
defineProps<Props>();

const emit = defineEmits<{
  (e: 'navigate', screen: ScreenId): void;
}>();

// Djangoのトップページ（アプリ一覧）へ戻るリンク。
// {% url %} 等のDjangoテンプレート構文はこの.vueファイル（Vite/Vueがビルドする）では
// 一切解釈されないため使えない。また本番でもspa_views.spa_indexはビルド済みindex.htmlを
// そのまま返すだけでDjangoのテンプレートエンジンを通していないため、同様に機能しない。
// そのため固定パス "/home/" を直書きする（TEAM_ID等、既存コードと同じ流儀）。
// ただし開発時（vite devサーバー、:5173）は <a> によるフルナビゲーションがViteのproxy対象外
// (server.proxyはfetch等のXHRのみ中継)のため、"/home/" のままだと :5173/home/ に飛んで404になる。
// import.meta.env.DEV（Viteが自動提供。追加設定不要）で判定し、開発時のみDjangoの絶対URLに切り替える。
const homeUrl = import.meta.env.DEV ? 'http://localhost:8000/home/' : '/home/';
</script>

<template>
  <nav class="sidebar">
    <div class="brand">勤務シフト<span style="color:#999;">PoC</span></div>

    <div class="menu-section">
      <div class="menu-label">シフト管理</div>
      <button
        class="menu-link"
        :class="{ 'menu-link-active': activeScreen === 'shift' }"
        @click="emit('navigate', 'shift')"
      >
        シフト作成
      </button>
    </div>

    <div class="menu-section">
      <div class="menu-label">マスタ管理</div>
      <span class="menu-inactive">法人</span>
      <button
        class="menu-link"
        :class="{ 'menu-link-active': activeScreen === 'groupe' }"
        @click="emit('navigate', 'groupe')"
      >
        グループ
      </button>
      <span class="menu-inactive">管理者</span>
      <button
        class="menu-link"
        :class="{ 'menu-link-active': activeScreen === 'staff' }"
        @click="emit('navigate', 'staff')"
      >
        職員
      </button>
    </div>

    <div class="menu-section">
      <div class="menu-label">デモ用管理</div>
      <button
        class="menu-link"
        :class="{ 'menu-link-active': activeScreen === 'spotworker' }"
        @click="emit('navigate', 'spotworker')"
      >
        スポット
      </button>
      <button
        class="menu-link"
        :class="{ 'menu-link-active': activeScreen === 'workshifttype' }"
        @click="emit('navigate', 'workshifttype')"
      >
        勤務タイプ
      </button>
      <a class="menu-link menu-link-home" :href="homeUrl">&lt;Home&gt;</a>
    </div>
  </nav>
</template>

<style scoped>
.sidebar {
  width: 150px;
  flex-shrink: 0;
  background: #ffffff;
  border-right: 1px solid #e5e7eb;
  min-height: 100vh;
  padding: 16px 0;
}
.brand {
  font-size: 16px;
  font-weight: 700;
  color: #ea580c;
  padding: 0 16px 20px;
}
.menu-section {
  padding: 10px 0 16px;
  border-bottom: 1px solid #f3f4f6;
}
.menu-label {
  font-size: 12px;
  color: #9ca3af;
  padding: 4px 16px;
}
.menu-link {
  display: block;
  width: 100%;
  text-align: left;
  padding: 8px 16px 8px 28px;
  border: none;
  background: transparent;
  font-size: 14px;
  color: #374151;
  cursor: pointer;
}
.menu-link:hover {
  background: #f9fafb;
}
.menu-link-active {
  background: #fff7ed;
  color: #ea580c;
  font-weight: 600;
  border-left: 3px solid #ea580c;
  padding-left: 25px;
}
.menu-link-home {
  text-decoration: none;
  box-sizing: border-box;
}
/* 「法人」「管理者」: リンクではなく単なるラベル。クリック不可・カーソルも変化させない */
.menu-inactive {
  display: block;
  padding: 8px 16px 8px 28px;
  font-size: 14px;
  color: #d1d5db;
  cursor: default;
  user-select: none;
}
</style>
