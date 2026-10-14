"""
Regression smoke tests for the dashboard / insights / completed_at fixes.

These exercise the actual views (not just the models) through Django's test
Client, so that template rendering is also covered — catching missing
template files and Django template syntax errors, not just Python logic
bugs.

Run with:
    python manage.py test apps.projects.tests
"""
import json

from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import User
from apps.projects.models import Project, Column
from apps.tasks.models import Task


class DashboardDoneTasksTests(TestCase):
    """
    Bug: 'done_tasks' on the web dashboard used to only count tasks from
    active/on_hold projects, so marking a project 'completed' made its
    finished tasks disappear from the stat. Fixed to count across all
    non-archived projects.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="regtest_owner", password="testpass123", role="owner",
        )
        self.client = Client()
        self.client.force_login(self.user)

        self.project = Project.objects.create(
            name="Regtest Project", owner=self.user,
        )
        self.project.members.add(self.user)
        for name, color, done, pos in [
            ("Backlog", "#8888aa", False, 0),
            ("A Fazer", "#5b4cf5", False, 1),
            ("Concluído", "#34d399", True, 4),
        ]:
            Column.objects.create(
                project=self.project, name=name, color=color,
                is_done_column=done, position=pos,
            )
        self.done_col = self.project.columns.get(name="Concluído")

        self.task = Task.objects.create(
            project=self.project, title="Regtest Task", created_by=self.user,
        )
        self.task.assignees.add(self.user)

    def _dashboard_stats(self):
        resp = self.client.get(reverse("projects:dashboard"))
        self.assertEqual(resp.status_code, 200)
        return resp.context["stats"]

    def test_task_update_sets_completed_at_on_done(self):
        """Moving a task to 'done' via the update view must stamp completed_at."""
        self.assertIsNone(self.task.completed_at)
        url = reverse("tasks:update", args=[self.task.pk])
        resp = self.client.post(
            url, data=json.dumps({"status": "done"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "done")
        self.assertIsNotNone(self.task.completed_at)

    def test_done_tasks_survive_project_completion(self):
        """The core regression: done_tasks stat must not drop when the
        project is marked 'completed'."""
        # Move task to done through the real view (exercises completed_at logic).
        self.client.post(
            reverse("tasks:update", args=[self.task.pk]),
            data=json.dumps({"status": "done"}),
            content_type="application/json",
        )
        stats_before = self._dashboard_stats()
        self.assertEqual(stats_before["done_tasks"], 1)

        # Mark the project as completed via the settings view.
        resp = self.client.post(
            reverse("projects:settings", args=[self.project.pk]),
            data={
                "name": self.project.name,
                "description": "",
                "color": self.project.color,
                "status": "completed",
                "members": [str(self.user.pk)],
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "completed")

        stats_after = self._dashboard_stats()
        self.assertEqual(
            stats_after["done_tasks"], 1,
            "done_tasks must still include the task after the project is completed",
        )

    def test_dashboard_stats_json_matches_dashboard(self):
        self.client.post(
            reverse("tasks:update", args=[self.task.pk]),
            data=json.dumps({"status": "done"}), content_type="application/json",
        )
        self.project.status = "completed"
        self.project.save(update_fields=["status"])

        resp = self.client.get(reverse("projects:stats_json"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["done_tasks"], 1)

    def test_archived_project_tasks_excluded(self):
        """Archived projects' done tasks should NOT count (only completed/
        active/on_hold do)."""
        self.client.post(
            reverse("tasks:update", args=[self.task.pk]),
            data=json.dumps({"status": "done"}), content_type="application/json",
        )
        self.project.status = "archived"
        self.project.save(update_fields=["status"])

        stats = self._dashboard_stats()
        self.assertEqual(stats["done_tasks"], 0)


class ProjectPageRenderTests(TestCase):
    """Smoke-test every project/task page template actually renders (200),
    catching missing-template regressions from the parallel cleanup pass."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="regtest_render", password="testpass123", role="owner",
        )
        self.client = Client()
        self.client.force_login(self.user)

        self.project = Project.objects.create(name="Render Project", owner=self.user)
        self.project.members.add(self.user)
        for name, color, done, pos in [
            ("Backlog", "#8888aa", False, 0),
            ("Concluído", "#34d399", True, 4),
        ]:
            Column.objects.create(
                project=self.project, name=name, color=color,
                is_done_column=done, position=pos,
            )
        self.done_col = self.project.columns.get(name="Concluído")
        self.archived_col = self.project.columns.get(name="Backlog")

        self.done_task = Task.objects.create(
            project=self.project, title="Done Task", created_by=self.user,
            status="done", column=self.done_col,
        )
        self.archived_task = Task.objects.create(
            project=self.project, title="Archived Task", created_by=self.user,
            status="archived", column=self.archived_col,
        )
        self.open_task = Task.objects.create(
            project=self.project, title="Open Task", created_by=self.user,
            status="todo", column=self.archived_col,
        )

    def test_dashboard_renders(self):
        resp = self.client.get(reverse("projects:dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_kanban_renders(self):
        resp = self.client.get(reverse("projects:kanban", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_task_list_renders(self):
        resp = self.client.get(reverse("projects:task_list", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_create_renders(self):
        resp = self.client.get(reverse("projects:create"))
        self.assertEqual(resp.status_code, 200)

    def test_insights_renders_and_progress_matches(self):
        self.done_task.assignees.add(self.user)
        self.open_task.assignees.add(self.user)
        resp = self.client.get(reverse("projects:insights"), {"project": str(self.project.pk)})
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        total = ctx["total_tasks"]
        done = ctx["done_count"]
        expected_rate = round(done / total * 100) if total else 0
        self.assertEqual(ctx["completion_rate"], expected_rate)

    def test_report_renders_and_progress_matches_done_total(self):
        resp = self.client.get(reverse("projects:report", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        total = ctx["total"]
        done = ctx["done"]
        expected_progress = round(done / total * 100) if total else 0
        self.assertEqual(ctx["progress"], expected_progress)
        # Archived tasks must not be counted in total (view excludes them).
        self.assertEqual(total, 2)  # done_task + open_task, archived excluded
        self.assertEqual(done, 1)

    def test_task_detail_renders(self):
        resp = self.client.get(reverse("tasks:detail", args=[self.open_task.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_my_tasks_renders(self):
        self.open_task.assignees.add(self.user)
        resp = self.client.get(reverse("tasks:my_tasks"))
        self.assertEqual(resp.status_code, 200)


class RemainingTemplateRenderTests(TestCase):
    """Covers the rest of templates/projects/ and templates/tasks/ so a
    missing-template regression (e.g. from the parallel dead-template
    cleanup) is caught as a 500/404 instead of slipping through."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="regtest_render2", password="testpass123", role="owner",
        )
        self.client = Client()
        self.client.force_login(self.user)

        self.project = Project.objects.create(name="Render Project 2", owner=self.user)
        self.project.members.add(self.user)
        Column.objects.create(
            project=self.project, name="Backlog", color="#8888aa",
            is_done_column=False, position=0,
        )
        from datetime import date
        self.task = Task.objects.create(
            project=self.project, title="Daily Report Task", created_by=self.user,
            start_date=date.today(), duration_days=3,
        )
        self.task.assignees.add(self.user)

    def test_project_list_renders(self):
        resp = self.client.get(reverse("projects:list"))
        self.assertEqual(resp.status_code, 200)

    def test_project_timeline_renders(self):
        resp = self.client.get(reverse("projects:timeline", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_project_settings_renders(self):
        resp = self.client.get(reverse("projects:settings", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_project_scope_renders(self):
        resp = self.client.get(reverse("projects:project_scope", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_project_flow_renders(self):
        resp = self.client.get(reverse("projects:flow", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_equipes_renders(self):
        resp = self.client.get(reverse("projects:equipes"))
        self.assertEqual(resp.status_code, 200)

    def test_daily_report_renders(self):
        resp = self.client.get(reverse("tasks:daily_report", args=[self.task.pk]))
        self.assertEqual(resp.status_code, 200)


class ApiDoneTasksTests(TestCase):
    """Same regression, through the mobile-facing JSON API."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="regtest_api", password="testpass123", role="owner",
        )
        self.project = Project.objects.create(name="API Regtest Project", owner=self.user)
        self.project.members.add(self.user)
        self.column_done = Column.objects.create(
            project=self.project, name="Concluído", color="#34d399",
            is_done_column=True, position=0,
        )
        self.task = Task.objects.create(
            project=self.project, title="API Task", created_by=self.user,
        )
        self.task.assignees.add(self.user)

        self.client = Client()
        login_resp = self.client.post(
            reverse("api:login"),
            data=json.dumps({"username": "regtest_api", "password": "testpass123"}),
            content_type="application/json",
        )
        self.assertEqual(login_resp.status_code, 200, login_resp.content)
        self.access = login_resp.json()["access"]
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.access}"}

    def test_task_update_sets_completed_at(self):
        url = reverse("api:task_update", args=[self.task.pk])
        resp = self.client.patch(
            url, data=json.dumps({"status": "done"}), content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "done")
        self.assertIsNotNone(self.task.completed_at)

    def test_dashboard_done_tasks_survive_completion(self):
        self.client.patch(
            reverse("api:task_update", args=[self.task.pk]),
            data=json.dumps({"status": "done"}), content_type="application/json",
            **self.auth_headers,
        )

        resp = self.client.get(reverse("api:dashboard"), **self.auth_headers)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["stats"]["done_tasks"], 1)

        # Complete the project via the API update endpoint.
        resp = self.client.patch(
            reverse("api:project_update", args=[self.project.pk]),
            data=json.dumps({"status": "completed"}), content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        resp = self.client.get(reverse("api:dashboard"), **self.auth_headers)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            resp.json()["stats"]["done_tasks"], 1,
            "API dashboard done_tasks must survive project completion",
        )
