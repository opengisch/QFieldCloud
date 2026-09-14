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

## Storage Configuration

The script needs to know which bucket(s) to connect to. Provide **exactly one** of the following two sources — they are mutually exclusive, and the script errors out if both, or neither, are set.

### Option A: `STORAGES` environment variable

Set `STORAGES` to the same JSON structure used by QFieldCloud's Django settings, e.g.:

```json
{
  "default": {
    "BACKEND": "qfieldcloud.filestorage.backend.QfcS3Boto3Storage",
    "OPTIONS": {
      "bucket_name": "qfieldcloud-local",
      "endpoint_url": "http://172.17.0.1:8009",
      "access_key": "...",
      "secret_key": "...",
      "region_name": ""
    }
  }
}
```

By default, the script purges **every** entry in `STORAGES` whose `BACKEND` is `qfieldcloud.filestorage.backend.QfcS3Boto3Storage`, one after another. Pass a storage name as the positional `storage_name` argument to restrict it to a single entry (the entry must exist and be of that backend type):

```bash
python purge_deleted_objects.py my-storage-name --retention-period "30 days"
```

### Option B: `AWS_*` environment variables

If `STORAGES` is not set, the script falls back to a single bucket configured via plain `boto3`-style environment variables:

- `AWS_BUCKET_NAME`
- `AWS_ENDPOINT_URL`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`

The positional `storage_name` argument does not apply in this mode.

## Usage

Run the script directly from the command line.

### Basic Syntax

```bash
python purge_deleted_objects.py [storage_name] --retention-period "30 days" [options]
```

`storage_name` is optional and only used to select a single entry from `STORAGES` (see "Storage Configuration" above). If omitted, all matching `STORAGES` entries are purged.

### Options

Run the script with `--help` to see all available options.

### Examples

**1. Scan all configured storages to see how much space can be freed:**

```bash
python purge_deleted_objects.py --retention-period "30 days" --dry-run
```

**2. Scan only one named storage from `STORAGES`:**

```bash
python purge_deleted_objects.py my-production-storage --retention-period "30 days" --dry-run
```

**3. Scan a specific folder:**

```bash
python purge_deleted_objects.py my-production-storage --retention-period "30 days" --dry-run --prefix "logs/2023/"
```

**4. Cleanup objects deleted more than 30 days ago (Retention Policy):**

- `--retention-period '30 days'`: Only selects objects that were deleted **more than 30 days ago**. Objects deleted recently (within the last 30 days) are preserved to allow for restoration.

```bash
# Clean objects deleted OLDER than 30 days, across every eligible storage
python purge_deleted_objects.py --retention-period '30 days'
```

**5. Permanently delete objects:**

```bash
# You will be prompted to confirm once, covering all storages to be purged.
python purge_deleted_objects.py --retention-period "30 days"
```

**6. Automated cleanup for RustFS (local/custom endpoint) using `AWS_*` env vars:**

```bash
export AWS_BUCKET_NAME=qfieldcloud-local
export AWS_ACCESS_KEY_ID=rustfsadmin
export AWS_SECRET_ACCESS_KEY=rustfsadmin
export AWS_ENDPOINT_URL=http://localhost:8009

python purge_deleted_objects.py --retention-period "30 days" --force
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
    export AWS_ENDPOINT_URL=http://localhost:9000
    ```

    (the bucket name will be generated and selected dynamically by the test suite)

3.  **Run Tests**
    ```bash
    python test.py
    ```
