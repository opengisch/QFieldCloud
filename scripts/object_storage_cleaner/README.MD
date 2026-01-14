# Object Storage Cleaner

A utility script to identify and clean "logically deleted" objects in S3-compatible object storage (e.g., AWS S3, MinIO) when bucket versioning is enabled.

## The Problem

When **Versioning** is enabled on an S3 bucket, deleting an object does not actually remove the data. Instead, S3 creates a **Delete Marker** as the latest version. The older versions (the actual data) remain in the bucket and continue to incur storage costs.

A "logically deleted object" is an object where the current (latest) version is a Delete Marker. This means the object appears deleted to applications, but all its historical versions are still stored.

This script helps you:
1.  **Scan**: Find all objects that are logically deleted and calculate how much space they are wasting.
2.  **Permanently Delete Versions**: Permanently delete all versions of these objects (including the delete marker) to free up storage.

> **Note**: This script specifically targets objects that are *currently deleted*. It does **not** touch objects that are still active (i.e., the latest version is a file, not a delete marker), even if they have old versions.

## Requirements

- Python 3.8+
- `boto3` library

1. Create a virtual environment

2. Install dependencies:

```bash
pip install boto3

# Optional
pip install mypy-boto3-s3 # for type hinting
```

## Usage

Run the script directly from the command line.

### Basic Syntax

```bash
python object_storage_cleaner.py <bucket_name> [options]
```

### Options

| Option | Description |
|--------|-------------|
| `bucket_name` | The name of the target S3 bucket (Required). |
| `--scan` | Only scan and report statistics (Default). |
| `--permanently-delete-versions` | Delete found objects. Requires confirmation unless `--noinput` is used. |
| `--noinput` | Skip confirmation prompt (useful for automation). |
| `--prefix <path>` | Limit scan to a specific prefix (folder). |
| `--retention-period <duration>` | Only process objects deleted BEFORE this duration (e.g., `7 days`, `30 minutes`, `1 hour`). Recent deletions are preserved. |
| `--log-level` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
---
By default the script uses the `default` S3 profile (default boto3 behavior)
check [Configuration and credential file settings in the AWS CLI](https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-files.html)

### Examples

**1. Scan a bucket to see how much space can be freed:**

```bash
python object_storage_cleaner.py my-production-bucket --scan
```

**2. Scan a specific folder:**

```bash
python object_storage_cleaner.py my-production-bucket --prefix "logs/2023/" --scan
```

**3. Cleanup objects deleted more than 30 days ago (Retention Policy):**

- `--retention-period '30 days'`: Only selects objects that were deleted **more than 30 days ago**. Objects deleted recently (within the last 30 days) are preserved to allow for restoration.

```bash
# Clean objects deleted OLDER than 30 days
python object_storage_cleaner.py my-bucket --permanently-delete-versions --retention-period '30 days'
```

**4. Permanently delete (permanently-delete-versions) objects:**

```bash
python object_storage_cleaner.py my-bucket --permanently-delete-versions
# You will be prompted to confirm.
```

**5. Automated cleanup for MinIO (local/custom endpoint):**

```bash
python object_storage_cleaner.py test-bucket --permanently-delete-versions --noinput
```

## Running Tests

The repository includes a test suite (`test.py`) that uses `pytest` and requires a running S3-compatible service (like MinIO).

### Test Requirements
- `pytest`
- `boto3`
- A local S3 service (e.g., MinIO) running. By default, tests expect it at `http://localhost:8009` (us-east-1).

*you can also adjust the test file for your needs to connect to a remote object storage server to run the tests*

### Steps to Run Tests

1.  **Start MinIO** (or ensure a mock S3 is running).
    Example using Docker:
    ```bash
    docker run -d -p 8009:9000 --name minio-test \
      -e "MINIO_ACCESS_KEY=access_key_xyz" \
      -e "MINIO_SECRET_KEY=secret_key_xyz" \
      minio/minio server /data
    ```

2.  **Configure Tests (Optional)**
    If your local S3 is different from `http://localhost:8009`, update the `CONNECTION_CONFIG` dictionary in `test.py`.

3.  **Run Pytest**
    ```bash
    pytest test.py
    ```
