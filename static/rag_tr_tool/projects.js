const _cfg = document.getElementById("jsConfig");
const CSRF_TOKEN = _cfg.dataset.csrfToken;
const PROJECT_EDIT_BASE = _cfg.dataset.projectEditBase.replace("/0/edit/", "/");
const PROJECT_DELETE_BASE = _cfg.dataset.projectDeleteBase.replace("/0/delete/", "/");
const EXPERIMENT_LIST_BASE = _cfg.dataset.experimentListBase.replace("/0/", "/");

marked.setOptions({
    breaks: true,
    gfm: true
});

document.addEventListener("DOMContentLoaded", function() {
    const descData = JSON.parse(document.getElementById("desc-data").textContent);
    document.querySelectorAll(".proj-desc-display").forEach(el => {
        const projectId = el.dataset.projectId;
        el.innerHTML = marked.parse(descData[projectId] || "");
    });
});

function toggleNewForm() {
    const area = document.getElementById("newFormArea");
    const icon = document.getElementById("newFormToggleIcon");
    const visible = area.style.display !== "none";
    area.style.display = visible ? "none" : "block";
    icon.textContent = visible ? "▶" : "▼";
}

function goToProject(event, projectId) {
    window.location.href = EXPERIMENT_LIST_BASE + projectId + "/";
}

function startEdit(projectId) {
    const row = document.getElementById("proj-row-" + projectId);
    row.querySelectorAll(".proj-name-display, .proj-short-display, .proj-desc-display, .proj-ops-display")
        .forEach(el => el.style.display = "none");
    row.querySelectorAll(".proj-name-input, .proj-short-input, .proj-desc-input, .proj-ops-edit")
        .forEach(el => el.style.display = "");
}

function cancelEdit(projectId) {
    const row = document.getElementById("proj-row-" + projectId);
    row.querySelectorAll(".proj-name-display, .proj-short-display, .proj-desc-display, .proj-ops-display")
        .forEach(el => el.style.display = "");
    row.querySelectorAll(".proj-name-input, .proj-short-input, .proj-desc-input, .proj-ops-edit")
        .forEach(el => el.style.display = "none");
}

async function saveEdit(projectId) {
    const row = document.getElementById("proj-row-" + projectId);
    const name = row.querySelector(".proj-name-input").value.trim();
    const short_name = row.querySelector(".proj-short-input").value.trim();
    const description = row.querySelector(".proj-desc-input").value.trim();

    const res = await fetch(PROJECT_EDIT_BASE + projectId + "/edit/", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRFToken": CSRF_TOKEN},
        body: JSON.stringify({name, short_name, description}),
    });
    if (res.ok) {
        row.querySelector(".proj-name-display").textContent = name;
        row.querySelector(".proj-short-display").textContent = short_name;
        row.querySelector(".proj-desc-display").innerHTML = marked.parse(description);
        cancelEdit(projectId);
    } else {
        alert("保存に失敗しました");
    }
}

async function deleteProject(projectId) {
    if (!confirm("このプロジェクトと紐づく全実験を削除します。よろしいですか？")) return;
    const res = await fetch(PROJECT_DELETE_BASE + projectId + "/delete/", {
        method: "POST",
        headers: {"X-CSRFToken": CSRF_TOKEN},
    });
    if (res.ok) {
        document.getElementById("proj-row-" + projectId).remove();
    } else {
        alert("削除に失敗しました");
    }
}