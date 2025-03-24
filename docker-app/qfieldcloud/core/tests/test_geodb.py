import logging
import unittest

import psycopg2
from django.conf import settings

from qfieldcloud.core.models import Geodb, Person

from .utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(unittest.TestCase):
    def setUp(self):
        setup_subscription_plans()

    def test_create_db(self):
        # Create a user
        user1 = Person.objects.create_user(
            username="user1", password="abc123", email="user1@pizza.it"
        )

        # Create a geodb object

        geodb = Geodb.objects.create(
            user=user1,
            hostname=settings.GEODB_HOST,
            port=settings.GEODB_PORT,
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
