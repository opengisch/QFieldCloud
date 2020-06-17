import shutil
import tempfile
import filecmp

from django.conf import settings

from rest_framework import status
from rest_framework.test import APITestCase

from .utils import testdata_path


class FunctionalTestCase(APITestCase):
    """Functional test using only API calls and not direct django data
    access"""

    def tearDown(self):
        pass

    def test_functional(self):
        # Maya registers herself on qfieldcloud
        response = self.client.post(
            '/api/v1/auth/registration/',
            {
                "username": "maya",
                "password1": "ILoveBees",
                "password2": "ILoveBees",
            }
        )
        # She gets a success answer
        self.assertTrue(status.is_success(response.status_code))
        # She gets the token
        self.assertTrue('token' in response.data)
        token = response.data['token']

        # She can now use her token as credentials
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

        # She creates a project for her beehives
        response = self.client.post(
            '/api/v1/projects/maya/',
            {
                'name': 'beehives',
                'description': 'My beehives in Lavertezzo',
                'private': True,
            }
        )
        self.assertTrue(status.is_success(response.status_code))

        # And she gets the project id in the response
        project_id = response.json()['id']

        # Now the new project is in the list of her projects
        response = self.client.get('/api/v1/projects/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)

        json = response.json()
        self.assertEqual(json[0]['name'], 'beehives')
        self.assertEqual(json[0]['id'], project_id)

        # Maya uploads her qgis project and geopackage
        file_path = testdata_path('simple_bumblebees.qgs')
        response = self.client.post(
            '/api/v1/files/{}/simple_bumblebees.qgs/?client=qgis'.format(project_id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('bumblebees.gpkg')
        response = self.client.post(
            '/api/v1/files/{}/bumblebees.gpkg/?client=qgis'.format(project_id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # And she also put some images in the DCIM subdirectory
        file_path = testdata_path('DCIM/1.jpg')
        response = self.client.post(
            '/api/v1/files/{}/DCIM/1.jpg/?client=qgis'.format(project_id),
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('DCIM/2.jpg')
        response = self.client.post(
            '/api/v1/files/{}/DCIM/2.jpg/?client=qgis'.format(project_id),
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # When she looks at the file list she finds all her uploaded files
        response = self.client.get(
            '/api/v1/files/{}/?client=qgis'.format(project_id))
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k['name'])

        self.assertEqual(len(json), 4)
        self.assertEqual(json[0]['name'], 'DCIM/1.jpg')
        self.assertEqual(json[1]['name'], 'DCIM/2.jpg')
        self.assertEqual(json[2]['name'], 'bumblebees.gpkg')
        self.assertEqual(json[3]['name'], 'simple_bumblebees.qgs')

        # But she notices that she uploaded a picture that she doesn't
        # need and she deletes it
        response = self.client.delete(
            '/api/v1/files/{}/DCIM/2.jpg/?client=qgis'.format(project_id))
        self.assertTrue(status.is_success(response.status_code))

        # And she verifies the list of the files again
        # When she looks at the file list she finds all her uploaded files
        response = self.client.get(
            '/api/v1/files/{}/?client=qgis'.format(project_id))
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k['name'])

        self.assertEqual(len(json), 3)
        self.assertEqual(json[0]['name'], 'DCIM/1.jpg')
        self.assertEqual(json[1]['name'], 'bumblebees.gpkg')
        self.assertEqual(json[2]['name'], 'simple_bumblebees.qgs')

        # She downloads all the files on another device
        response = self.client.get(
            '/api/v1/files/{}/simple_bumblebees.qgs/?client=qgis'.format(project_id))
        self.assertTrue(status.is_success(response.status_code))
        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)
        self.assertTrue(filecmp.cmp(
            temp_file.name, testdata_path('simple_bumblebees.qgs')))

        response = self.client.get(
            '/api/v1/files/{}/bumblebees.gpkg/?client=qgis'.format(project_id))
        self.assertTrue(status.is_success(response.status_code))
        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)
        self.assertTrue(filecmp.cmp(
            temp_file.name, testdata_path('bumblebees.gpkg')))

        response = self.client.get(
            '/api/v1/files/{}/DCIM/1.jpg/?client=qgis'.format(project_id))
        self.assertTrue(status.is_success(response.status_code))
        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)
        self.assertTrue(filecmp.cmp(
            temp_file.name, testdata_path('DCIM/1.jpg')))

        # TODO: continue with new projects, collaborators etc.
