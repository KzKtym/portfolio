/**
 * 検索キーワードをハイライト表示する
 * @param {Array} keywords - ハイライトするキーワードの配列
 */
function highlightKeywords(keywords) {
    if (!keywords || keywords.length === 0) {
        return;
    }

    // ハイライト対象の要素を取得（.searchableクラスを持つ要素）
    const searchableElements = document.querySelectorAll('.searchable');

    searchableElements.forEach(element => {
        let html = element.innerHTML;

        // 各キーワードをハイライト
        keywords.forEach(keyword => {
            if (!keyword) return;

            // 大文字小文字を区別しない正規表現を作成
            // 特殊文字をエスケープ
            const escapedKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const regex = new RegExp(`(${escapedKeyword})`, 'gi');

            // すでに太字タグで囲まれていないテキストのみを対象にする
            // HTMLタグ内のテキストは対象外
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = html;

            function highlightTextNodes(node) {
                if (node.nodeType === Node.TEXT_NODE) {
                    const text = node.textContent;
                    if (regex.test(text)) {
                        const span = document.createElement('span');
                        span.innerHTML = text.replace(regex, '<strong class="keyword-highlight">$1</strong>');
                        node.parentNode.replaceChild(span, node);
                        // spanの中身を直接親に展開
                        while (span.firstChild) {
                            span.parentNode.insertBefore(span.firstChild, span);
                        }
                        span.parentNode.removeChild(span);
                    }
                } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName !== 'SCRIPT' && node.tagName !== 'STYLE') {
                    // 子ノードを処理（後ろから処理してインデックスのズレを防ぐ）
                    const children = Array.from(node.childNodes);
                    children.forEach(child => highlightTextNodes(child));
                }
            }

            highlightTextNodes(tempDiv);
            html = tempDiv.innerHTML;
        });

        element.innerHTML = html;
    });
}

/**
 * 検索フォーム送信時にURLハッシュをクリア
 */
document.addEventListener('DOMContentLoaded', function() {
    const searchForm = document.querySelector('.search-section form');
    if (searchForm) {
        searchForm.addEventListener('submit', function() {
            // URLからハッシュを削除
            if (window.location.hash) {
                history.replaceState(null, null, window.location.pathname + window.location.search);
            }
        });
    }
});