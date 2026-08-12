/*
 * サービス管理画面（お知らせ管理）のクライアント処理
 *
 *  - Edit    : 画面遷移せず表示モード ⇔ 編集モードを切り替える
 *  - タブ    : 編集 / プレビュー（プレビューはサーバ側で /home/ と同じ変換を行う）
 *  - Cancel  : 確認ダイアログ（yes/no）の上で編集内容を破棄し表示モードへ戻る
 *  - Save    : 通常の form POST（JS は関与しない）
 */
(function () {
    'use strict';

    var previewUrl = document.currentScript.dataset.previewUrl;

    document.addEventListener('DOMContentLoaded', function () {
        var viewArea = document.getElementById('notice-view');
        var editForm = document.getElementById('notice-edit');
        var editButton = document.getElementById('notice-edit-button');
        var cancelButton = document.getElementById('notice-cancel-button');
        var textarea = document.getElementById('notice-textarea');
        var previewArea = document.getElementById('notice-preview');

        if (!viewArea || !editForm || !editButton || !textarea) {
            return;
        }

        // Cancel 時に戻すための原文。保存後はページが再読み込みされるため、
        // ここで1度だけ控えておけば十分。
        var originalText = textarea.value;
        var tabs = editForm.querySelectorAll('.notice-tab');
        var panes = editForm.querySelectorAll('.notice-pane');

        function setMode(editing) {
            viewArea.classList.toggle('is-hidden', editing);
            editForm.classList.toggle('is-hidden', !editing);
            editButton.classList.toggle('is-active', editing);
            if (editing) {
                selectTab('write');
                textarea.focus();
            }
        }

        function selectTab(name) {
            tabs.forEach(function (tab) {
                tab.classList.toggle('is-active', tab.dataset.tab === name);
            });
            panes.forEach(function (pane) {
                pane.classList.toggle('is-hidden', pane.dataset.pane !== name);
            });
            if (name === 'preview') {
                renderPreview();
            }
        }

        function renderPreview() {
            var token = editForm.querySelector('[name=csrfmiddlewaretoken]');
            var body = new FormData();
            body.append('content', textarea.value);

            previewArea.textContent = 'プレビューを生成中...';

            fetch(previewUrl, {
                method: 'POST',
                headers: { 'X-CSRFToken': token ? token.value : '' },
                body: body,
                credentials: 'same-origin'
            })
                .then(function (res) {
                    if (!res.ok) {
                        throw new Error('HTTP ' + res.status);
                    }
                    return res.json();
                })
                .then(function (data) {
                    previewArea.innerHTML = data.html;
                })
                .catch(function () {
                    previewArea.textContent = 'プレビューの取得に失敗しました。';
                });
        }

        editButton.addEventListener('click', function () {
            setMode(editForm.classList.contains('is-hidden'));
        });

        cancelButton.addEventListener('click', function () {
            if (!window.confirm('編集内容を破棄します。よろしいですか？')) {
                return;
            }
            textarea.value = originalText;
            previewArea.innerHTML = '';
            setMode(false);
        });

        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                selectTab(tab.dataset.tab);
            });
        });
    });

    /*
     * 新規発行フォーム: 「新規作成」か既存ユーザーかで入力欄を出し分ける
     */
    document.addEventListener('DOMContentLoaded', function () {
        var select = document.getElementById('meeting-username');
        var form = document.getElementById('issue-form');
        if (!select || !form) {
            return;
        }

        var newUsername = document.getElementById('meeting-new-username');

        function sync() {
            var isNew = select.value === '__new__';
            form.querySelectorAll('[data-when]').forEach(function (row) {
                var wants = row.dataset.when === (isNew ? 'new' : 'existing');
                row.classList.toggle('is-hidden', !wants);
            });
            // 隠れている欄を required にすると送信できなくなるため、表示時だけ必須にする
            newUsername.required = isNew;
        }

        select.addEventListener('change', sync);
        sync();
    });

    /*
     * 発行結果のコピーボタン
     *   クリップボードには "URL: <値>" / "Pass: <値>" の形で入れる。
     *   clipboard API は安全なコンテキスト（https / localhost）でしか使えないため、
     *   使えない環境では従来の execCommand にフォールバックする。
     */
    document.addEventListener('DOMContentLoaded', function () {
        function fallbackCopy(text) {
            var area = document.createElement('textarea');
            area.value = text;
            area.setAttribute('readonly', '');
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            var ok = false;
            try {
                ok = document.execCommand('copy');
            } catch (e) {
                ok = false;
            }
            document.body.removeChild(area);
            return ok;
        }

        function flash(button, message) {
            var original = button.dataset.originalLabel || button.textContent;
            button.dataset.originalLabel = original;
            button.textContent = message;
            setTimeout(function () {
                button.textContent = original;
            }, 1500);
        }

        document.querySelectorAll('.copy-button').forEach(function (button) {
            button.addEventListener('click', function () {
                var target = document.getElementById(button.dataset.copyTarget);
                if (!target) {
                    return;
                }
                var text = button.dataset.copyPrefix + target.textContent.trim();

                if (navigator.clipboard && window.isSecureContext) {
                    navigator.clipboard.writeText(text).then(
                        function () { flash(button, 'コピーしました'); },
                        function () { flash(button, fallbackCopy(text) ? 'コピーしました' : '失敗'); }
                    );
                    return;
                }
                flash(button, fallbackCopy(text) ? 'コピーしました' : '失敗');
            });
        });
    });
})();
