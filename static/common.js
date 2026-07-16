/**
 * ページトップへスムーズにスクロール
 */
function scrollToTop() {
    window.scrollTo({
        top: 0,
        behavior: 'smooth'
    });
}

/**
 * スクロール位置に応じてボタンの表示/非表示を切り替え
 */
function toggleTopButton() {
    const topBtn = document.querySelector('.top-btn');
    if (!topBtn) return;
    
   // data-scroll-target属性で指定された要素、なければwindow
    const targetSelector = topBtn.getAttribute('data-scroll-target');
    const scrollElement = targetSelector ? document.querySelector(targetSelector) : window;
    const scrollY = scrollElement === window ? window.scrollY : scrollElement.scrollTop;
    
    if (scrollY > 300) {
        topBtn.classList.add('show');
    } else {
        topBtn.classList.remove('show');
    }
}

/**
 * ページ読み込み時の初期化
 */
document.addEventListener('DOMContentLoaded', function() {
    const topBtn = document.querySelector('.top-btn');
    if (!topBtn) return;
    
    // 監視対象要素を取得
    const targetSelector = topBtn.getAttribute('data-scroll-target');
    const scrollElement = targetSelector ? document.querySelector(targetSelector) : window;
    
    // スクロールイベントを適切な要素に設定
    scrollElement.addEventListener('scroll', toggleTopButton);
    
    // 初期表示チェック
    toggleTopButton();
    
    // ボタンクリック時の動作
    topBtn.addEventListener('click', function(e) {
        e.preventDefault();
        if (scrollElement === window) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
            scrollElement.scrollTo({ top: 0, behavior: 'smooth' });
        }
    });
});
