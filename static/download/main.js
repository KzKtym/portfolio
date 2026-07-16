document.addEventListener('DOMContentLoaded', function () {
    // ===== 下書き表示: Copyボタン =====
    var copyButton = document.getElementById('copy-button');
    if (copyButton) {
        copyButton.addEventListener('click', function () {
            var textarea = document.getElementById('draft-text');
            var message = document.getElementById('copy-message');

            textarea.select();
            textarea.setSelectionRange(0, 99999);

            navigator.clipboard.writeText(textarea.value).then(function () {
                if (message) {
                    message.textContent = 'コピーしました';
                    setTimeout(function () {
                        message.textContent = '';
                    }, 2000);
                }
            }).catch(function () {
                document.execCommand('copy');
                if (message) {
                    message.textContent = 'コピーしました';
                    setTimeout(function () {
                        message.textContent = '';
                    }, 2000);
                }
            });
        });
    }

    // ===== 管理画面: 新規ユーザー追加行の表示切り替え =====
    var addUserButton = document.getElementById('add-user-button');
    var newUserRow = document.getElementById('new-user-row');
    if (addUserButton && newUserRow) {
        addUserButton.addEventListener('click', function () {
            newUserRow.hidden = !newUserRow.hidden;
        });

        var newUserCancel = newUserRow.querySelector('.cancel-button');
        if (newUserCancel) {
            newUserCancel.addEventListener('click', function () {
                newUserRow.hidden = true;
            });
        }
    }

    // ===== 管理画面: ユーザー行の編集/キャンセル切り替え =====
    document.querySelectorAll('.user-row').forEach(function (row) {
        var editButton = row.querySelector('.edit-button');
        var viewCells = row.querySelectorAll('.view-mode');
        var editCell = row.querySelector('.edit-mode');

        if (!editButton || !editCell) {
            return;
        }

        editButton.addEventListener('click', function () {
            viewCells.forEach(function (cell) {
                cell.hidden = true;
            });
            editCell.hidden = false;
        });

        var cancelButton = editCell.querySelector('.cancel-button');
        if (cancelButton) {
            cancelButton.addEventListener('click', function () {
                editCell.hidden = true;
                viewCells.forEach(function (cell) {
                    cell.hidden = false;
                });
            });
        }
    });
});
