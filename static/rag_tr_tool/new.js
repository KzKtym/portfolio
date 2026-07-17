/* new.js - 新規実験画面のインタラクション */

const cfg = document.getElementById('jsConfig').dataset;
const checkIndexUrl = cfg.checkIndexUrl;
const paramInput = document.getElementById('paramInput');
const rebuildCheck = document.getElementById('rebuildCheck');
const rebuildLabel = document.getElementById('rebuildLabel');

// 1. 実験タイトルの初期値生成
//    前回タイトル無し：'ex' + MMDD-HHMM
//    前回タイトル有り：前回タイトル + '-' + n（末尾が '-数字' なら数字をインクリメント）
const lastName = cfg.lastName || '';
if (lastName) {
    const m = lastName.match(/^(.*)-(\d+)$/);
    if (m) {
        document.getElementById('expName').value = `${m[1]}-${parseInt(m[2], 10) + 1}`;
    } else {
        document.getElementById('expName').value = `${lastName}-2`;
    }
} else {
    const now = new Date();
    const mmdd = String(now.getMonth() + 1).padStart(2, '0') + String(now.getDate()).padStart(2, '0');
    const hhmm = String(now.getHours()).padStart(2, '0') + String(now.getMinutes()).padStart(2, '0');
    document.getElementById('expName').value = `ex${mmdd}-${hhmm}`;
}

// 2. PARAM_ORDER / PARAM_DEFS は common.js で定義（common.js を先に読み込むこと）

// 3. 最新パラメータの初期表示（パイプライン順・グループ間改行で整列）
const lastParams = JSON.parse(cfg.lastParams || '{}');

// グループ順に並べた行リストを返す。グループ間は空文字（改行区切り用）を挿入
function sortedParamLines(params) {
    const allKnown = PARAM_ORDER.flat();
    const lines = [];
    for (const group of PARAM_ORDER) {
        const groupLines = group
            .filter(k => k in params)
            .map(k => `${k}:${params[k]}`);
        if (groupLines.length === 0) continue;
        lines.push(groupLines.join(' '));
    }
    // 未知キーは末尾に追加
    const unknown = Object.entries(params)
        .filter(([k]) => !allKnown.includes(k))
        .map(([k, v]) => `${k}:${v}`);
    if (unknown.length > 0) {
        lines.push(unknown.join(' '));
    }
    return lines;
}

paramInput.value = sortedParamLines(lastParams).join('\n');

