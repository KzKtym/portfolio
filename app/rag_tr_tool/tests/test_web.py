"""層A: web 層（views / views_api / services / context_processors）。

core はモックし、境界の受け渡しと HTTP の応答を検証する。
実験実行経路が通らないコード（generate_answers / compare / rwa）に不整合が溜まっていたため、
ここは実際に URL を叩いて確認する。
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from app.rag_tr_tool.models import Experiment, RagProject
from app.rag_tr_tool.web.services import context_service, data_service, llm_service, run_service


def make_project(**kwargs):
    defaults = {"name": "PJ", "short_name": "P", "description": ""}
    return RagProject.objects.create(**{**defaults, **kwargs})


def make_experiment(project, **kwargs):
    defaults = {
        "name": "実験",
        "mrr": 0.5,
        "recall_at_5": 1.0,
        "parameters": {"top_k": 5},
        "spec_snapshot": "* Spec",
        "project": project,
    }
    return Experiment.objects.create(**{**defaults, **kwargs})


class ProjectViewTest(TestCase):
    def test_project_list_renders(self):
        make_project(name="表示用PJ")
        res = self.client.get(reverse("project_list"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "表示用PJ")

    def test_project_create_via_post(self):
        with patch.object(__import__(
            "app.rag_tr_tool.web.views", fromlist=["views"]), "_init_project_dirs"):
            res = self.client.post(reverse("project_list"),
                                   {"name": "新PJ", "short_name": "N", "description": "説明"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(RagProject.objects.filter(name="新PJ").exists())

    def test_project_create_requires_name_and_short_name(self):
        # 0004_init_default_project が既定プロジェクトを1件作るため、増分で判定する
        before = RagProject.objects.count()
        self.client.post(reverse("project_list"), {"name": "", "short_name": ""})
        self.assertEqual(RagProject.objects.count(), before)

    def test_project_edit(self):
        project = make_project()
        res = self.client.post(
            reverse("project_edit", args=[project.id]),
            data=json.dumps({"name": "変更後", "short_name": "X", "description": "d"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.name, "変更後")

    def test_project_edit_rejects_get(self):
        project = make_project()
        self.assertEqual(self.client.get(reverse("project_edit", args=[project.id])).status_code, 405)

    def test_project_delete_cascades_experiments(self):
        project = make_project()
        make_experiment(project)
        res = self.client.post(reverse("project_delete", args=[project.id]))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Experiment.objects.exists())

    def test_project_delete_missing_returns_404(self):
        self.assertEqual(self.client.post(reverse("project_delete", args=[999])).status_code, 404)


class RunExperimentViewTest(TestCase):
    def setUp(self):
        self.project = make_project()

    def test_get_redirects_to_new(self):
        res = self.client.get(reverse("run_experiment", args=[self.project.id]))
        self.assertRedirects(res, reverse("new_experiment", args=[self.project.id]),
                             fetch_redirect_response=False)

    def test_empty_parameters_does_not_run(self):
        with patch.object(run_service, "run_evaluation") as mock_run:
            res = self.client.post(reverse("run_experiment", args=[self.project.id]),
                                   {"parameters": "{}"})
        mock_run.assert_not_called()
        self.assertEqual(res.status_code, 302)

    def test_invalid_json_does_not_run(self):
        with patch.object(run_service, "run_evaluation") as mock_run:
            self.client.post(reverse("run_experiment", args=[self.project.id]),
                             {"parameters": "not json"})
        mock_run.assert_not_called()

    def test_failure_does_not_create_experiment(self):
        # 失敗を mrr=0.0 の実験として保存しない
        err = {"status": "error", "error": "boom", "error_type": "ValueError", "meta": {}}
        with patch.object(run_service, "run_evaluation", return_value=err):
            res = self.client.post(reverse("run_experiment", args=[self.project.id]),
                                   {"parameters": json.dumps({"top_k": 5}), "name": "実験"})
        self.assertEqual(Experiment.objects.count(), 0)
        self.assertRedirects(res, reverse("new_experiment", args=[self.project.id]),
                             fetch_redirect_response=False)

    def test_failure_surfaces_error_message(self):
        err = {"status": "error", "error": "boom", "error_type": "ValueError", "meta": {}}
        with patch.object(run_service, "run_evaluation", return_value=err):
            res = self.client.post(reverse("run_experiment", args=[self.project.id]),
                                   {"parameters": json.dumps({"top_k": 5}), "name": "実験"},
                                   follow=True)
        body = res.content.decode()
        self.assertIn("ValueError", body)
        self.assertIn("boom", body)

    def test_success_creates_experiment_and_renders_result(self):
        ok = {
            "status": "success",
            "metrics": {"mrr": 0.8, "recall_at_5": 1.0},
            "meta": {"query_count": 1, "total_chunks": 10,
                     "index_creation_time": "0:00:01", "evaluation_time_sec": 1.0},
            "details": [], "rwa_queries": [],
        }
        with patch.object(run_service, "run_evaluation", return_value=ok), \
             patch.object(run_service, "save_log"), \
             patch.object(run_service, "save_details_json"), \
             patch.object(run_service, "resolve_spec", return_value="* Spec"):
            res = self.client.post(reverse("run_experiment", args=[self.project.id]),
                                   {"parameters": json.dumps({"top_k": 5}), "name": "実験A"})
        self.assertEqual(res.status_code, 200)
        exp = Experiment.objects.get()
        self.assertEqual(exp.name, "実験A")
        self.assertAlmostEqual(exp.mrr, 0.8)


class RunExperimentServiceTest(TestCase):
    def setUp(self):
        self.project = make_project()

    def test_error_result_returns_not_ok(self):
        err = {"status": "error", "error": "boom", "error_type": "ValueError", "meta": {}}
        with patch.object(run_service, "run_evaluation", return_value=err):
            out = run_service.run_experiment_service("n", {"top_k": 5}, False, self.project.id)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_type"], "ValueError")
        self.assertEqual(Experiment.objects.count(), 0)

    def test_success_returns_ok_and_message(self):
        ok = {
            "status": "success",
            "metrics": {"mrr": 0.8, "recall_at_5": 1.0},
            "meta": {}, "details": [], "rwa_queries": [],
        }
        with patch.object(run_service, "run_evaluation", return_value=ok), \
             patch.object(run_service, "save_log"), \
             patch.object(run_service, "save_details_json"), \
             patch.object(run_service, "resolve_spec", return_value="* Spec"):
            out = run_service.run_experiment_service("n", {"top_k": 5}, False, self.project.id)
        self.assertTrue(out["ok"])
        self.assertTrue(out["has_log"])
        self.assertEqual(out["message"], "実行完了（保存OK）")


class ExperimentListViewTest(TestCase):
    def setUp(self):
        self.project = make_project()

    def test_renders(self):
        make_experiment(self.project, name="一覧の実験")
        with patch.object(context_service, "read_log", return_value=None), \
             patch.object(context_service, "read_details_json", return_value=None):
            res = self.client.get(reverse("experiment_list", args=[self.project.id]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "一覧の実験")

    def test_sort_order_query_count_then_mrr(self):
        low = make_experiment(self.project, mrr=0.9)
        high = make_experiment(self.project, mrr=0.1)
        details = {str(high.id): {"meta": {"query_count": 10}},
                   str(low.id): {"meta": {"query_count": 1}}}
        with patch.object(context_service, "read_log", return_value=None), \
             patch.object(context_service, "read_details_json",
                          side_effect=lambda exp_id, project_id: details[str(exp_id)]):
            experiments = context_service.get_experiment_list(self.project.id)
        # QRY 降順が最優先。MRR が低くても query_count が多い方が先
        self.assertEqual([e.id for e in experiments], [high.id, low.id])

    def test_icons_assigned_to_newest_three(self):
        exps = [make_experiment(self.project) for _ in range(4)]
        with patch.object(context_service, "read_log", return_value=None), \
             patch.object(context_service, "read_details_json", return_value=None):
            listed = {e.id: e.icon for e in context_service.get_experiment_list(self.project.id)}
        self.assertEqual(listed[exps[3].id], "new")
        self.assertEqual(listed[exps[2].id], "1st")
        self.assertEqual(listed[exps[1].id], "2nd")
        self.assertEqual(listed[exps[0].id], "")


class DeleteAndToggleTest(TestCase):
    def setUp(self):
        self.project = make_project()
        self.exp = make_experiment(self.project)

    def test_toggle_star(self):
        res = self.client.post(reverse("toggle_star", args=[self.exp.id]))
        self.assertJSONEqual(res.content, {"starred": True})
        self.exp.refresh_from_db()
        self.assertTrue(self.exp.is_starred)

    def test_toggle_star_missing_returns_404(self):
        self.assertEqual(self.client.post(reverse("toggle_star", args=[999])).status_code, 404)

    def test_toggle_star_rejects_get(self):
        self.assertEqual(self.client.get(reverse("toggle_star", args=[self.exp.id])).status_code, 405)

    def test_update_name(self):
        self.client.post(reverse("update_name", args=[self.exp.id]),
                         data=json.dumps({"name": "改名"}), content_type="application/json")
        self.exp.refresh_from_db()
        self.assertEqual(self.exp.name, "改名")

    def test_delete_experiments(self):
        with patch.object(data_service, "get_logs_dir", return_value=Path("/nonexistent")):
            res = self.client.post(reverse("delete_experiments"),
                                   {"ids": str(self.exp.id), "project_id": self.project.id})
        self.assertEqual(res.status_code, 302)
        self.assertFalse(Experiment.objects.exists())

    def test_delete_ignores_missing_ids(self):
        with patch.object(data_service, "get_logs_dir", return_value=Path("/nonexistent")):
            data_service.delete_experiments_service([str(self.exp.id), "9999"])
        self.assertFalse(Experiment.objects.exists())


class CompareViewTest(TestCase):
    def setUp(self):
        self.project = make_project()
        self.a = make_experiment(self.project, mrr=0.4, spec_snapshot="* A\n* 共通")
        self.b = make_experiment(self.project, mrr=0.6, spec_snapshot="* B\n* 共通")

    def test_requires_two_ids(self):
        res = self.client.get(reverse("compare"), {"ids": [self.a.id]})
        self.assertRedirects(res, reverse("project_list"), fetch_redirect_response=False)

    def test_renders_with_two_ids(self):
        with patch.object(data_service, "read_rwa_json", return_value=None):
            res = self.client.get(reverse("compare"), {"ids": [self.a.id, self.b.id]})
        self.assertEqual(res.status_code, 200)

    def test_spec_diff_marks_changes(self):
        with patch.object(data_service, "read_rwa_json", return_value=None):
            data = data_service.build_compare_data(self.a.id, self.b.id)
        self.assertIn("- * A", data["spec_diff"])
        self.assertIn("+ * B", data["spec_diff"])
        self.assertIn("  * 共通", data["spec_diff"])

    def test_metric_diffs(self):
        with patch.object(data_service, "read_rwa_json", return_value=None):
            data = data_service.build_compare_data(self.a.id, self.b.id)
        self.assertAlmostEqual(data["mrr_diff"], 0.2)

    def test_param_comparison_flags_difference(self):
        self.a.parameters = {"top_k": 5}
        self.a.save()
        self.b.parameters = {"top_k": 10}
        self.b.save()
        with patch.object(data_service, "read_rwa_json", return_value=None):
            data = data_service.build_compare_data(self.a.id, self.b.id)
        row = next(r for r in data["param_comparison"] if r["key"] == "top_k")
        self.assertTrue(row["is_diff"])

    def test_rwa_reason_uses_query_option_key(self):
        # 保存キーは query_option。query_rewrite を見ていた頃は常に「未指定」になっていた
        self.a.parameters = {"query_option": "rewrite"}
        self.a.save()
        with patch.object(data_service, "read_rwa_json", return_value=None):
            data = data_service.build_compare_data(self.a.id, self.b.id)
        reasons = " ".join(data["rwa_disabled_reasons"])
        self.assertIn(f"Exp {self.a.id}: Rewriteデータなし", reasons)
        self.assertIn(f"Exp {self.b.id}: query_option 未指定", reasons)

    def test_rwa_button_shown_when_both_have_data(self):
        with patch.object(data_service, "read_rwa_json", return_value=[{"query": "Q"}]):
            data = data_service.build_compare_data(self.a.id, self.b.id)
        self.assertTrue(data["show_rwa_btn"])
        self.assertEqual(data["rwa_disabled_reasons"], [])


class RwaViewTest(TestCase):
    def setUp(self):
        self.project = make_project()
        self.plain = make_experiment(self.project, parameters={"top_k": 5})
        self.rewrite = make_experiment(self.project, parameters={"query_option": "rewrite"})

    def test_requires_both_ids(self):
        res = self.client.get(reverse("rwa"), {"id_a": self.plain.id})
        self.assertEqual(res.status_code, 400)

    def test_rewrite_side_is_placed_right(self):
        # query_option 指定側が右（label_b）に来る
        with patch("app.rag_tr_tool.web.views_api.read_rwa_json", return_value=[]):
            res = self.client.get(reverse("rwa"),
                                  {"id_a": self.rewrite.id, "id_b": self.plain.id})
        body = res.json()
        self.assertEqual(body["label_a"], f"{self.plain.id}:false")
        self.assertEqual(body["label_b"], f"{self.rewrite.id}:true")

    def test_multi_is_treated_as_rewrite_side(self):
        multi = make_experiment(self.project, parameters={"query_option": "multi"})
        with patch("app.rag_tr_tool.web.views_api.read_rwa_json", return_value=[]):
            res = self.client.get(reverse("rwa"), {"id_a": self.plain.id, "id_b": multi.id})
        self.assertEqual(res.json()["label_b"], f"{multi.id}:true")

    def test_same_flag_sorts_by_id(self):
        other = make_experiment(self.project, parameters={"top_k": 5})
        with patch("app.rag_tr_tool.web.views_api.read_rwa_json", return_value=[]):
            res = self.client.get(reverse("rwa"), {"id_a": other.id, "id_b": self.plain.id})
        self.assertEqual(res.json()["label_a"], f"{self.plain.id}:false")

    def test_missing_experiment_falls_back(self):
        with patch("app.rag_tr_tool.web.views_api.read_rwa_json", return_value=None):
            res = self.client.get(reverse("rwa"), {"id_a": 9999, "id_b": self.plain.id})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["has_rwa_a"])


class GenerateAnswersViewTest(TestCase):
    def setUp(self):
        self.project = make_project()
        self.exp = make_experiment(self.project)

    def test_rejects_get(self):
        res = self.client.get(reverse("generate_answers", args=[self.exp.id]))
        self.assertEqual(res.status_code, 405)

    def test_missing_experiment_returns_404(self):
        res = self.client.post(reverse("generate_answers", args=[9999]))
        self.assertEqual(res.status_code, 404)

    def test_returns_answers(self):
        with patch.object(__import__(
                "app.rag_tr_tool.web.views_api", fromlist=["views_api"]).services,
                "generate_answers_service",
                return_value={"answers": [{"query": "Q", "answer": "A"}]}):
            res = self.client.post(reverse("generate_answers", args=[self.exp.id]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["answers"][0]["answer"], "A")

    def test_propagates_service_status(self):
        with patch.object(__import__(
                "app.rag_tr_tool.web.views_api", fromlist=["views_api"]).services,
                "generate_answers_service",
                return_value={"error": "rate limit", "answers": [], "status": 502}):
            res = self.client.post(reverse("generate_answers", args=[self.exp.id]))
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json()["error"], "rate limit")


class GenerateAnswersServiceTest(TestCase):
    """A・B（query_rewrite 参照と 4要素タプル）で全経路が AttributeError だった箇所。"""

    def setUp(self):
        self.project = make_project()

    def _results(self):
        return [{"rank": 1, "score": 0.9, "text": "本文",
                 "metadata": {"source": "s0.md"}}]

    def _run(self, parameters):
        exp = make_experiment(self.project, parameters=parameters)
        retriever = MagicMock()
        retriever.search.return_value = self._results()
        with patch.object(llm_service, "build_index",
                          return_value=(MagicMock(), MagicMock(), 0.0)), \
             patch.object(llm_service, "Retriever", return_value=retriever), \
             patch.object(llm_service, "read_details_json",
                          return_value={"details": [{"query": "質問"}]}), \
             patch.object(llm_service, "rewrite_query", return_value="言い換え"), \
             patch.object(llm_service, "generate_queries", return_value=["q1"]), \
             patch.object(llm_service, "generate_answer", return_value="回答"), \
             patch.object(llm_service, "save_answers_json"):
            return llm_service.generate_answers_service(exp.id)

    def test_plain_path(self):
        self.assertEqual(self._run({"top_k": 5})["answers"][0]["answer"], "回答")

    def test_rewrite_path(self):
        self.assertEqual(self._run({"query_option": "rewrite"})["answers"][0]["answer"], "回答")

    def test_legacy_true_value_is_treated_as_rewrite(self):
        self.assertEqual(self._run({"query_option": "true"})["answers"][0]["answer"], "回答")

    def test_multi_path(self):
        self.assertEqual(self._run({"query_option": "multi"})["answers"][0]["answer"], "回答")

    def test_multi_with_normalized_gate(self):
        params = {"query_option": "multi", "gate_score": "normalized", "gate_mode": "top1"}
        self.assertEqual(self._run(params)["answers"][0]["answer"], "回答")

    def test_missing_details_returns_404_payload(self):
        exp = make_experiment(self.project)
        with patch.object(llm_service, "build_index",
                          return_value=(MagicMock(), MagicMock(), 0.0)), \
             patch.object(llm_service, "Retriever", return_value=MagicMock()), \
             patch.object(llm_service, "read_details_json", return_value=None):
            out = llm_service.generate_answers_service(exp.id)
        self.assertEqual(out["status"], 404)


class ContextProcessorTest(TestCase):
    def test_returns_project_for_url_with_project_id(self):
        project = make_project(name="対象PJ", description="あ" * 100)
        with patch.object(context_service, "read_log", return_value=None), \
             patch.object(context_service, "read_details_json", return_value=None):
            res = self.client.get(reverse("experiment_list", args=[project.id]))
        self.assertEqual(res.context["current_project"], project)

    def test_description_preview_is_truncated(self):
        project = make_project(description="あ" * 100)
        ctx = context_service.get_current_project_context(project.id)
        self.assertEqual(len(ctx["project_description_preview"]), 40)

    def test_none_project_id_returns_empty_context(self):
        ctx = context_service.get_current_project_context(None)
        self.assertIsNone(ctx["current_project"])
        self.assertEqual(ctx["project_description_preview"], "")

    def test_missing_project_returns_empty_context(self):
        ctx = context_service.get_current_project_context(9999)
        self.assertIsNone(ctx["current_project"])

    def test_url_without_project_id_has_no_current_project(self):
        res = self.client.get(reverse("project_list"))
        self.assertIsNone(res.context["current_project"])


class LogApiTest(TestCase):
    def setUp(self):
        self.project = make_project()
        self.exp = make_experiment(self.project)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.logs_dir = Path(self._tmp.name)

    def test_log_text_returns_404_when_no_data(self):
        with patch("app.rag_tr_tool.web.views_api.read_details_json", return_value=None):
            res = self.client.get(reverse("log_text", args=[self.exp.id]))
        self.assertEqual(res.status_code, 404)

    def test_log_text_returns_plain_text(self):
        saved = {"details": [{"query": "Q", "correct_rank": 1, "mrr": 1.0,
                              "results": [{"rank": 1, "score": 0.9, "source": "s0.md"}]}],
                 "meta": {"total_chunks": 5}}
        with patch("app.rag_tr_tool.web.views_api.read_details_json", return_value=saved):
            res = self.client.get(reverse("log_text", args=[self.exp.id]))
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/plain", res["Content-Type"])
        self.assertIn("Query 1: Q", res.content.decode())

    def test_log_text_format2(self):
        saved = {"details": [{"query": "Q", "correct_rank": 1, "mrr": 1.0,
                              "results": [{"rank": 1, "score": 0.9,
                                           "source": "s0.md", "text": "本文X"}]}],
                 "meta": {}}
        with patch("app.rag_tr_tool.web.views_api.read_details_json", return_value=saved):
            res = self.client.get(reverse("log_text", args=[self.exp.id]), {"fmt": "2"})
        self.assertIn("本文X", res.content.decode())

    def test_download_log_404_when_missing(self):
        with patch("app.rag_tr_tool.web.views_api.get_logs_dir", return_value=self.logs_dir):
            res = self.client.get(reverse("download_log", args=[self.exp.id]))
        self.assertEqual(res.status_code, 404)

    def test_download_log_returns_attachment(self):
        (self.logs_dir / f"exp_{self.exp.id}.log").write_text("ログ", encoding="utf-8")
        with patch("app.rag_tr_tool.web.views_api.get_logs_dir", return_value=self.logs_dir):
            res = self.client.get(reverse("download_log", args=[self.exp.id]))
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res["Content-Disposition"])


class CheckIndexTest(TestCase):
    def test_post_returns_index_info(self):
        with patch.object(data_service, "get_index_info", return_value={"exists": True}), \
             patch.object(data_service, "resolve_spec", return_value="* Spec"):
            res = self.client.post(reverse("check_index"),
                                   data=json.dumps({"chunk_size": 500, "project_id": 1}),
                                   content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["exists"])
        self.assertEqual(res.json()["spec_text"], "* Spec")

    def test_get_returns_not_exists(self):
        res = self.client.get(reverse("check_index"))
        self.assertFalse(res.json()["exists"])


class ResultViewTest(TestCase):
    def setUp(self):
        self.project = make_project()
        self.exp = make_experiment(self.project)

    def test_renders(self):
        with patch.object(context_service, "read_details_json", return_value=None), \
             patch.object(context_service, "read_answers_json", return_value=None), \
             patch.object(context_service, "read_rwa_json", return_value=None):
            res = self.client.get(reverse("result", args=[self.exp.id]))
        self.assertEqual(res.status_code, 200)

    def test_mrr_fallback_for_legacy_details(self):
        saved = {"details": [{"query": "Q", "correct_rank": 4,
                              "results": []}], "meta": {}}
        with patch.object(context_service, "read_details_json", return_value=saved), \
             patch.object(context_service, "read_answers_json", return_value=None), \
             patch.object(context_service, "read_rwa_json", return_value=None):
            data = context_service.get_result_data(self.exp.id)
        self.assertAlmostEqual(data["details"][0]["mrr"], 0.25)

    def test_has_answers_flag(self):
        with patch.object(context_service, "read_details_json", return_value=None), \
             patch.object(context_service, "read_answers_json", return_value=[{"q": "a"}]), \
             patch.object(context_service, "read_rwa_json", return_value=None):
            data = context_service.get_result_data(self.exp.id)
        self.assertTrue(data["has_answers"])


class NewExperimentContextTest(TestCase):
    def setUp(self):
        self.project = make_project()

    def test_defaults_when_no_experiment(self):
        with patch.object(context_service, "get_index_info", return_value={"exists": False}), \
             patch.object(context_service, "resolve_spec", return_value="* Spec"):
            data = context_service.get_new_experiment_context(None, self.project.id)
        params = json.loads(data["last_params_json"])
        self.assertEqual(params["chunker"], "langchain")
        self.assertEqual(data["last_name"], "")

    def test_uses_last_experiment_params(self):
        make_experiment(self.project, parameters={"top_k": 9}, name="直近")
        with patch.object(context_service, "get_index_info", return_value={"exists": False}), \
             patch.object(context_service, "resolve_spec", return_value="* Spec"):
            data = context_service.get_new_experiment_context(None, self.project.id)
        self.assertEqual(json.loads(data["last_params_json"])["top_k"], 9)
        self.assertEqual(data["last_name"], "直近")

    def test_params_from_list_override(self):
        make_experiment(self.project, parameters={"top_k": 9})
        with patch.object(context_service, "get_index_info", return_value={"exists": False}), \
             patch.object(context_service, "resolve_spec", return_value="* Spec"):
            data = context_service.get_new_experiment_context(
                json.dumps({"top_k": 3}), self.project.id)
        self.assertEqual(json.loads(data["last_params_json"])["top_k"], 3)

    def test_params_from_list_without_any_experiment(self):
        with patch.object(context_service, "get_index_info", return_value={"exists": False}), \
             patch.object(context_service, "resolve_spec", return_value="* Spec"):
            data = context_service.get_new_experiment_context(
                json.dumps({"top_k": 3}), self.project.id)
        self.assertEqual(data["last_name"], "")
