// frontend/work_shift/src/lib/api.ts
/**
 * Django の書き込み系API（/shift/api/v1/...）を呼ぶための共通ラッパ。
 *
 * Django側は CsrfViewMiddleware による保護が有効なため、POST/PUT/PATCH/DELETE には
 * X-CSRFToken ヘッダが必須となる。各コンポーネントが素の fetch を直接呼ぶと付け忘れが
 * 起きるため、書き込みは必ずこの apiFetch を経由させる。
 *
 * 読み取り（GET）はCSRF不要なので素の fetch のままでよい。このラッパを通しても害はない。
 *
 * 経路について（vite.config.ts と対応）:
 *   npm run dev  → Viteのproxyで /shift/api → :8000(Django), /api → :8090(FastAPI)
 *   npm run build → Djangoの /shift/ から配信。/api は spa_views.fastapi_proxy が中継
 * いずれも同一オリジンなので、CORS設定もクロスオリジンのクッキー送信も不要。
 */

const CSRF_COOKIE_NAME = 'csrftoken';
const CSRF_ENDPOINT = '/shift/api/v1/csrf/';

/** CSRFトークンが不要なメソッド（Djangoの CsrfViewMiddleware と同じ判定）。 */
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE']);

/** 同一トークン取得リクエストの多重発行を防ぐためのin-flightキャッシュ。 */
let inflightCsrfRequest: Promise<string> | null = null;

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  for (const chunk of document.cookie.split(';')) {
    const cookie = chunk.trim();
    if (cookie.startsWith(prefix)) {
      return decodeURIComponent(cookie.slice(prefix.length));
    }
  }
  return null;
}

async function requestCsrfToken(): Promise<string> {
  await fetch(CSRF_ENDPOINT, { credentials: 'same-origin' });

  const token = readCookie(CSRF_COOKIE_NAME);
  if (!token) {
    throw new Error('CSRFトークンを取得できませんでした。ログイン状態を確認してください。');
  }
  return token;
}

/**
 * csrftoken クッキーを返す。未発行なら CSRF_ENDPOINT を叩いて発行させてから返す。
 *
 * npm run dev では index.html を Vite が配信し、Django の spa_index（@ensure_csrf_cookie）を
 * 通らないため、初回はクッキーが存在しない。この関数がその差を吸収する。
 *
 * 複数の書き込みを Promise.all / Promise.allSettled で同時発行するケース（AddMemberModal 等）
 * があるため、取得リクエストはin-flightキャッシュで1本に束ねる。
 */
async function ensureCsrfToken(): Promise<string> {
  const cached = readCookie(CSRF_COOKIE_NAME);
  if (cached) return cached;

  if (!inflightCsrfRequest) {
    inflightCsrfRequest = requestCsrfToken().finally(() => {
      inflightCsrfRequest = null;
    });
  }
  return inflightCsrfRequest;
}

/**
 * fetch のラッパ。書き込みメソッドのときだけ X-CSRFToken を付与する。
 * 引数・戻り値は fetch と同じなので、呼び出し側は fetch を apiFetch に置き換えるだけでよい。
 */
export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase();
  const headers = new Headers(init.headers);

  if (!SAFE_METHODS.has(method)) {
    headers.set('X-CSRFToken', await ensureCsrfToken());
  }

  return fetch(input, { ...init, headers, credentials: 'same-origin' });
}
