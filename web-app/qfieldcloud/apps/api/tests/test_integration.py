import os
import requests
import json
import shutil
import unittest
import tempfile
import time

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

        # Request export of project
        response = self.client.get(
            '/api/v1/qfield-files/{}/'.format(self.project1.id))

        jobid = response.json()['jobid']

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/qfield-files/export/{}/'.format(jobid),
            )

            if response.json()['status'] == 'finished':

                response = self.client.get(
                    '/api/v1/qfield-files/export/{}/data.gpkg/'.format(jobid),
                )

                self.assertTrue(status.is_success(response.status_code))
                self.assertEqual(response.filename, 'data.gpkg')
                return

        self.fail("Worker didn't finish")

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

        jobid = response.json()['jobid']

        points_geojson_file = os.path.join(
            settings.PROJECTS_ROOT,
            str(self.project1.id),
            'real_files',
            'points.geojson'
        )

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/deltas/status/{}/'.format(jobid),
            )

            if response.json()['status'] == 'finished':

                # The geojson has been updated with the changes in the delta file
                with open(points_geojson_file) as f:
                    points_geojson = json.load(f)
                    features = sorted(points_geojson['features'], key=lambda k: k['id'])
                    self.assertEqual(666, features[0]['properties']['int'])
                    return

        self.fail("Worker didn't finish")

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

        jobid = response.json()['jobid']

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/deltas/status/{}/'.format(jobid),
            )

            if response.json()['status'] == 'not_applied':
                self.assertIn(
                    "'deltas\' is a required property",
                    response.json()['output'])
                return

        self.fail("Worker didn't finish")

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

        jobid = response.json()['jobid']

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/deltas/status/{}/'.format(jobid),
            )

            if not response.json()['status'] == 'started':
                self.assertEquals(
                    'applied_with_conflicts', response.json()['status'])
                return

        self.fail("Worker didn't finish")

    def test_list_files_for_qfield(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get(
            '/api/v1/qfield-files/{}/'.format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        jobid = response.json()['jobid']

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/qfield-files/export/{}/'.format(jobid),
            )

            if response.json()['status'] == 'finished':
                json_resp = response.json()
                files = sorted(json_resp['files'], key=lambda k: k['name'])
                self.assertEqual(files[2]['name'], 'project_qfield.qgs')
                return

        self.fail("Worker didn't finish")

    def test_list_files_for_qfield_incomplete_project(self):
        # the qgs file is missing
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get(
            '/api/v1/qfield-files/{}/'.format(self.project1.id))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            'The project does not contain a valid qgis project file')

    def test_download_file_for_qfield(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Start the export to get the jobid
        response = self.client.get(
            '/api/v1/qfield-files/{}/'.format(
                self.project1.id),
        )
        self.assertTrue(status.is_success(response.status_code))

        jobid = response.json()['jobid']

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/qfield-files/export/{}/'.format(jobid),
            )

            if response.json()['status'] == 'finished':
                response = self.client.get(
                    '/api/v1/qfield-files/export/{}/project_qfield.qgs/'.format(
                        jobid),
                )
                temp_dir = tempfile.mkdtemp()
                local_file = os.path.join(temp_dir, 'project.qgs')

                with open(local_file, 'wb') as f:
                    for chunk in response.streaming_content:
                        f.write(chunk)

                with open(local_file, 'r') as f:
                    self.assertEqual(
                        f.readline().strip(),
                        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>")
                return

        self.fail("Worker didn't finish")

    def test_download_file_for_qgis(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/'.format(
                self.project1.id),
            {
                "file": open(file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Download the qgs file
        response = self.client.get(
            '/api/v1/files/{}/project.qgs/'.format(
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

    def test_push_apply_delta_file_twice(self):
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

        jobid = response.json()['jobid']
        points_geojson_file = os.path.join(
            settings.PROJECTS_ROOT,
            str(self.project1.id),
            'real_files',
            'points.geojson'
        )

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/deltas/status/{}/'.format(jobid),
            )

            if response.json()['status'] == 'finished':

                # The geojson has been updated with the changes in the delta file
                with open(points_geojson_file) as f:
                    points_geojson = json.load(f)
                    features = sorted(points_geojson['features'], key=lambda k: k['id'])
                    self.assertEqual(666, features[0]['properties']['int'])
                    break

        # Push the same deltafile again
        delta_file = testdata_path('delta/deltas/singlelayer_singledelta.json')

        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )

        self.assertTrue(status.is_success(response.status_code))

        # Push a deltafile with same id but different content
        delta_file = testdata_path(
            'delta/deltas/singlelayer_singledelta_diff_content.json')

        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )

        self.assertTrue(status.is_client_error(response.status_code))
