/* list.js - 実験一覧画面のインタラクション */
/* PARAM_ORDER は common.js で定義（common.js を先に読み込むこと） */

const TOGGLE_STAR_BASE = document.getElementById('jsConfig').dataset.toggleStarBase.replace("/0/", "/");
const CSRF_TOKEN = document.getElementById('jsConfig').dataset.csrfToken;
const NEW_URL = document.getElementById('jsConfig').dataset.newUrl;

// --- PARAM_ORDER に従いパラメータを並び替えて表示文字列を生成（グループ改行なし）---
function formatParamsDisplay(paramsJson) {
    let params;
    try { params = JSON.parse(paramsJson); } catch { return paramsJson; }
    const allKnown = PARAM_ORDER.flat();
    const known = allKnown.filter(k => k in params).map(k => `${k}:${params[k]}`);
    const unknown = Object.keys(params).filter(k => !allKnown.includes(k)).map(k => `${k}:${params[k]}`);
    return [...known, ...unknown].join(', ');
}

// Parameters列をPARAM_ORDER順に書き換え
document.querySelectorAll('.exp-row').forEach(row => {
    const paramsTd = row.querySelector('td:nth-child(7)');
    if (paramsTd) paramsTd.textContent = formatParamsDisplay(row.dataset.params);
});

function getSelectedIds() {
    return Array.from(document.querySelectorAll('.exp-check:checked')).map(cb => cb.value);
}

// --- 「選択」ヘッダークリック → 全チェックオフ ---
document.getElementById('checkAllOff').addEventListener('click', function() {
    document.querySelectorAll('.exp-check').forEach(cb => cb.checked = false);
});

// --- 行クリック → result表示 / チェックセルはOn/Off ---
document.querySelectorAll('.exp-row').forEach(row => {
    row.addEventListener('click', function(e) {
        if (e.target.closest('.check-cell')) {
            const cb = this.querySelector('.exp-check');
            if (e.target !== cb) cb.checked = !cb.checked;
            return;
        }
        window.location.href = `/rag/result/${this.dataset.id}/`;
    });
});

// --- 新規実験ボタン ---
function newExperiment() {
    const ids = getSelectedIds();
    if (ids.length === 0) {
        window.location.href = NEW_URL;
    } else if (ids.length === 1) {
        const row = document.querySelector(`.exp-row[data-id="${ids[0]}"]`);
        const params = row.dataset.params;
        window.location.href = NEW_URL + "?params=" + encodeURIComponent(params);
    } else {
        alert('パラメータを選択しての新規実験は１件のみ選択してください。');
    }
}

// --- 比較ボタン（URL パラメータは常に ID 小→大）---
function compareSelected() {
    const ids = getSelectedIds();
    if (ids.length !== 2) {
        alert("比較するには2つの実験を選択してください。");
        return;
    }
    const sorted = ids.map(Number).sort((a, b) => a - b);
    const form = document.getElementById('compareForm');
    form.innerHTML = sorted.map(id => `<input type="hidden" name="ids" value="${id}">`).join('');
    form.submit();
}

// --- 削除ボタン ---
function deleteSelected() {
    const ids = getSelectedIds();
    if (ids.length === 0) return;
    if (!confirm("選択した実験を削除しますか？")) return;
    document.getElementById('deleteIds').value = ids.join(',');
    document.getElementById('deleteForm').submit();
}

// --- Starボタン（★バッジと New/1st/2nd バッジを両立）---
function toggleStarSelected() {
    const ids = getSelectedIds();
    if (ids.length === 0) return;
    ids.forEach(id => {
        fetch(TOGGLE_STAR_BASE + id + "/", {
            method: "POST",
            headers: {"X-CSRFToken": CSRF_TOKEN, "Content-Type": "application/json"},
        })
        .then(r => r.json())
        .then(data => {
            const row = document.querySelector(`.exp-row[data-id="${id}"]`);
            if (!row) return;
            row.dataset.starred = data.starred ? "true" : "false";
            const td = row.querySelector('td:nth-child(3)');
            const starBadge = td.querySelector('.star-badge');
            if (data.starred) {
                if (!starBadge) {
                    const span = document.createElement('span');
                    span.className = "ms-1 badge bg-warning text-dark star-badge";
                    span.style.fontSize = "0.7rem";
                    span.textContent = "★";
                    const iconBadge = td.querySelector('.icon-badge');
                    iconBadge ? td.insertBefore(span, iconBadge) : td.appendChild(span);
                }
            } else {
                if (starBadge) starBadge.remove();
            }
        });
    });
}

// --- T-CC / M-CC / P-CC / A-CC：選択行の情報をクリップボードにコピー ---
// 選択なし時は data-icon="new" の行（最新実験）をフォールバック対象とする
function copySelected(type) {
    let ids = getSelectedIds();
    if (ids.length === 0) {
        const newRow = document.querySelector('.exp-row[data-icon="new"]');
        if (!newRow) return;
        ids = [newRow.dataset.id];
    }
    const texts = ids.map(id => {
        const row = document.querySelector(`.exp-row[data-id="${id}"]`);
        if (!row) return '';
        const idStr = `実験ID:${id}`;
        const title = row.dataset.name || '(no title)';
        const metrics = `MRR=${row.dataset.mrr},Recall@K=${row.dataset.recall}`;
        const params = `Parameters:\n${formatParamsDisplay(row.dataset.params)}`;
        if (type === 'title') return `${idStr} ${title}`;
        if (type === 'metrics') return `${idStr} ${metrics}`;
        if (type === 'params') return `${idStr} ${params}`;
        if (type === 'all') return `${idStr} ${title}\n\n${params}\n\n${metrics}`;
        return '';
    });
    navigator.clipboard.writeText(texts.join('\n\n'));
}