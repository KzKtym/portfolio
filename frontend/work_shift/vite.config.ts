// frontend/work_shift/vite.config.ts
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath, URL } from 'node:url';

// 開発時（npm run dev, :5173）はViteのproxyでバックエンドへ中継する構成。
// フロントのfetchは相対パスで書けるため、devサーバー利用時はCORS設定が一切不要。
//   /api/*        → FastAPI (読み取り専任BFF, :8090)
//   /shift/api/*  → Django  (書き込み系API,   :8000)
//
// 本番相当のビルド（npm run build, Djangoの/shift/から配信）時は、Viteのproxyは介在しないため、
// 代わりにDjango側に用意した中継ビュー（app/work_shift/spa_views.py の fastapi_proxy、
// config/urls.py の "api/v1/shifts/snapshot"）が同じ役割を果たす。フロントのfetchコードは
// どちらの経路でも変更不要（常に相対パスのまま）。
//
// ビルド成果物は Django のアプリ静的ディレクトリ規約（<app>/static/<app_name>/...）に
// 直接出力する。STATICFILES_DIRS への追加登録は不要（AppDirectoriesFinderが自動検出する）。
// base を "/static/work_shift/" にすることで、index.html内のJS/CSS参照がその場所を指す。
export default defineConfig({
  plugins: [vue()],
  base: '/static/work_shift/',
  build: {
    outDir: fileURLToPath(new URL('../../app/work_shift/static/work_shift', import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/shift/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
      },
    },
  },
});
