import logging
import uuid

from django.test import TestCase

from qfieldcloud.core.job_results import (
    apply_delta_results,
    get_job_command,
    prepare_deltafile,
)
from qfieldcloud.core.models import ApplyJob, ApplyJobDelta, Delta, Job, Person
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user = Person.objects.create_user(username="user1", password="abc123")
        set_subscription(self.user)
        self.project = Project.objects.create(name="p1", owner=self.user)
        self.job = ApplyJob.objects.create(
            project=self.project, created_by=self.user, overwrite_conflicts=True
        )

    def _delta(self, content: dict | None = None, **kwargs) -> Delta:
        return Delta.objects.create(
            deltafile_id=uuid.uuid4(),
            project=self.project,
            content=content or {},
            client_id=kwargs.pop("client_id", uuid.uuid4()),
            created_by=self.user,
            **kwargs,
        )

    def _job_delta(self, **kwargs) -> Delta:
        delta = self._delta(**kwargs)
        ApplyJobDelta.objects.create(
            apply_job=self.job, delta=delta, status=Delta.Status.PENDING
        )

        return delta

    def _set_feedback(self, *deltas_and_statuses: tuple[Delta, str]) -> None:
        self.job.feedback = {
            "outputs": {
                "apply_deltas": {
                    "delta_feedback": [
                        {
                            "delta_id": str(delta.pk),
                            "status": status,
                            "modified_pk": "1",
                        }
                        for delta, status in deltas_and_statuses
                    ]
                }
            }
        }

    def test_applied_delta_updates_delta_and_project(self):
        delta = self._job_delta()
        self._set_feedback((delta, "status_applied"))

        apply_delta_results(self.job)

        delta.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(delta.last_status, Delta.Status.APPLIED)
        self.assertEqual(delta.last_modified_pk, "1")
        self.assertEqual(delta.last_apply_attempt_by, self.user)
        self.assertIsNotNone(self.project.data_last_updated_at)

    def test_conflict_does_not_mark_the_data_as_modified(self):
        delta = self._job_delta()
        self._set_feedback((delta, "status_conflict"))

        apply_delta_results(self.job)

        delta.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(delta.last_status, Delta.Status.CONFLICT)
        self.assertIsNone(self.project.data_last_updated_at)

    def test_unknown_status_becomes_error(self):
        delta = self._job_delta()
        self._set_feedback((delta, "status_something_else"))

        apply_delta_results(self.job)

        delta.refresh_from_db()
        self.assertEqual(delta.last_status, Delta.Status.ERROR)

    def test_feedback_cannot_change_deltas_of_other_jobs(self):
        other_delta = self._delta()
        self._set_feedback((other_delta, "status_applied"))

        apply_delta_results(self.job)

        other_delta.refresh_from_db()
        self.assertEqual(other_delta.last_status, Delta.Status.PENDING)
        self.assertIsNone(other_delta.last_feedback)

    def test_prepare_deltafile_starts_the_deltas_of_the_job(self):
        delta = self._job_delta(content={"uuid": "1"})
        other_delta = self._delta()

        deltafile = prepare_deltafile(self.job)

        delta.refresh_from_db()
        other_delta.refresh_from_db()
        self.assertEqual(deltafile["deltas"], [{"uuid": "1"}])
        self.assertEqual(deltafile["project"], str(self.project.id))
        self.assertEqual(delta.last_status, Delta.Status.STARTED)
        self.assertEqual(other_delta.last_status, Delta.Status.PENDING)

    def test_prepare_deltafile_maps_local_to_remote_primary_keys(self):
        client_id = uuid.uuid4()
        self._delta(
            content={"clientId": str(client_id), "localLayerId": "l", "localPk": "2"},
            client_id=client_id,
            last_modified_pk="99",
        )
        self._job_delta(content={"clientId": str(client_id)}, client_id=client_id)

        deltafile = prepare_deltafile(self.job)

        self.assertEqual(deltafile["clientPks"], {f"{client_id}__l__2": "99"})

    def test_delta_command_passes_overwrite_conflicts(self):
        command = get_job_command(self.job)

        self.assertEqual(command[:2], ["apply_deltas", str(self.project.id)])
        self.assertEqual(command[-1], "--overwrite-conflicts")

    def test_create_project_command(self):
        job = Job.objects.create(
            project=self.project, type=Job.Type.CREATE_PROJECT, created_by=self.user
        )

        self.assertEqual(get_job_command(job), ["create_project", str(self.project.id)])
