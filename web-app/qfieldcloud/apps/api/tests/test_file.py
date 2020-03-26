import os
import shutil
import filecmp
import tempfile

from django.core.files import File as django_file
from django.contrib.auth import get_user_model
from django.conf import settings

from rest_framework import status
from rest_framework.test import APITransactionTestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.model.models import Project, File, FileVersion
from .utils import testdata_path

User = get_user_model()

# Use a different PROJECTS_ROOT for the tests
settings.PROJECTS_ROOT += '_test'


class FileTestCase(APITransactionTestCase):

    def setUp(self):
        # Create a user
        self.user1 = User.objects.create_user(
            username='user1', password='abc123')
        self.user1.save()

        self.user2 = User.objects.create_user(
            username='user2', password='abc123')
        self.user2.save()

        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # Create a project
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)
        self.project1.save()

    def tearDown(self):
        User.objects.all().delete()
        # Remove credentials
        self.client.credentials()
        Project.objects.all().delete()

        # Remove test's PROJECTS_ROOT
        shutil.rmtree(settings.PROJECTS_ROOT, ignore_errors=True)

    def test_push_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/user1/project1/push/',
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        self.assertTrue(File.objects.filter(original_path='file.txt').exists())

        file_obj = File.objects.get(original_path='file.txt')

        self.assertTrue(FileVersion.objects.filter(file=file_obj).exists())

        file_version_obj = FileVersion.objects.get(file=file_obj)

        file_version_obj_path = os.path.join(
            settings.PROJECTS_ROOT,
            file_version_obj.stored_file.name)

        self.assertTrue(filecmp.cmp(file_path, file_version_obj_path))

    def test_overwrite_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/user1/project1/push/',
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))
        # stored_file = os.path.join(str(self.project1.id), 'file.txt')
        updated_at1 = File.objects.get(original_path='file.txt').updated_at

        # Push again the file
        response = self.client.post(
            '/api/v1/projects/user1/project1/push/',
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(File.objects.all()), 1)

        self.assertEqual(len(FileVersion.objects.all()), 2)

        updated_at2 = File.objects.get(original_path='file.txt').updated_at

        self.assertTrue(updated_at2 > updated_at1)

        self.assertNotEqual(
            FileVersion.objects.all()[0].stored_file.name,
            FileVersion.objects.all()[1].stored_file.name)

    def test_push_file_with_path(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/user1/project1/push/',
            {
                "file": open(file_path, 'rb'),
                "path": 'foo/bar',
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        self.assertTrue(File.objects.filter(original_path='foo/bar/file.txt').exists())

    def test_push_file_with_unsafe_path(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/user1/project1/push/',
            {
                "file": open(file_path, 'rb'),
                "path": '../foo/bar',
            },
            format='multipart'
        )
        self.assertTrue(status.is_client_error(response.status_code))

    def test_push_file_invalid_user(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/user1234/project1/push/',
            {
                "file": open(file_path, 'rb'),
                "path": '../foo/bar',
            },
            format='multipart'
        )
        self.assertTrue(status.is_client_error(response.status_code))

    def test_push_file_invalid_project(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/user1/project1234/push/',
            {
                "file": open(file_path, 'rb'),
                "path": '../foo/bar',
            },
            format='multipart'
        )
        self.assertTrue(status.is_client_error(response.status_code))

    def test_pull_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        # Pull the file
        response = self.client.get(
            '/api/v1/files/user1/project1/file.txt/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'file.txt')

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'file.txt')
        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path('file.txt')))

    def test_pull_file_with_path(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='foo/bar/file.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(
                f,
                name=os.path.join(
                    'foo/bar',
                    os.path.basename(f.name))))

        # Pull the file
        response = self.client.get(
            '/api/v1/files/user1/project1/foo/bar/file.txt/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'foo/bar/file.txt')

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'foo/bar/file.txt')
        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path('file.txt')))

    def test_list_files(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        f = open(testdata_path('file2.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file2.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        response = self.client.get(
            '/api/v1/files/user1/project1/')
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k['name'])

        self.assertEqual(json[0]['name'], 'file.txt')
        self.assertEqual(json[0]['size'], 13)
        self.assertEqual(json[1]['name'], 'file2.txt')
        self.assertEqual(json[1]['size'], 13)
        self.assertEqual(
            json[0]['sha256'],
            '8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d')
        self.assertEqual(
            json[1]['sha256'],
            'fcc85fb502bd772aa675a0263b5fa665bccd5d8d93349d1dbc9f0f6394dd37b9')

    def test_delete_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file.txt')

        file_version_obj = FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        file_path_on_server = os.path.join(
            settings.PROJECTS_ROOT,
            file_version_obj.stored_file.name
        )
        self.assertTrue(os.path.isfile(file_path_on_server))

        self.assertEqual(len(File.objects.all()), 1)
        self.assertEqual(len(FileVersion.objects.all()), 1)

        response = self.client.delete(
            '/api/v1/files/user1/project1/file.txt/')
        self.assertTrue(status.is_success(response.status_code))

        self.assertEqual(len(File.objects.all()), 0)
        self.assertEqual(len(FileVersion.objects.all()), 0)
        self.assertFalse(os.path.isfile(file_path_on_server))

    def test_delete_file_with_path(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='foo/bar/file.txt')

        file_version_obj = FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        file_path_on_server = os.path.join(
            settings.PROJECTS_ROOT,
            file_version_obj.stored_file.name
        )
        self.assertTrue(os.path.isfile(file_path_on_server))

        self.assertEqual(len(File.objects.all()), 1)
        self.assertEqual(len(FileVersion.objects.all()), 1)

        response = self.client.delete(
            '/api/v1/files/user1/project1/foo/bar/file.txt/')
        self.assertTrue(status.is_success(response.status_code))

        self.assertEqual(len(File.objects.all()), 0)
        self.assertEqual(len(FileVersion.objects.all()), 0)
        self.assertFalse(os.path.isfile(file_path_on_server))

    def test_file_history(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        f2 = open(testdata_path('file2.txt'))

        file_obj = File.objects.create(
            project=self.project1,
            original_path='foo/bar/file.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)),
            uploaded_by=self.user1)

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f2, name=os.path.basename(f.name)),
            uploaded_by=self.user2)

        response = self.client.get(
            '/api/v1/history/user1/project1/foo/bar/file.txt/')

        self.assertTrue(status.is_success(response.status_code))

        json = response.json()

        self.assertEqual(len(json), 2)
        self.assertTrue(
            response.json()[0]['created_at'] <
            response.json()[1]['created_at'])

        self.assertEqual(
            json[0]['sha256'],
            '8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d')
        self.assertEqual(
            json[1]['sha256'],
            'fcc85fb502bd772aa675a0263b5fa665bccd5d8d93349d1dbc9f0f6394dd37b9')

        self.assertEqual(json[0]['size'], 13)
        self.assertEqual(json[1]['size'], 13)

        self.assertEqual(json[0]['uploaded_by'], 'user1')
        self.assertEqual(json[1]['uploaded_by'], 'user2')

    def test_pull_file_version(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        f2 = open(testdata_path('file2.txt'))

        file_obj = File.objects.create(
            project=self.project1,
            original_path='foo/bar/file.txt')

        file_version_obj = FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)),
            uploaded_by=self.user1)

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f2, name=os.path.basename(f.name)),
            uploaded_by=self.user2)

        # Pull the last file
        response = self.client.get(
            '/api/v1/files/user1/project1/foo/bar/file.txt/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'foo/bar/file.txt')

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'foo/bar/file.txt')
        self.assertFalse(
            filecmp.cmp(temp_file.name, testdata_path('file.txt')))

        response = self.client.get(
            '/api/v1/files/user1/project1/foo/bar/file.txt/',
            {
                "version": file_version_obj.created_at
            },
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'foo/bar/file.txt')

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'foo/bar/file.txt')
        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path('file.txt')))
