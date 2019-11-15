from django.test import TestCase
from django.contrib.auth.models import User

from .models import Project


class ProjectTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Create a user
        test_user1 = User.objects.create_user(
            username='test_user1', password='abc123')
        test_user1.save()

        # Create a project
        test_project = Project(
            name='test_project', file_name='test_project.qgs', uploaded_by=test_user1)
        test_project.save()

    def test_project_content(self):
        project = Project.objects.get(id=1)
        self.assertEqual(project.name, 'test_project')
        self.assertEqual(project.file_name, 'test_project.qgs')
        self.assertEqual(str(project.uploaded_by), 'test_user1')