// 4. パラメータテキストをJSONに変換（スペース区切り・改行・カンマ区切りすべて対応）
function parseParams() {
    const text = paramInput.value;
    const obj = {};
    text.split(/[\n,]/).forEach(line => {
        line.trim().split(/\s+/).forEach(pair => {
            const colonIdx = pair.indexOf(':');
            if (colonIdx === -1) return;
            const key = pair.slice(0, colonIdx).trim().replace(/^["']|["']$/g, '');
            let val = pair.slice(colonIdx + 1).trim().replace(/^["']|["']$/g, '');
            if (val !== "" && !isNaN(val)) {
                val = val.includes('.') ? parseFloat(val) : parseInt(val, 10);
            }
            if (key) obj[key] = val;
        });
    });
    return obj;
}

// 5. 旧パラメータ名チェック
const OBSOLETE_PARAMS = ['max_chars', 'query_rewrite'];

// 6. バリデーション＋既定値補完
//    - 旧パラメータ名チェック
//    - 許容値チェック（valuesあり）・数値型チェック（valuesなし）
//    - エラーは全件まとめてポップアップ
//    - 既定値補完：未入力キーをparams・パラメータ欄テキストに反映
//    - 条件付き補完（bm25/rrf系）はsearch_typeに応じて挿入
//    戻り値: { ok: bool, params: object }
function validateAndComplete(params) {
    // 旧パラメータ名チェック
    const obsolete = OBSOLETE_PARAMS.filter(k => k in params);
    if (obsolete.length > 0) {
        alert(`旧パラメータ名が含まれています: ${obsolete.join(', ')}\n修正してから実行してください。`);
        return { ok: false, params };
    }

    // 既定値補完（バリデーション前に補完してから検証する）
    const completed = { ...params };
    for (const [key, def] of Object.entries(PARAM_DEFS)) {
        if (def.default === null) continue;           // 自動挿入しない
        if (key in completed) continue;               // 既に指定済み
        if (def.condition && !def.condition(completed)) continue; // 条件不成立
        completed[key] = def.default;
    }

    // gate_mode自動推論（未指定かつgate_top1/gate_marginのいずれかが指定されている場合）
    if (!('gate_mode' in completed) && ('gate_top1' in completed || 'gate_margin' in completed)) {
        const hasTop1 = 'gate_top1' in completed;
        const hasMargin = 'gate_margin' in completed;
        if (hasTop1 && hasMargin)  completed.gate_mode = "standard";
        else if (hasTop1)          completed.gate_mode = "top1";
        else                       completed.gate_mode = "margin";
    }

    // gate_mode組み合わせチェック（gate_mode優先でgate_top1/gate_marginの過不足を検証）
    if ('gate_mode' in completed) {
        const hasTop1 = 'gate_top1' in completed;
        const hasMargin = 'gate_margin' in completed;
        const gm = completed.gate_mode;
        const invalid =
            (gm === "standard" && !(hasTop1 && hasMargin)) ||
            (gm === "top1"     && !(hasTop1 && !hasMargin)) ||
            (gm === "margin"   && !(!hasTop1 && hasMargin));
        if (invalid) {
            alert("gate_modeの組み合わせエラーです。gate_top1またはgate_marginを確認してください。");
            return { ok: false, params: completed };
        }
    }

    // 不要パラメータチェック（conditionが定義されていて条件不成立なのに指定されているキー）
    const spurious = [];
    for (const [key, def] of Object.entries(PARAM_DEFS)) {
        if (!def.condition) continue;
        if (!(key in completed)) continue;
        if (!def.condition(completed)) {
            spurious.push(key);
        }
    }
    if (spurious.length > 0) {
        alert(`不要なパラメータが含まれています: ${spurious.join(', ')}\n修正してから実行してください。`);
        return { ok: false, params: completed };
    }

    // バリデーション
    const errors = [];
    for (const [key, val] of Object.entries(completed)) {
        const def = PARAM_DEFS[key];
        if (!def) continue; // 未知キーはスキップ
        if (def.values !== null) {
            // 許容値チェック（文字列型パラメータ）
            if (!def.values.includes(String(val))) {
                errors.push(`${key}: "${val}" は無効な値です（有効値: ${def.values.join(', ')}）`);
            }
        } else {
            // 数値型チェック
            if (typeof val !== 'number' || isNaN(val)) {
                errors.push(`${key}: "${val}" は数値である必要があります`);
            }
        }
    }

    if (errors.length > 0) {
        alert(`パラメータエラー:\n\n${errors.join('\n')}`);
        return { ok: false, params: completed };
    }

    // 補完結果をパラメータ欄テキストに反映
    paramInput.value = sortedParamLines(completed).join('\n');
    return { ok: true, params: completed };
}

// 7. Index確認（Ajax）＋表示更新
async function checkIndex(params) {
    const projectId = parseInt(cfg.projectId, 10);
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    const res = await fetch(checkIndexUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({...params, project_id: projectId}),
    });
    const data = await res.json();
    const statusEl = document.getElementById('indexStatus');
    if (data.exists) {
        const detail = (data.created_at && data.creation_time)
            ? `有（${data.created_at} RT. ${data.creation_time}）`
            : '有';
        statusEl.textContent = detail;
        statusEl.className = 'ms-2 fw-bold text-success';
    } else {
        statusEl.textContent = '無';
        statusEl.className = 'ms-2 fw-bold text-danger';
    }
    // Chunks欄更新
    const chunkEl = document.getElementById('chunkStats');
    if (data.exists && data.chunk_stats && data.chunk_stats.total) {
        const s = data.chunk_stats;
        chunkEl.textContent = `Total: ${s.total} / 平均: ${s.avg} / 最大: ${s.max} / 最小: ${s.min}`;
    } else {
        chunkEl.textContent = '—';
    }
    updateRebuildVisibility(data.exists);
    // SPEC欄更新
    const specEl = document.querySelector('#specPanel pre');
    if (specEl && data.spec_text !== undefined) {
        specEl.textContent = data.spec_text;
    }
    return data.exists;
}

// 8. 再作成チェックボックスの不活性制御
function updateRebuildVisibility(indexExists) {
    if (indexExists) {
        rebuildCheck.disabled = false;
        rebuildLabel.style.color = '';
    } else {
        rebuildCheck.disabled = true;
        rebuildCheck.checked = false;
        rebuildLabel.style.color = '#adb5bd';
    }
}
// 初期表示（サーバーサイドの値で制御）
updateRebuildVisibility(cfg.indexExists === 'true');

// 9. 再確認ボタン：バリデーション＋補完 → Index確認
document.getElementById('recheckBtn').addEventListener('click', async function () {
    const parsed = parseParams();
    const { ok, params } = validateAndComplete(parsed);
    if (!ok) return;
    await checkIndex(params);
});

// 10. Run確認ダイアログのメッセージ生成
//    indexExists=false → Indexなし（作成・時間がかかる旨）
//    indexExists=true かつ rebuild=true → Index再作成（時間がかかる旨）
//    indexExists=true かつ rebuild=false → 通常確認のみ
function buildConfirmMessage(params, indexExists) {
    const title = document.getElementById('expName').value.trim() || '（タイトルなし）';
    const paramLines = sortedParamLines(params).join('\n');
    let msg = '';
    if (!indexExists) {
        msg += `⚠️ Indexが存在しません。Index作成を開始します（時間がかかります）。\n\n`;
    } else if (rebuildCheck.checked) {
        msg += `⚠️ Indexを再作成します（時間がかかります）。\n\n`;
    }
    msg += `【実験内容の確認】\n`;
    msg += `タイトル: ${title}\n`;
    msg += `パラメータ:\n${paramLines}\n`;
    msg += `\n実行しますか？`;
    return msg;
}

// 11. デモ用：フォームの全送信経路を停止する
//    Runボタン以外の経路（タイトル欄でEnterによる暗黙送信など）でも
//    実際の実行に進まないよう、submitイベント自体を抑止する。
document.getElementById('runForm').addEventListener('submit', e => e.preventDefault());

// 12. Runボタン：バリデーション＋補完 → Index確認 → 確認ダイアログ → 送信
document.getElementById('runBtn').addEventListener('click', async function () {
    const parsed = parseParams();
    const { ok, params } = validateAndComplete(parsed);
    if (!ok) return;
    const exists = await checkIndex(params);
    const ok2 = confirm(buildConfirmMessage(params, exists));
    if (!ok2) return;
    alert('デモのため処理中断'); // ※デモ用（処理中断）
    return;

    // document.getElementById('finalParams').value = JSON.stringify(params);
    // document.getElementById('runForm').submit();
});