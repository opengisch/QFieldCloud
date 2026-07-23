# Object Storage Cleaner

A utility script to identify and clean "logically deleted" objects in S3-compatible object storage (e.g., AWS S3, RustFS) when bucket versioning is enabled.

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
python purge_deleted_objects.py <bucket_name> --retention-period "30 days" [options]
```

### Options

Run the script with `--help` to see all available options.

---
By default the script uses the `default` S3 profile (default `boto3` behavior)
check [Configuration and credential file settings in the AWS CLI](https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-files.html)

### Examples

**1. Scan a bucket to see how much space can be freed:**

```bash
python purge_deleted_objects.py my-production-bucket --retention-period "30 days" --dry-run
```

**2. Scan a specific folder:**

```bash
python purge_deleted_objects.py my-production-bucket --retention-period "30 days" --dry-run --prefix "logs/2023/"
```

**3. Cleanup objects deleted more than 30 days ago (Retention Policy):**

- `--retention-period '30 days'`: Only selects objects that were deleted **more than 30 days ago**. Objects deleted recently (within the last 30 days) are preserved to allow for restoration.

```bash
# Clean objects deleted OLDER than 30 days
python purge_deleted_objects.py my-bucket --retention-period '30 days'
```

**4. Permanently delete objects:**

```bash
python purge_deleted_objects.py my-bucket --retention-period "30 days"
# You will be prompted to confirm.
```

**5. Automated cleanup for RustFS (local/custom endpoint):**

```bash
python purge_deleted_objects.py test-bucket --retention-period "30 days" --force
```

## Running Tests

The repository includes a test suite (`test.py`) that uses `unittest` and requires a running S3-compatible service.

### Test Requirements

- `boto3`
- Object storage service (e.g., RustFS) running.

### Steps to Run Tests

1.  **Start Object storage** - example using Docker:

    ```bash
    docker run -d -p 9000:9000 -p 9001:9001 --rm --name object-storage-test \
      -e "OBJECT_STORAGE_ACCESS_KEY=rustfsadmin" \
      -e "OBJECT_STORAGE_SECRET_KEY=rustfsadmin" \
      rustfs/rustfs /data
    ```

2.  **Configure Environment Variables**
    Export the following variables to configure `boto3` to talk to your local RustFS instance (matching the credentials above):

    ```bash
    export AWS_ACCESS_KEY_ID=rustfsadmin
    export AWS_SECRET_ACCESS_KEY=rustfsadmin
    export AWS_ENDPOINT_URL=http://localhost:8009
    export AWS_DEFAULT_REGION=us-east-1
    ```

3.  **Run Tests**
    ```bash
    python test.py
    ```
