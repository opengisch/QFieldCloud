import os
import requests
import json
import shutil
import unittest
import tempfile

from django.core.files import File as django_file
from django.conf import settings
from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.api import qgis_utils
from qfieldcloud.apps.model.models import Project, File, FileVersion, DeltaFile
from .utils import testdata_path

User = get_user_model()


class IntegrationTestCase(APITestCase):

    DJANGO_BASE_URL = 'http://localhost:8000/api/v1/'
    ORCHESTRATOR_URL = 'http://' + qgis_utils.get_default_gateway() + ':5000/'

    def setUp(self):
        # Check if orchestrator is running otherwise skip test
        if not qgis_utils.orchestrator_is_running():
            self.skipTest('The orchestrator is not running correctly')

        # Create a user
        self.user1 = User.objects.create_user(
            username='user1', password='abc123')
        self.user1.save()

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

    @unittest.skip('The directory should be inside the user projects dir')
    def test_orchestrator_export_project(self):
        project_directory = testdata_path('simple_bee_farming')
        project_file = 'simple_bee_farming.qgs'

        url = ''.join([
            self.ORCHESTRATOR_URL,
            'export-project',
            '?project-dir=',
            project_directory,
            '&project-file=',
            project_file,
        ])

        response = requests.get(url)

        response.raise_for_status()

        files = os.listdir(
            testdata_path('simple_bee_farming/export/'))

        self.assertIn('simple_bee_farming_qfield.qgs', files)
        self.assertIn('data.gpkg', files)

        # TODO: move that in tearDown
        # delete output directory
        shutil.rmtree(
            testdata_path('simple_bee_farming/export/'),
            ignore_errors=True)

    def test_pull_data_file_api(self):

        # delete output directory
        shutil.rmtree(
            testdata_path('simple_bee_farming/export/'),
            ignore_errors=True)

        # Add files to the project
        with open(testdata_path(
                'simple_bee_farming/real_files/simple_bee_farming.qgs')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='simple_bee_farming.qgs')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path('simple_bee_farming/real_files/bees.gpkg'),
                  'rb') as f:
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

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Pull the data file
        response = self.client.get(
            '/api/v1/files/{}/data.gpkg/'.format(self.project1.id))

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'data.gpkg')

    def test_push_apply_delta_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Verify the original geojson file
        with open(testdata_path('delta/points.geojson')) as f:
            points_geojson = json.load(f)
            features = sorted(points_geojson['features'], key=lambda k: k['id'])
            self.assertEqual(1, features[0]['properties']['int'])

        # Add files to the project
        with open(testdata_path(
                'delta/points.geojson')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='points.geojson')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'delta/polygons.geojson')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='polygons.geojson')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'delta/project.qgs')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='project.qgs')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        # Push a deltafile
        delta_file = testdata_path('delta/deltas/singlelayer_singledelta.json')
        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )

        self.assertTrue(status.is_success(response.status_code))

        points_geojson_file = os.path.join(
            settings.PROJECTS_ROOT,
            str(self.project1.id),
            'real_files',
            'points.geojson'
        )

        # The geojson has been updated with the changes in the delta file
        with open(points_geojson_file) as f:
            points_geojson = json.load(f)
            features = sorted(points_geojson['features'], key=lambda k: k['id'])
            self.assertEqual(666, features[0]['properties']['int'])

        # The status has been updated
        deltafile_obj = DeltaFile.objects.get(
            id='6f109cd3-f44c-41db-b134-5f38468b9fda')
        self.assertEqual(deltafile_obj.status, DeltaFile.STATUS_APPLIED)

    def test_orchestrator_export_project_with_error(self):
        project_directory = testdata_path('simple_bee_farming')
        project_file = 'simple_bee_farmingZZ.qgs'

        url = ''.join([
            self.ORCHESTRATOR_URL,
            'export-project',
            '?project-dir=',
            project_directory,
            '&project-file=',
            project_file,
        ])

        response = requests.get(url)
        self.assertEqual(response.status_code, 500)

        self.assertIn(
            'FileNotFoundError: /io/project/simple_bee_farmingZZ.qgs',
            response.json()['output'])

    def test_push_apply_delta_file_with_error(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        with open(testdata_path(
                'delta/points.geojson')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='points.geojson')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'delta/polygons.geojson')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='polygons.geojson')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'delta/project.qgs')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='project.qgs')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        # Push a wrong deltafile
        delta_file = testdata_path('delta/deltas/wrong.json')
        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )

        self.assertTrue(status.is_success(response.status_code))

        # The status has been updated
        deltafile_obj = DeltaFile.objects.get(
            id='6f109cd3-f44c-41db-b134-5f38468b9fda')
        self.assertEqual(deltafile_obj.status, DeltaFile.STATUS_ERROR)

        self.assertIn("'deltaZZZ' was unexpected", deltafile_obj.output)

    def test_push_apply_delta_file_not_json(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        with open(testdata_path(
                'delta/points.geojson')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='points.geojson')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'delta/polygons.geojson')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='polygons.geojson')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'delta/project.qgs')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='project.qgs')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        # Push a wrong deltafile
        delta_file = testdata_path('file.txt')
        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )

        self.assertFalse(status.is_success(response.status_code))

    def test_push_apply_delta_file_with_conflicts(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        with open(testdata_path(
                'delta/points.geojson')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='points.geojson')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'delta/polygons.geojson')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='polygons.geojson')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        with open(testdata_path(
                'delta/project.qgs')) as f:
            file_obj = File.objects.create(
                project=self.project1,
                original_path='project.qgs')

            FileVersion.objects.create(
                file=file_obj,
                stored_file=django_file(f, name=os.path.basename(f.name)))

        # Push a deltafile
        delta_file = testdata_path(
            'delta/deltas/singlelayer_singledelta_conflict.json')
        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # The status has been updated
        deltafile_obj = DeltaFile.objects.get(
            id='6f109cd3-f44c-41db-b134-5f38468b9fda')

        self.assertEqual(deltafile_obj.status,
                         DeltaFile.STATUS_APPLIED_WITH_CONFLICTS)

    def test_list_files_for_qfield(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get(
            '/api/v1/files/{}/?client=qfield'.format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        # TODO: test content of the response

    def test_list_files_for_qfield_incomplete_project(self):
        # the qgs file is missing
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get(
            '/api/v1/files/{}/?client=qfield'.format(self.project1.id))
        self.assertEqual(response.status_code, 400)

    def test_download_file_for_qfield(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Download the qgs file
        response = self.client.get(
            '/api/v1/files/{}/project_qfield.qgs/?client=qfield'.format(
                self.project1.id),
        )
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

    def test_download_file_for_qgis(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/?client=qfield'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Download the qgs file
        response = self.client.get(
            '/api/v1/files/{}/project.qgs/?client=qgis'.format(
                self.project1.id),
        )
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
