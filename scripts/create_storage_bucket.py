import boto3

# TODO: add cli params
# TODO: add non-delete bucket policy


def load_env_file():
    """Read env file and return a dict with the variables"""

    environment = {}
    with open('../conf/.env.app') as f:
        for line in f:
            splitted = line.rstrip().split('=')
            environment[splitted[0]] = splitted[1]

    return environment


def _get_s3_bucket(env, bucket_name):
    """Get S3 Bucket according to the env variable
    AWS_STORAGE_BUCKET_NAME"""

    # Create AWS session
    session = boto3.Session(
        aws_access_key_id=env['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=env['AWS_SECRET_ACCESS_KEY'],
        region_name=env['AWS_S3_REGION_NAME']
    )

    # Get the bucket objects
    s3 = session.resource('s3', endpoint_url=env['AWS_S3_ENDPOINT_URL'])
    return s3.Bucket(bucket_name)


def _get_s3_client(env):

    s3_client = boto3.client(
        's3',
        region_name=env['AWS_S3_REGION_NAME'],
        aws_access_key_id=env['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=env['AWS_SECRET_ACCESS_KEY'],
        endpoint_url=env['AWS_S3_ENDPOINT_URL'],
    )
    return s3_client

def _create_bucket(bucket_name):
    pass
# location = {'LocationConstraint': 'zrh1'}
# s3_client.create_bucket(
#     Bucket='qfieldcloud-test',
#     CreateBucketConfiguration=location)

# print(s3_client.put_bucket_versioning(
#     Bucket='qfieldcloud-test',
#     VersioningConfiguration={
#         'Status': 'Enabled'
#     }))

env = load_env_file()
print(env)
bucket = _get_s3_bucket(env, 'test-bucket')
client = _get_s3_client(env)


bucket.objects.all().delete()
bucket.object_versions.all().delete()

client.delete_bucket(
    Bucket='test-bucket',
    )

print(client.list_buckets())
