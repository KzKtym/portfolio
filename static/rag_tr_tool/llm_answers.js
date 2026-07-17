/* llm_answers.js - LLM回答生成パネルのインタラクション */

{
    const generateBtn = document.getElementById('generateBtn');
    const answersView = document.getElementById('answersView');
    const llmCard = generateBtn ? generateBtn.closest('[data-exp-id]') : null;
    const expId = llmCard ? llmCard.dataset.expId : null;
    const queryCount = llmCard ? llmCard.dataset.queryCount : '?';

    if (generateBtn && expId) {
        generateBtn.addEventListener('click', async () => {
            if (!window.confirm(`${queryCount}件のクエリに対してLLM回答を生成します。\nよろしいですか？`)) return;
            generateBtn.disabled = true;
            generateBtn.textContent = '生成中...';
            answersView.innerHTML = '<div class="text-muted small">APIに問い合わせ中です。しばらくお待ちください...<br><i style="color:red">（※デモ用のため処理は中断しています。次の操作へ進んでください。）</i></div>';
            return; //デモ用（処理中断）

            const csrfToken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
            try {
                const res = await fetch(`/rag/generate-answers/${expId}/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                });
                const data = await res.json();

                if (!res.ok) {
                    const partial = data.answers && data.answers.length > 0;
                    answersView.innerHTML = `<div class="text-danger small">エラー: ${data.error}</div>`
                        + (partial ? renderAnswers(data.answers) : '');
                    return;
                }

                answersView.innerHTML = renderAnswers(data.answers);
            } catch (e) {
                answersView.innerHTML = `<div class="text-danger small">通信エラー: ${e}</div>`;
            } finally {
                generateBtn.disabled = false;
                generateBtn.textContent = '再生成';
            }
        });
    }

    function renderAnswers(answers) {
        if (!answers || answers.length === 0) return '<div class="text-muted small">回答データがありません</div>';
        return answers.map((item, i) => {
            const isError = item.answer.startsWith('Error:');
            return `<div class="mb-3">
<div class="fw-bold">Q${i + 1}: ${escapeHtml(item.query)}</div>
<div class="${isError ? 'text-danger' : ''}" style="white-space:pre-wrap; padding-left:1rem;">${escapeHtml(item.answer)}</div>
</div>`;
        }).join('');
    }

    function escapeHtml(str) {
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
}
