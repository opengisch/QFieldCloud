import os
import shutil
import filecmp
import tempfile

from shutil import copyfile
from unittest import skip

from django.test import TestCase
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from projects.models import Project, ProjectRole

from .. import permissions


settings.PROJECTS_ROOT += '_test'


def testdata_path(path):
    basepath = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(basepath, 'testdata', path)


class ProjectTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        pass

    def setUp(self):
        # Insert a user into the db
        self.test_user1 = get_user_model().objects.create_user(
            username='test_user1', password='abc123')
        self.test_user1.save()
        self.token = Token.objects.get_or_create(user=self.test_user1)[0]

        # Insert a second user into the db
        self.test_user2 = get_user_model().objects.create_user(
            username='test_user2', password='abc123')
        self.test_user2.save()
        self.token2 = Token.objects.get_or_create(user=self.test_user2)[0]

        # Insert a third user into the db
        self.test_user3 = get_user_model().objects.create_user(
            username='test_user3', password='abc123')
        self.test_user3.save()
        self.token3 = Token.objects.get_or_create(user=self.test_user3)[0]

        # Insert a public project into the db
        self.test_project1 = Project(
            name='test_project1',
            description='Test project 1',
            homepage='http://test_project1.com',
            private=False,
            owner=self.test_user1)
        self.test_project1.save()

        # Insert another public project into the db
        self.test_project2 = Project(
            name='test_project2',
            description='Test project 2',
            homepage='http://test_project2.com',
            private=False,
            owner=self.test_user1)
        self.test_project2.save()

        # Add 2 files to the project2
        filename1 = os.path.join(
            settings.PROJECTS_ROOT,
            'test_user1',
            'test_project2',
            'file.txt')

        filename2 = os.path.join(
            settings.PROJECTS_ROOT,
            'test_user1',
            'test_project2',
            'file2.txt')

        os.makedirs(os.path.dirname(filename1), exist_ok=True)

        copyfile(testdata_path('file.txt'), filename1)
        copyfile(testdata_path('file2.txt'), filename2)

        # Insert a private project into the db
        self.test_project3 = Project(
            name='test_project3',
            description='Test project 3',
            homepage='http://test_project3.com',
            private=True,
            owner=self.test_user1)
        self.test_project3.save()

    def tearDown(self):
        Project.objects.all().delete()
        get_user_model().objects.all().delete()
        # Remove credentials
        self.client.credentials()

        # Remove test's PROJECTS_ROOT
        shutil.rmtree(settings.PROJECTS_ROOT, ignore_errors=True)

    def test_project_content(self):
        project = Project.objects.get(id=1)
        self.assertEqual(project.name, 'test_project1')
        self.assertEqual(project.description, 'Test project 1')
        self.assertEqual(project.homepage, 'http://test_project1.com')
        self.assertFalse(project.private)
        self.assertEqual(str(project.owner), 'test_user1')

    def test_list_public_projects_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        response = self.client.get('/api/v1/projects/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 2)
        self.assertTrue(
            response.data[0]['name'] in ['test_project1', 'test_project2'])
        self.assertTrue(
            response.data[1]['name'] in ['test_project1', 'test_project2'])

    def test_list_user_projects_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        response = self.client.get('/api/v1/projects/test_user1/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 3)

    def test_create_user_project_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        response = self.client.post(
            '/api/v1/projects/test_user1/',
            {
                'name': 'api_created_project',
                'description': 'desc',
                'homepage': 'http://perdu.com',
                'private': True,
            }
        )

        self.assertTrue(status.is_success(response.status_code))

        project = Project.objects.get(name='api_created_project')
        # Will raise exception if donesn't exist

        self.assertEqual(str(project.owner), 'test_user1')

    def test_push_file_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/test_user1/test_project1/push/',
            {
                "file_content": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Check if the file is actually stored in the correct position
        stored_file = os.path.join(
            settings.PROJECTS_ROOT,
            'test_user1',
            'test_project1',
            'file.txt')
        self.assertTrue(os.path.isfile(stored_file))

        # Check if file content is still the same
        self.assertTrue(filecmp.cmp(file_path, stored_file))

    def test_push_multiple_files_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        file_path = testdata_path('file.txt')
        file_path2 = testdata_path('file2.txt')

        # Push the files
        response = self.client.post(
            '/api/v1/projects/test_user1/test_project1/push/',
            {
                "file_content": [open(file_path, 'rb'), open(file_path2, 'rb')]
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Check if the files are actually stored in the correct position
        stored_file = os.path.join(
            settings.PROJECTS_ROOT,
            'test_user1',
            'test_project1',
            'file.txt')
        self.assertTrue(os.path.isfile(stored_file))
        stored_file2 = os.path.join(
            settings.PROJECTS_ROOT,
            'test_user1',
            'test_project1',
            'file2.txt')
        self.assertTrue(os.path.isfile(stored_file2))

        # Check if files content is still the same
        self.assertTrue(filecmp.cmp(file_path, stored_file))
        self.assertTrue(filecmp.cmp(file_path2, stored_file2))

    def test_pull_file_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # Pull the file
        response = self.client.get(
            '/api/v1/projects/test_user1/test_project2/file.txt/')
        self.assertTrue(status.is_success(response.status_code))

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'file.txt')
        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path('file.txt')))

    def test_get_files_list_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # Pull the file
        response = self.client.get(
            '/api/v1/projects/test_user1/test_project2/files/')
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.json()[0]['name'], 'file.txt')
        self.assertEqual(response.json()[1]['name'], 'file2.txt')
        self.assertEqual(response.json()[0]['size'], 13)
        self.assertEqual(response.json()[1]['size'], 13)
        self.assertEqual(
            response.json()[0]['sha256'],
            '8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d')
        self.assertEqual(
            response.json()[1]['sha256'],
            'fcc85fb502bd772aa675a0263b5fa665bccd5d8d93349d1dbc9f0f6394dd37b9')

    def test_delete_file_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # The file exists
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    settings.PROJECTS_ROOT,
                    'test_user1',
                    'test_project2',
                    'file.txt')))

        # Delete the file
        response = self.client.delete(
            '/api/v1/projects/test_user1/test_project2/file.txt/')
        self.assertTrue(status.is_success(response.status_code))

        # The file doesn't exist
        self.assertFalse(
            os.path.isfile(
                os.path.join(
                    settings.PROJECTS_ROOT,
                    'test_user1',
                    'test_project2',
                    'file.txt')))

    def test_add_collaborator_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        self.assertFalse(ProjectRole.objects.all())
        response = self.client.post(
            '/api/v1/projects/test_user1/test_project1/collaborators/test_user2/',
            {
                "role": "reader",
            }
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(ProjectRole.objects.all())

        self.assertEqual(
            ProjectRole.objects.all()[0].user.username, 'test_user2')
        self.assertEqual(
            ProjectRole.objects.all()[0].project.name, 'test_project1')
        self.assertEqual(
            ProjectRole.objects.all()[0].role,
            settings.PROJECT_ROLE['reader'])

    def test_list_collaborators_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # Create 2 permissions on test_project1
        self.assertFalse(ProjectRole.objects.all())
        self.client.post(
            '/api/v1/projects/test_user1/test_project1/collaborators/test_user2/',
            {
                "role": "admin",
            }
        )

        self.client.post(
            '/api/v1/projects/test_user1/test_project1/collaborators/test_user3/',
            {
                "role": "editor",
            }
        )

        # Ask for the collaborators list
        response = self.client.get(
            '/api/v1/projects/test_user1/test_project1/collaborators/')

        self.assertEqual(response.json()[0], ['test_user2', 'admin'])
        self.assertEqual(response.json()[1], ['test_user3', 'editor'])

    def test_is_project_owner(self):

        self.assertTrue(permissions.is_project_owner('test_user1', 'test_project1'))
        self.assertFalse(permissions.is_project_owner('test_user2', 'test_project1'))
        self.assertFalse(permissions.is_project_owner('test_user2', 'test_project2'))

    def test_is_project_admin(self):

        # If it's owner, then can admin
        self.assertTrue(permissions.is_project_admin('test_user1', 'test_project1'))

        # test_user2 cannot admin
        self.assertFalse(permissions.is_project_admin('test_user2', 'test_project1'))

        # Lets define test_user2 as admin
        ProjectRole.objects.create(
            user=self.test_user2,
            project=self.test_project1,
            role=settings.PROJECT_ROLE['admin'])

        # Now should be allowed to admin
        self.assertTrue(permissions.is_project_admin('test_user2', 'test_project1'))

        # Lets set write permission to test_user3
        ProjectRole.objects.create(
            user=self.test_user3,
            project=self.test_project1,
            role=settings.PROJECT_ROLE['editor'])

        # Should not be allowed to admin
        self.assertFalse(permissions.is_project_admin('test_user3', 'test_project1'))

    def test_is_project_manager(self):
        # If it's owner, then is also manager
        self.assertTrue(permissions.is_project_manager('test_user1', 'test_project1'))

        # test_user2 isn't manager
        self.assertFalse(permissions.is_project_manager('test_user2', 'test_project1'))

        # Lets set manager permission to test_user2
        ProjectRole.objects.create(
            user=self.test_user2,
            project=self.test_project1,
            role=settings.PROJECT_ROLE['manager'])

        # Now should be allowed to manage
        self.assertTrue(permissions.is_project_manager('test_user2', 'test_project1'))

        # Lets set read permission to test_user3
        ProjectRole.objects.create(
            user=self.test_user3,
            project=self.test_project1,
            role=settings.PROJECT_ROLE['reader'])

        # Should not be allowed to manage
        self.assertFalse(permissions.is_project_manager('test_user3', 'test_project1'))

    # TODO: test_is_reporter
    # TODO: test_is_editor

    def test_is_project_reader(self):
        # Lets set test_project1 as private
        self.test_project1.private = True
        self.test_project1.save()

        # If it's owner, then can read
        self.assertTrue(permissions.is_project_reader('test_user1', 'test_project1'))

        # test_user2 cannot read
        self.assertFalse(permissions.is_project_reader('test_user2', 'test_project1'))

        # Lets set read permission to test_user2
        ProjectRole.objects.create(
            user=self.test_user2,
            project=self.test_project1,
            role=settings.PROJECT_ROLE['reader'])

        # Now should be allowed to read
        self.assertTrue(permissions.is_project_reader('test_user2', 'test_project1'))

        # test_user3 cannot read
        self.assertFalse(permissions.is_project_reader('test_user3', 'test_project1'))

        # Lets set test_project1 as public
        self.test_project1.private = False
        self.test_project1.save()

        # Now test_user3 should be allowed to read
        self.assertTrue(permissions.is_project_reader('test_user3', 'test_project1'))

    # TODO: test organization roles
