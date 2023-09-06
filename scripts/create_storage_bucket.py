import boto3

# TODO: add cli params
# TODO: add non-delete bucket policy


def load_env_file():
    """Read env file and return a dict with the variables"""

    environment = {}
    with open("../.env") as f:
        for line in f:
            if line.strip():
                splitted = line.rstrip().split("=", maxsplit=1)
                if len(splitted) == 2:
                    environment[splitted[0]] = splitted[1]

    return environment


def _get_s3_bucket(env, bucket_name):
    """Get S3 Bucket according to the env variable
    STORAGE_BUCKET_NAME"""

    # Create session
    session = boto3.Session(
        aws_access_key_id=env["STORAGE_ACCESS_KEY_ID"],
        aws_secret_access_key=env["STORAGE_SECRET_ACCESS_KEY"],
        region_name=env["STORAGE_REGION_NAME"],
    )

    # Get the bucket objects
    s3 = session.resource("s3", endpoint_url=env["STORAGE_ENDPOINT_URL"])
    return s3.Bucket(bucket_name)


def _get_s3_client(env):
    s3_client = boto3.client(
        "s3",
        region_name=env["STORAGE_REGION_NAME"],
        aws_access_key_id=env["STORAGE_ACCESS_KEY_ID"],
        aws_secret_access_key=env["STORAGE_SECRET_ACCESS_KEY"],
        endpoint_url=env["STORAGE_ENDPOINT_URL"],
    )
    return s3_client


def _create_bucket(env, bucket_name):
    client = _get_s3_client(env)

    client.create_bucket(
        Bucket=bucket_name,
    )


def _enable_versioning(env, bucket_name):
    client = _get_s3_client(env)

    client.put_bucket_versioning(
        Bucket=bucket_name, VersioningConfiguration={"Status": "Enabled"}
    )


def _print_access_control_list(env, bucket_name):
    # Retrieve a bucket's ACL
    s3 = _get_s3_client(env)
    result = s3.get_bucket_acl(Bucket=bucket_name)
    from pprint import pprint

    pprint(result)


env = load_env_file()

# _print_access_control_list(env, 'qfieldcloud-test')
# _create_bucket(env, 'qfieldcloud-dev')

# bucket.objects.all().delete()
# bucket.object_versions.all().delete()

# client.delete_bucket(
#    Bucket='test-bucket',
#     )
