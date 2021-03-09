import unittest

import psycopg2
from django.contrib.auth import get_user_model
from qfieldcloud.core.models import Geodb

User = get_user_model()


class GeodbTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def test_create_db(self):
        # Create a user
        user1 = User.objects.create_user(
            username="user1", password="abc123", email="user1@pizza.it"
        )

        # Create a geodb object

        geodb = Geodb.objects.create(
            user=user1,
            hostname="geodb",
            port=5432,
        )

        conn = psycopg2.connect(
            dbname=geodb.dbname,
            user=geodb.username,
            password=geodb.password,
            host=geodb.hostname,
            port=geodb.port,
        )

        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE pizza (
                code        char(5) CONSTRAINT firstkey PRIMARY KEY,
                title       varchar(40) NOT NULL
            );
            """
        )

        conn.commit()

    def tearDown(self):
        User.objects.all().delete()
