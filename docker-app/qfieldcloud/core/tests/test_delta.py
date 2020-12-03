import os
import json
import tempfile
import time
import sqlite3

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITransactionTestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.core import utils
from qfieldcloud.core.models import Project
from .utils import testdata_path

User = get_user_model()


class DeltaTestCase(APITransactionTestCase):

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
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
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

        file_path = testdata_path('delta/testdata.gpkg')
        response = self.client.post(
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )

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

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/deltas/{}/'.format(self.project1.id),
            )

            if response.json()[0]['status'] in ['STATUS_BUSY', 'STATUS_PENDING']:
                continue

            self.assertEqual('STATUS_APPLIED', response.json()[0]['status'])

            # Download the geojson file
            response = self.client.get(
                '/api/v1/files/{}/testdata.gpkg/'.format(
                    self.project1.id),
            )
            self.assertTrue(status.is_success(response.status_code))

            temp_dir = tempfile.mkdtemp()
            local_file = os.path.join(temp_dir, 'testdata.gpkg')

            with open(local_file, 'wb') as f:
                for chunk in response.streaming_content:
                    f.write(chunk)

            conn = sqlite3.connect(local_file)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute('''SELECT * FROM points WHERE fid = 1''')
            f = c.fetchone()

            self.assertEqual(666, f['int'])
            return

        self.fail("Worker didn't finish")

    def test_push_apply_delta_file_with_error(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file_path = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
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

        file_path = testdata_path('delta/testdata.gpkg')
        response = self.client.post(
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )

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
        delta_file = testdata_path('delta/deltas/with_errors.json')
        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )

        self.assertTrue(status.is_success(response.status_code))

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/deltas/{}/'.format(self.project1.id),
            )

            if response.json()[0]['status'] == 'STATUS_BUSY':
                continue

            self.assertEqual('STATUS_NOT_APPLIED', response.json()[0]['status'])
            return

        self.fail("Worker didn't finish")

    def test_push_apply_delta_file_invalid_json_schema(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file_path = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
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

        file_path = testdata_path('delta/testdata.gpkg')
        response = self.client.post(
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )

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
        delta_file = testdata_path('delta/deltas/not_schema_valid.json')
        response = self.client.post(
            '/api/v1/deltas/{}/'.format(self.project1.id),
            {
                "file": open(delta_file, 'rb')
            },
            format='multipart'
        )

        self.assertFalse(status.is_success(response.status_code))

    def test_push_apply_delta_file_not_json(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Add files to the project
        file_path = testdata_path('delta/points.geojson')
        response = self.client.post(
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
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

        file_path = testdata_path('delta/testdata.gpkg')
        response = self.client.post(
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )

        file_path = testdata_path('delta/project.qgs')
        response = self.client.post(
            '/api/v1/files/{}/project.qgs/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
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
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
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

        file_path = testdata_path('delta/testdata.gpkg')
        response = self.client.post(
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )

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

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/deltas/{}/'.format(self.project1.id),
            )

            if response.json()[0]['status'] == 'STATUS_BUSY':
                continue

            self.assertEqual('STATUS_APPLIED_WITH_CONFLICTS', response.json()[0]['status'])
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
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
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

        file_path = testdata_path('delta/testdata.gpkg')
        response = self.client.post(
            '/api/v1/files/{}/testdata.gpkg/'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )

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

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                '/api/v1/deltas/{}/'.format(self.project1.id),
            )

            if response.json()[0]['status'] == 'STATUS_BUSY':
                continue

            self.assertEqual('STATUS_APPLIED', response.json()[0]['status'])

            # Download the geojson file
            response = self.client.get(
                '/api/v1/files/{}/testdata.gpkg/'.format(
                    self.project1.id),
            )
            self.assertTrue(status.is_success(response.status_code))

            temp_dir = tempfile.mkdtemp()
            local_file = os.path.join(temp_dir, 'testdata.gpkg')

            with open(local_file, 'wb') as f:
                for chunk in response.streaming_content:
                    f.write(chunk)

            conn = sqlite3.connect(local_file)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute('''SELECT * FROM points WHERE fid = 1''')
            f = c.fetchone()

            self.assertEqual(666, f['int'])
            return

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

        self.assertEqual(json[1]['id'], 'e4546ec2-6e01-43a1-ab30-a52db9469afd')
        self.assertEqual(json[0]['id'], '802ae2ef-f360-440e-a816-8990d6a06667')

    def test_push_list_multidelta(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Push a deltafile
        delta_file = testdata_path(
            'delta/deltas/singlelayer_multidelta.json')
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

        self.assertEqual(json[0]['id'], '736bf2c2-646a-41a2-8c55-28c26aecd68d')
        self.assertEqual(json[1]['id'], '8adac0df-e1d3-473e-b150-f8c4a91b4781')
        self.assertEqual(json[2]['id'], 'c6c88e78-172c-4f77-b2fd-2ff41f5aa854')

        time.sleep(10)
