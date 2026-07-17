"""context_processors.py - 全テンプレートに現在選択中のプロジェクト情報を供給する"""
from app.rag_tr_tool.web.services import get_current_project_context


def current_project(request):
    """現在のURLからproject_idを取得し、プロジェクト情報をテンプレートに渡す。

    URLにproject_idが含まれない画面（result/, compare/等）では
    current_project=None、project_description_preview="" を返す。
    """
    project_id = None
    if hasattr(request, "resolver_match") and request.resolver_match:
        raw = request.resolver_match.kwargs.get("project_id")
        if raw is not None:
            try:
                project_id = int(raw)
            except (ValueError, TypeError):
                project_id = None

    return get_current_project_context(project_id)
