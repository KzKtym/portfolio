/* result.js - 実験結果画面のインタラクション */
/* PARAM_ORDER は common.js で定義（common.js を先に読み込むこと） */

// ===== Parameters 表示をPARAM_ORDER順に書き換え =====
function formatParamsDisplay(params) {
    const allKnown = PARAM_ORDER.flat();
    const known = allKnown.filter(k => k in params).map(k => `${k}:${params[k]}`);
    const unknown = Object.keys(params).filter(k => !allKnown.includes(k)).map(k => `${k}:${params[k]}`);
    return [...known, ...unknown].join(', ');
}

const expMeta = document.getElementById('expMeta');
if (expMeta) {
    let expParams;
    try { expParams = JSON.parse(expMeta.dataset.expParams); } catch { expParams = null; }
    if (expParams) {
        const paramsDisplay = formatParamsDisplay(expParams);
        // 評価概要テーブルの Parameters セル
        const paramsCell = document.getElementById('paramsCell');
        if (paramsCell) paramsCell.textContent = paramsDisplay;
        // Summary の Parameters 行
        const summaryParams = document.getElementById('summaryParams');
        if (summaryParams) summaryParams.textContent = paramsDisplay;
    }
}

// ===== T-CC / MR-CC / P-CC / ALL-CC =====
if (expMeta) {
    const id = expMeta.dataset.expId;
    const name = expMeta.dataset.expName || '(no title)';
    const mrr = expMeta.dataset.expMrr;
    const recall = expMeta.dataset.expRecall;
    let expParams;
    try { expParams = JSON.parse(expMeta.dataset.expParams); } catch { expParams = {}; }
    const paramsStr = formatParamsDisplay(expParams);

    function ccCopy(text, btn) {
        navigator.clipboard.writeText(text);
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = orig, 2000);
    }

    const ccTitle = document.getElementById('ccTitle');
    const ccMetrics = document.getElementById('ccMetrics');
    const ccParams = document.getElementById('ccParams');

    const ccAll = document.getElementById('ccAll');

    if (ccTitle) ccTitle.addEventListener('click', () => ccCopy(`ID:${id} ${name}`, ccTitle));
    if (ccMetrics) ccMetrics.addEventListener('click', () => ccCopy(`ID:${id} MRR=${mrr},Recall@K=${recall}`, ccMetrics));
    if (ccParams) ccParams.addEventListener('click', () => ccCopy(`ID:${id} Parameters:\n${paramsStr}`, ccParams));
    if (ccAll) ccAll.addEventListener('click', () =>
        ccCopy(`ID:${id} ${name}\n\nParameters:\n${paramsStr}\n\nMRR=${mrr},Recall@K=${recall}`, ccAll));
}

// ===== 書式切り替え =====
const btnSummary = document.getElementById('btnSummary');
const btnFmt1 = document.getElementById('btnFmt1');
const btnFmt2 = document.getElementById('btnFmt2');
const btnRewrite1 = document.getElementById('btnRewrite1');
const btnRewrite2 = document.getElementById('btnRewrite2');
const summaryView = document.getElementById('summaryView');
const fmt1View = document.getElementById('fmt1View');
const fmt2View = document.getElementById('fmt2View');
const rewriteView = document.getElementById('rewriteView');
const rewrite1Content = document.getElementById('rewrite1Content');
const rewrite2Content = document.getElementById('rewrite2Content');
let currentFmt = 'summary';

function switchFmt(fmt) {
    currentFmt = fmt;
    summaryView && (summaryView.style.display = fmt === 'summary' ? '' : 'none');
    fmt1View && (fmt1View.style.display = fmt === '1' ? '' : 'none');
    fmt2View && (fmt2View.style.display = fmt === '2' ? '' : 'none');
    if (rewriteView) {
        rewriteView.style.display = (fmt === 'rewrite1' || fmt === 'rewrite2') ? '' : 'none';
    }
    if (rewrite1Content) rewrite1Content.style.display = fmt === 'rewrite1' ? '' : 'none';
    if (rewrite2Content) rewrite2Content.style.display = fmt === 'rewrite2' ? '' : 'none';
    btnSummary && btnSummary.classList.toggle('active', fmt === 'summary');
    btnFmt1 && btnFmt1.classList.toggle('active', fmt === '1');
    btnFmt2 && btnFmt2.classList.toggle('active', fmt === '2');
    btnRewrite1 && btnRewrite1.classList.toggle('active', fmt === 'rewrite1');
    btnRewrite2 && btnRewrite2.classList.toggle('active', fmt === 'rewrite2');
}

if (btnSummary) btnSummary.addEventListener('click', () => switchFmt('summary'));
if (btnFmt1) btnFmt1.addEventListener('click', () => switchFmt('1'));
if (btnFmt2) btnFmt2.addEventListener('click', () => switchFmt('2'));
if (btnRewrite1) btnRewrite1.addEventListener('click', () => switchFmt('rewrite1'));
if (btnRewrite2) btnRewrite2.addEventListener('click', () => switchFmt('rewrite2'));

// ===== Copyボタン =====
const copyBtn = document.getElementById('copyBtn');
if (copyBtn) {
    const expId = copyBtn.dataset.expId;
    copyBtn.addEventListener('click', async () => {
        let text = '';
        if (currentFmt === 'summary') {
            text = summaryView ? summaryView.innerText : '';
        } else if (currentFmt === 'rewrite1' || currentFmt === 'rewrite2') {
            text = rewriteView ? rewriteView.innerText : '';
        } else {
            const url = `/rag/log/${expId}/text/?fmt=${currentFmt}`;
            const res = await fetch(url);
            if (!res.ok) {
                alert('ログデータの取得に失敗しました');
                return;
            }
            text = await res.text();
        }
        await navigator.clipboard.writeText(text);
        copyBtn.textContent = 'Copied!';
        setTimeout(() => copyBtn.textContent = 'Copy', 2000);
    });
}

// ===== タイトルインライン編集 =====
{
    const nameCell = document.getElementById('nameCell');
    if (nameCell) {
        const expId = nameCell.dataset.expId;

        nameCell.addEventListener('click', function () {
            if (this.querySelector('input')) return;
            const original = this.textContent.trim();
            const input = document.createElement('input');
            input.type = 'text';
            input.value = original === '(no title)' ? '' : original;
            input.className = 'form-control form-control-sm';
            input.style.minWidth = '200px';
            this.textContent = '';
            this.appendChild(input);
            input.focus();

            async function save() {
                const newName = input.value.trim();
                const display = newName || '(no title)';
                if (newName === original) { nameCell.textContent = original; return; }
                const csrfToken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
                await fetch(`/rag/update-name/${expId}/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                    body: JSON.stringify({ name: newName }),
                });
                nameCell.textContent = display;
            }

            input.addEventListener('blur', save);
            input.addEventListener('keydown', e => {
                if (e.key === 'Enter') input.blur();
                if (e.key === 'Escape') { nameCell.textContent = original; }
            });
        });
    }
}