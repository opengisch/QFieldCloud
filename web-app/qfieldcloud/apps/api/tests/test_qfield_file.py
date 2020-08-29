import os
import shutil
import filecmp
import tempfile
import requests
import uuid
import unittest

from django.core.files import File as django_file
from django.contrib.auth import get_user_model
from django.conf import settings

from rest_framework import status
from rest_framework.test import APITransactionTestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.api import qgis_utils
from qfieldcloud.apps.model.models import Project, File, FileVersion
from .utils import testdata_path
from qfieldcloud.apps.api.qgis_utils import export_project

User = get_user_model()


class QfieldFileTestCase(APITransactionTestCase):

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
        # Remove all projects avoiding bulk delete in order to use
        # the overrided delete() function in the model
        for p in Project.objects.all():
            p.delete()

        User.objects.all().delete()
        # Remove credentials
        self.client.credentials()

    def test_export_project_files_to_filesystem(self):

        # Add a file to the project
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

        dir = self.project1.export_to_filesystem()

        self.assertIn('foo', os.listdir(dir))
        self.assertIn('bar', os.listdir(dir + '/foo/'))
        self.assertIn('file.txt', os.listdir(dir + '/foo/bar/'))

    @unittest.skip('This is an integration test')
    def test_list_files(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        with open(testdata_path(
                'simple_bee_farming/real_files/simple_bee_farming.qgs')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='simple_bee_farming.qgs')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path('simple_bee_farming/real_files/bees.gpkg'), 'rb') as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='bees.gpkg')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'simple_bee_farming/real_files/bumblebees.gpkg'), 'rb') as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='bumblebees.gpkg')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        project_file = 'simple_bee_farming.qgs'

        self.project1.export_to_filesystem()

        export_project(str(self.project1.id), project_file)

        response = self.client.get(
            '/api/v1/files/{}/?client=qfield'.format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k['name'])

        self.assertIn(json[0]['name'], 'data.gpkg')
        self.assertEqual(json[1]['name'], 'simple_bee_farming_qfield.qgs')

    @unittest.skip('This is an integration test')
    def test_export_job(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        with open(testdata_path(
                'simple_bee_farming/real_files/simple_bee_farming.qgs')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='simple_bee_farming.qgs')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path('simple_bee_farming/real_files/bees.gpkg'), 'rb') as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='bees.gpkg')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'simple_bee_farming/real_files/bumblebees.gpkg'), 'rb') as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='bumblebees.gpkg')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        response = self.client.get(
            '/api/v1/qfield-files/{}/'.format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        self.assertTrue('jobid' in json)

        jobid = str(json['jobid'])
        # Check if the response actually contains a valid uuid
        self.assertTrue(uuid.UUID(jobid))

        response = self.client.get(
            '/api/v1/qfield-files/export/{}/'.format(jobid))
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        files = sorted(json['files'], key=lambda k: k['name'])

        self.assertIn(files[0]['name'], 'data.gpkg')
        self.assertEqual(files[1]['name'], 'simple_bee_farming_qfield.qgs')

        response = self.client.get(
            '/api/v1/qfield-files/export/{}/{}/'.format(jobid, 'simple_bee_farming_qfield.qgs'))
        self.assertTrue(status.is_success(response.status_code))

        temp_dir = tempfile.mkdtemp()
        local_file = os.path.join(temp_dir, 'project.qgs')

        with open(local_file, 'wb') as f:
            for chunk in response.streaming_content:
                f.write(chunk)

        with open(local_file, 'r') as f:
            self.assertEqual(
                f.readline().strip(),
                "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>")
