import os
import tempfile
import time

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITransactionTestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.core.models import Project
from .utils import testdata_path

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

    def test_download_file_for_qfield_broken_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file = testdata_path('delta/broken.qgs')
        response = self.client.post(
            '/api/v1/files/{}/broken.qgs/'.format(
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
            if response.json()['status'] == 'failed':
                # self.assertIn(
                #     'Unable to open file with QGIS', response.json()['output'])
                return

        self.fail("Worker didn't finish")

    def test_downloaded_file_has_canvas_name(self):
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
                    for line in f:
                        if 'name="theMapCanvas"' in line:
                            return

        self.fail("Worker didn't finish or there was an error")

    def test_download_project_with_broken_layer_datasources(self):
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

        file = testdata_path('delta/project_broken_datasource.qgs')
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

                self.assertTrue(
                    response.json()['layers']['points_c2784cf9_c9c3_45f6_9ce5_98a6047e4d6c']['valid'])
                self.assertFalse(
                    response.json()['layers']['surfacestructure_35131bca_337c_483b_b09e_1cf77b1dfb16']['valid'])
                return

        self.fail("Worker didn't finish")
