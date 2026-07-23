import io
import logging
import shutil
import tempfile

import geopandas as gpd
from django.http import FileResponse
from rest_framework.test import APITransactionTestCase
from shapely.geometry import Polygon

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    Person,
    Secret,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    get_test_postgis_connection,
    set_subscription,
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)
from qfieldcloud.core.utils2.jobs import repackage
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        self.org1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )
        set_subscription(self.org1, is_external_db_supported=True)

        # Create a project
        self.project1 = Project.objects.create(
            name="project1",
            is_public=False,
            owner=self.org1,
            packaging_offliner=Project.PackagingOffliner.PYTHONMINI,
        )

        self.conn = get_test_postgis_connection()

    def tearDown(self):
        self.conn.close()

    def test_packaged_gpkg_features(self):
        # check the number of features in the bumblebees geopackage
        apiaries_local = gpd.read_file(testdata_path("bumblebees.gpkg"), layer="apiary")
        areas_local = gpd.read_file(testdata_path("bumblebees.gpkg"), layer="area")

        self.assertEqual(len(apiaries_local), 35)
        self.assertEqual(len(areas_local), 14)

        # upload the geopackage and the qgis project file to the project
        self._upload_file(
            self.user1,
            self.project1,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )
        self._upload_file(
            self.user1,
            self.project1,
            "simple_bumblebees.qgs",
            io.FileIO(testdata_path("simple_bumblebees.qgs"), "rb"),
        )

        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        # trigger a project package job for user1
        repackage(self.project1, self.user1)
        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        # download the packaged gpkg
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get(
            f"/api/v1/packages/{self.project1.id}/latest/files/data.gpkg/",
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response, FileResponse)

        # check the number of features in the downloaded geopackage
        with tempfile.NamedTemporaryFile(delete=True, suffix=".gpkg") as tmp:
            with open(tmp.name, "wb") as f:
                for chunk in response.streaming_content:
                    f.write(chunk)

            # Here we check for point and polygon layers, respectively apiary and area layers.
            # since PythonMiniOffliner names layers with sha256 of the datasource
            # see https://github.com/opengisch/libqfieldsync/blob/1fe95e62b3c648e58ef80707593c447592ca1762/libqfieldsync/offliners.py#L257-L259
            layers = gpd.list_layers(tmp.name)
            point_layer = layers.loc[layers["geometry_type"] == "Point", "name"].iloc[0]
            polygon_layer = layers.loc[
                layers["geometry_type"] == "Polygon", "name"
            ].iloc[0]

            apiaries_package = gpd.read_file(tmp.name, layer=point_layer)
            areas_package = gpd.read_file(tmp.name, layer=polygon_layer)

            self.assertEqual(len(apiaries_package), 35)
            self.assertEqual(len(apiaries_package), len(apiaries_local))
            self.assertEqual(len(areas_package), 14)
            self.assertEqual(len(areas_package), len(areas_local))

    def test_packaged_postgis_features(self):
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE point (id integer primary key, geometry geometry(multipoint, 2056))"
        )
        self.conn.commit()

        nb_point_features = 12

        for i in range(nb_point_features):
            cur.execute(
                "INSERT INTO point(id, geometry) VALUES(%s, ST_GeomFromText('MULTIPOINT(%s %s)', 2056))",
                (i + 1, 2725505 + i, 1121435 - i),
            )

        self.conn.commit()

        Secret.objects.create(
            name="PG_SERVICE_TESTDB1",
            type=Secret.Type.PGSERVICE,
            project=self.project1,
            created_by=self.project1.owner,
            value=(
                "[geodb1]\n"
                "dbname=test_postgis_db_name\n"
                "host=test_postgis_db\n"
                "port=5432\n"
                "user=test_postgis_db_user\n"
                "password=test_postgis_db_password\n"
                "sslmode=disable\n"
            ),
        )

        self._upload_file(
            self.user1,
            self.project1,
            "project.qgs",
            io.FileIO(testdata_path("delta/project2.qgs"), "rb"),
        )

        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        # trigger a project package job for user1
        repackage(self.project1, self.user1)
        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        # download the packaged gpkg
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get(
            f"/api/v1/packages/{self.project1.id}/latest/files/data.gpkg/",
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response, FileResponse)

        # check the number and types of features in the downloaded gpkg
        with tempfile.NamedTemporaryFile(delete=True, suffix=".gpkg") as tmp:
            with open(tmp.name, "wb") as f:
                for chunk in response.streaming_content:
                    f.write(chunk)

            layers = gpd.list_layers(tmp.name)

            self.assertEqual(len(layers), 1)

            layer_name = layers.iloc[0]["name"]
            packaged_gdf = gpd.read_file(tmp.name, layer=layer_name)

            self.assertEqual(len(packaged_gdf), nb_point_features)
            self.assertTrue((packaged_gdf.geometry.geom_type == "Point").all())

            for _, row in packaged_gdf.iterrows():
                self.assertEqual(row.geometry.geom_type, "Point")

    def test_packaging_promotes_polygon_to_multipolygon(self):
        # `multipolygons.gpkg` declares the layer as MULTIPOLYGON but has no features.
        # We append a Polygon to create the type mismatch that the PythonMiniOffliner will resolve by promoting the geometry to MultiPolygon.
        gdf = gpd.GeoDataFrame(
            geometry=[Polygon([(104, 12), (104, 11), (105, 11), (105, 12), (104, 12)])],
            crs="EPSG:4326",
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gpkg") as tmp:
            shutil.copy(testdata_path("multipolygons.gpkg"), tmp.name)
            gdf.to_file(tmp.name, layer="multipolygons", driver="GPKG", mode="a")

        self._upload_file(
            self.user1,
            self.project1,
            "multipolygons.gpkg",
            io.FileIO(tmp.name, "rb"),
        )
        self._upload_file(
            self.user1,
            self.project1,
            "multipolygons.qgs",
            io.FileIO(testdata_path("multipolygons.qgs"), "rb"),
        )

        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        # trigger a project package job for user1
        repackage(self.project1, self.user1)
        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        # download the packaged gpkg
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get(
            f"/api/v1/packages/{self.project1.id}/latest/files/data.gpkg/",
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response, FileResponse)

        # check the number and types of features in the downloaded gpkg
        with tempfile.NamedTemporaryFile(delete=True, suffix=".gpkg") as tmp:
            with open(tmp.name, "wb") as f:
                for chunk in response.streaming_content:
                    f.write(chunk)

            layers = gpd.list_layers(tmp.name)

            self.assertEqual(len(layers), 1)

            layer_name = layers.iloc[0]["name"]
            packaged_gdf = gpd.read_file(tmp.name, layer=layer_name)

            self.assertEqual(len(packaged_gdf), 1)
            self.assertEqual(packaged_gdf.geometry.geom_type.iloc[0], "MultiPolygon")
