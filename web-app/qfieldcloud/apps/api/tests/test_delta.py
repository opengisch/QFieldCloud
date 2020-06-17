import shutil
import os
import unittest
import json

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files import File as django_file

from rest_framework import status
from rest_framework.test import APITransactionTestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.model.models import (
    DeltaFile, Project, File, FileVersion)
from .utils import testdata_path


User = get_user_model()


class DeltaTestCase(APITransactionTestCase):

    def setUp(self):
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
        User.objects.all().delete()
        # Remove credentials
        self.client.credentials()
        Project.objects.all().delete()

    def test_list_deltafiles(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Store a deltafile
        deltafile1 = DeltaFile.objects.create(
            project=self.project1,
            uploaded_by=self.user1,
            file=django_file(
                open(testdata_path('delta/deltas/singlelayer_singledelta.json')),
                name='delta.json')
        )

        # Store a deltafile
        deltafile2 = DeltaFile.objects.create(
            project=self.project1,
            uploaded_by=self.user1,
            file=django_file(
                open(testdata_path('delta/deltas/singlelayer_singledelta.json')),
                name='delta.json')
        )

        response = self.client.get(
            '/api/v1/deltas/{}/'.format(self.project1.id)
        )

        self.assertTrue(status.is_success(response.status_code))

        json_resp = response.json()
        json_resp = sorted(json_resp, key=lambda k: k['created_at'])

        self.assertEqual(len(json_resp), 2)

        self.assertEqual(json_resp[0]['uploaded_by'], 'user1')
        self.assertEqual(json_resp[1]['uploaded_by'], 'user1')

        self.assertEqual(json_resp[0]['status'], 'PENDING')
        self.assertEqual(json_resp[1]['status'], 'PENDING')

        self.assertEqual(json_resp[0]['id'], str(deltafile1.id))
        self.assertEqual(json_resp[1]['id'], str(deltafile2.id))

        self.assertEqual(json_resp[0]['project'], str(deltafile1.project.id))
        self.assertEqual(json_resp[1]['project'], str(deltafile2.project.id))

    def test_get_deltafile(self):

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        # Store a deltafile
        deltafile1 = DeltaFile.objects.create(
            project=self.project1,
            uploaded_by=self.user1,
            file=django_file(
                open(testdata_path(
                    'delta/deltas/singlelayer_singledelta.json')),
                name='delta.json')
        )

        response = self.client.get(
            '/api/v1/delta-status/{}/'.format(deltafile1.id)
        )

        self.assertTrue(status.is_success(response.status_code))
        json_resp = response.json()

        self.assertEqual(json_resp['uploaded_by'], 'user1')
        self.assertEqual(json_resp['status'], 'PENDING')
        self.assertEqual(json_resp['id'], str(deltafile1.id))
        self.assertEqual(json_resp['project'], str(deltafile1.project.id))
