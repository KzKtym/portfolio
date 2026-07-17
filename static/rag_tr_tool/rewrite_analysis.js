/* rewrite_analysis.js - Rewrite Analysisパネルのインタラクション */

{
    const rwaBtn = document.getElementById('rwaBtn');
    const rwaView = document.getElementById('rwaView');
    const rwaCard = rwaBtn ? rwaBtn.closest('[data-exp-id-a]') : null;
    const expIdA = rwaCard ? rwaCard.dataset.expIdA : null;
    const expIdB = rwaCard ? rwaCard.dataset.expIdB : null;

    if (rwaBtn && !rwaBtn.disabled && expIdA && expIdB) {
        rwaBtn.addEventListener('click', async () => {
            rwaBtn.disabled = true;
            rwaBtn.textContent = '読み込み中...';
            rwaView.innerHTML = '<div class="text-muted small">データを読み込んでいます...</div>';

            try {
                const res = await fetch(`/rag/rwa/?id_a=${expIdA}&id_b=${expIdB}`);
                const data = await res.json();

                if (!res.ok) {
                    rwaView.innerHTML = `<div class="text-danger small">エラー: ${data.error}</div>`;
                    return;
                }

                rwaView.innerHTML = renderRwa(data);
            } catch (e) {
                rwaView.innerHTML = `<div class="text-danger small">通信エラー: ${e}</div>`;
            } finally {
                rwaBtn.disabled = false;
                rwaBtn.textContent = 'Rewrite比較実行';
            }
        });
    }

    function calcSummary(queries) {
        let improved = 0, degraded = 0, unchanged = 0, rewriteGain = 0;
        for (const q of queries) {
            const delta = q.mrr_rewrite - q.mrr_original;
            if (delta > 0) improved++;
            else if (delta < 0) degraded++;
            else unchanged++;
            const origSources = new Set(q.results_original.map(r => r.source));
            rewriteGain += q.results_rewrite.filter(r => !origSources.has(r.source)).length;
        }
        return { improved, degraded, unchanged, rewriteGain };
    }

    function summaryLine(s, label) {
        return `<div>${escapeHtml(label)}: 改善 ${s.improved} / 悪化 ${s.degraded} / 変化なし ${s.unchanged} / Rewrite Gain: ${s.rewriteGain}</div>`;
    }

    function diffLine(sA, sB) {
        const fmt = (v) => (v > 0 ? `+${v}` : `${v}`);
        return `<div class="mt-1 text-muted">差分: `
            + `改善 ${fmt(sB.improved - sA.improved)} / `
            + `悪化 ${fmt(sB.degraded - sA.degraded)} / `
            + `変化なし ${fmt(sB.unchanged - sA.unchanged)} / `
            + `Rewrite Gain: ${fmt(sB.rewriteGain - sA.rewriteGain)}`
            + `</div>`;
    }

    function renderRwa(data) {
        const { rwa_a, rwa_b, has_rwa_a, has_rwa_b, label_a, label_b } = data;

        let html = `<div class="mb-3 text-muted small">比較対象 (ID:query_rewrite)： ${escapeHtml(label_a)} → ${escapeHtml(label_b)}</div>`;

        if (!has_rwa_a && !has_rwa_b) {
            html += '<div class="text-muted small">どちらの実験にもRewriteデータがありません。</div>';
            return html;
        }

        if (!has_rwa_a) {
            html += `<div class="text-muted small">${escapeHtml(label_a)}: Rewriteデータなし</div>`;
        } else {
            html += summaryLine(calcSummary(rwa_a), label_a);
        }

        if (!has_rwa_b) {
            html += `<div class="text-muted small">${escapeHtml(label_b)}: Rewriteデータなし</div>`;
        } else {
            html += summaryLine(calcSummary(rwa_b), label_b);
        }

        // 両方データがある場合のみ差分行を表示
        if (has_rwa_a && has_rwa_b) {
            html += diffLine(calcSummary(rwa_a), calcSummary(rwa_b));
        }

        return html;
    }

    function escapeHtml(str) {
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
}