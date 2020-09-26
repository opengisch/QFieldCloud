import os
import json
import tempfile
import time

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.core import utils
from qfieldcloud.core.models import Project
from .utils import testdata_path

User = get_user_model()


class DeltaTestCase(APITestCase):

    DJANGO_BASE_URL = 'http://localhost:8000/api/v1/'

    def setUp(self):
        # Check if orchestrator is running otherwise skip test
        if not utils.redis_is_running():
            self.skipTest('Redis is not running correctly')

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

    def test_push_apply_delta_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Verify the original geojson file
        with open(testdata_path('delta/points.geojson')) as f:
            points_geojson = json.load(f)
            features = sorted(
                points_geojson['features'], key=lambda k: k['id'])
            self.assertEqual(1, features[0]['properties']['int'])

        # Add files to the project
        file_path = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push a deltafile
        delta_file = testdata_path(
            'delta/deltas/singlelayer_singledelta2.json')
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
                '/api/v1/deltas/{}/{}/'.format(self.project1.id, jobid),
            )

            if response.json()['status'] == 'STATUS_APPLIED':

                # Download the geojson file
                response = self.client.get(
                    '/api/v1/files/{}/points.geojson/'.format(
                        self.project1.id),
                )
                self.assertTrue(status.is_success(response.status_code))

                temp_dir = tempfile.mkdtemp()
                local_file = os.path.join(temp_dir, 'points.geojson')

                with open(local_file, 'wb') as f:
                    for chunk in response.streaming_content:
                        f.write(chunk)

                # The geojson has been updated with the changes in the
                # delta file
                with open(local_file) as f:
                    points_geojson = json.load(f)
                    features = sorted(
                        points_geojson['features'], key=lambda k: k['id'])
                    self.assertEqual(666, features[0]['properties']['int'])
                    return

        self.fail("Worker didn't finish")

    def test_push_apply_delta_file_with_error(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file_path = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push a deltafile
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
                '/api/v1/deltas/{}/{}/'.format(self.project1.id, jobid),
            )
            if response.json()['status'] == 'STATUS_NOT_APPLIED':
                return

        self.fail("Worker didn't finish")

    def test_push_apply_delta_file_not_json(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file_path = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push a deltafile
        delta_file = testdata_path('delta/deltas/wrong.json')
        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )

        self.assertTrue(status.is_success(response.status_code))

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
        file_path = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

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
                '/api/v1/deltas/{}/{}/'.format(self.project1.id, jobid),
            )

            if response.json()['status'] == 'STATUS_APPLIED_WITH_CONFLICTS':
                return

        self.fail("Worker didn't finish")

    def test_push_apply_delta_file_twice(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Verify the original geojson file
        with open(testdata_path('delta/points.geojson')) as f:
            points_geojson = json.load(f)
            features = sorted(
                points_geojson['features'], key=lambda k: k['id'])
            self.assertEqual(1, features[0]['properties']['int'])

        # Add files to the project
        file_path = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/points.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/polygons.geojson')
        response = self.client.post(
            '/api/v1/files/{}/polygons.geojson/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

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

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/deltas/{}/{}/'.format(self.project1.id, jobid),
            )
            if response.json()['status'] == 'STATUS_APPLIED':

                # Download the geojson file
                response = self.client.get(
                    '/api/v1/files/{}/points.geojson/'.format(
                        self.project1.id),
                )
                self.assertTrue(status.is_success(response.status_code))

                temp_dir = tempfile.mkdtemp()
                local_file = os.path.join(temp_dir, 'points.geojson')

                with open(local_file, 'wb') as f:
                    for chunk in response.streaming_content:
                        f.write(chunk)

                # The geojson has been updated with the changes in the
                # delta file
                with open(local_file) as f:
                    points_geojson = json.load(f)
                    features = sorted(
                        points_geojson['features'], key=lambda k: k['id'])
                    self.assertEqual(666, features[0]['properties']['int'])
                    return
            elif response.json()['status'] == 'STATUS_NOT_APPLIED':
                self.fail("Delta not applied")

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

    def test_push_list_deltas(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Push a deltafile
        delta_file = testdata_path(
            'delta/deltas/singlelayer_singledelta3.json')
        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push another deltafile
        delta_file = testdata_path(
            'delta/deltas/singlelayer_singledelta4.json')
        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get(
            '/api/v1/deltas/{}/'.format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))
        json = response.json()
        json = sorted(json, key=lambda k: k['id'])

        self.assertEqual(json[1]['id'], 'ab3e55a2-98cc-4c03-8069-8266fefd8124')
        self.assertEqual(json[1]['size'], 546)
        self.assertEqual(json[0]['id'], '4d027a9d-d31a-4e8f-acad-2f2d59caa48c')
        self.assertEqual(json[0]['size'], 546)
        self.assertEqual(
            json[1]['sha256'],
            'ccf1a0726d760510bb50b740c13e6a140aeadb832e5dd8152be4bd8b62b7ccac')
        self.assertEqual(
            json[0]['sha256'],
            '1690fb4ad6f4747e166c15f8a64dd500b16279a9e0ca9f70bba5e13a13547e36')

    def test_apply_delta_gpkg(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file_path = testdata_path('delta/points.gpkg')
        response = self.client.post(
            '/api/v1/files/{}/points.gpkg/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/polygons.gpkg')
        response = self.client.post(
            '/api/v1/files/{}/polygons.gpkg/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('delta/project_gpkg.qgz')
        response = self.client.post(
            '/api/v1/files/{}/project_gpkg.qgz/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push a deltafile
        delta_file = testdata_path(
            'delta/deltas/singlelayer_singledelta_gpkg.json')
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
                '/api/v1/deltas/{}/{}/'.format(self.project1.id, jobid),
            )
            if response.json()['status'] == 'STATUS_APPLIED':

                # Download the gpkg file
                response = self.client.get(
                    '/api/v1/files/{}/points.gpkg/'.format(
                        self.project1.id),
                )
                self.assertTrue(status.is_success(response.status_code))

                temp_dir = tempfile.mkdtemp()
                local_file = os.path.join(temp_dir, 'points.gpkg')

                with open(local_file, 'wb') as f:
                    for chunk in response.streaming_content:
                        f.write(chunk)

                import sqlite3
                conn = sqlite3.connect(local_file)
                c = conn.cursor()
                c.execute("SELECT int FROM points WHERE fid = '1'")
                self.assertEqual(c.fetchone()[0], 6969)

                conn.close()
                return

        self.fail("Worker didn't finish")
