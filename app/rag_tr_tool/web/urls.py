from django.urls import path
from django.shortcuts import redirect
from . import views
from . import views_api

urlpatterns = [
    path("", lambda request: redirect("project_list"), name="rag_index"),
    path("projects/", views.project_list, name="project_list"),
    path("projects/<int:project_id>/edit/", views.project_edit, name="project_edit"),
    path("projects/<int:project_id>/delete/", views.project_delete, name="project_delete"),
    path("<int:project_id>/", views.experiment_list, name="experiment_list"),
    path("<int:project_id>/new/", views.new_experiment_view, name="new_experiment"),
    path("<int:project_id>/run/", views.run_experiment, name="run_experiment"),
    path("result/<int:exp_id>/", views.result_view, name="result"),
    path("update-name/<int:exp_id>/", views.update_name, name="update_name"),
    path("check-index/", views.check_index, name="check_index"),
    path("compare/", views.compare_view, name="compare"),
    path("delete/", views.delete_experiments, name="delete_experiments"),
    path("log/<int:exp_id>/download/", views_api.download_log, name="download_log"),
    path("log/<int:exp_id>/text/", views_api.log_text, name="log_text"),
    path("toggle-star/<int:exp_id>/", views.toggle_star, name="toggle_star"),
    path("generate-answers/<int:exp_id>/", views_api.generate_answers, name="generate_answers"),
    path("rwa/", views_api.rwa_view, name="rwa"),
]