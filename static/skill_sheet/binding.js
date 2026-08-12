/*
 * セル同期定義の画面。
 *
 * - 登録・編集: モデルの選択に応じてフィールドの候補を絞り込む
 * - 一覧: 設定ファイルの雛形をクリップボードへコピー
 *
 * どちらの画面からも同じファイルを読むので、対象が無ければ何もしない。
 */
(function () {
    'use strict';

    function setupFieldFilter() {
        var mapNode = document.getElementById('field-map');
        var modelSelect = document.getElementById('id_model_label');
        var fieldSelect = document.getElementById('id_field_name');
        if (!mapNode || !modelSelect || !fieldSelect) {
            return;
        }

        var fieldMap = JSON.parse(mapNode.textContent);

        function refresh(keepValue) {
            var choices = fieldMap[modelSelect.value] || [];
            fieldSelect.innerHTML = '';

            var blank = document.createElement('option');
            blank.value = '';
            blank.textContent = choices.length ? '---------' : '先にモデル名を選択';
            fieldSelect.appendChild(blank);

            choices.forEach(function (choice) {
                var option = document.createElement('option');
                option.value = choice.value;
                option.textContent = choice.text;
                fieldSelect.appendChild(option);
            });

            // 編集時とエラー差し戻し時に、選ばれていた値を復元する
            if (keepValue) {
                fieldSelect.value = keepValue;
            }
        }

        // 描画時点の値を保持してから絞り込む
        refresh(fieldSelect.value);
        modelSelect.addEventListener('change', function () {
            refresh('');
        });
    }

    function setupSampleCopy() {
        var button = document.getElementById('copy-sample');
        var sample = document.getElementById('sample-config');
        if (!button || !sample) {
            return;
        }

        button.addEventListener('click', function () {
            var text = sample.textContent;
            var done = function () {
                var original = button.textContent;
                button.textContent = 'コピーしました';
                setTimeout(function () { button.textContent = original; }, 1500);
            };

            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(done, selectFallback);
            } else {
                selectFallback();
            }

            // クリップボードが使えない場合は選択状態にして利用者に任せる
            function selectFallback() {
                var range = document.createRange();
                range.selectNodeContents(sample);
                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        setupFieldFilter();
        setupSampleCopy();
    });
})();
