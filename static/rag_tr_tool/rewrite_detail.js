/* rewrite_detail.js - Rewrite詳細タブのCopyボタン対応 */
// Rewriteタブ選択時、CopyボタンはrewriteViewのinnerTextをコピーする
// result.jsのcopyBtn処理はsummary/form1/form2を対象としているため、
// rewriteフォーマットのコピーはこちらで補完する。

{
    const copyBtn = document.getElementById('copyBtn');
    const rewriteView = document.getElementById('rewriteView');

    if (copyBtn && rewriteView) {
        const originalHandler = copyBtn.onclick;

        copyBtn.addEventListener('click', async () => {
            // currentFmtはresult.jsのスコープで定義されているためwindow経由でなくグローバル参照
            if (typeof currentFmt !== 'undefined' && currentFmt === 'rewrite') {
                const text = rewriteView.innerText || '';
                await navigator.clipboard.writeText(text);
                copyBtn.textContent = 'Copied!';
                setTimeout(() => copyBtn.textContent = 'Copy', 2000);
            }
        }, true); // キャプチャフェーズで先に処理
    }
}