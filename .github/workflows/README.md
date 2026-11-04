# GitHub Actions workflows

## CI image and tag behavior

The [`ci.yml`](ci.yml) workflow builds shared images before running tests. Events
with package write access push the completed images to GHCR using an exact commit
tag, allowing parallel test jobs to pull the same images instead of rebuilding them.

| Event | Images and tags | Tests |
| --- | --- | --- |
| Pull request from this repository (draft or ready) | Six test images receive `commit-<sha>` tags in GHCR and update their `buildcache` tags. Docker Hub, `edge`, and version tags are unchanged. | Pull the commit-tagged images and run with `--no-build`. |
| Fork or Dependabot pull request (draft or ready) | No images or tags are pushed because these pull requests receive a token that cannot write to this repository's GHCR packages. | Build images separately on each GitHub Actions runner. |
| Push to an ordinary branch | Does not trigger `ci.yml`. If the branch has an open pull request, its `pull_request` event runs the pull-request behavior above. | Not run directly by the branch push. |
| Push to `release` | Six test images receive `commit-<sha>` tags in GHCR and update their `buildcache` tags. | Pull the commit-tagged images and run with `--no-build`. |
| Push to `master` | All eight images are built. Six test images receive GHCR `commit-<sha>` tags. Seven runtime images receive `edge` tags in GHCR and Docker Hub. | Pull the commit-tagged images and run with `--no-build`. |
| Published GitHub Release | Seven runtime images receive version tags in GHCR and Docker Hub and update their `buildcache` tags. `app-test` is not published. | Lint and tests are skipped because the released commit was checked before publication. |
| Manual workflow run | Not available because `ci.yml` has no `workflow_dispatch` trigger. Re-running an existing run repeats its original event behavior. | Depends on the original event. |

## Image groups

Test images receive commit-scoped tags and are consumed by CI:

- `app-test`
- `worker-wrapper`
- `qgis3`
- `qgis4`
- `nginx`
- `createbuckets`

Runtime images receive `edge` or version tags for deployment:

- `app`
- `worker-wrapper`
- `qgis` (legacy compatibility image built from the `qgis3` definition)
- `qgis3`
- `qgis4`
- `nginx`
- `createbuckets`

## Tag meanings

- `commit-<sha>` identifies the exact image tested by a CI run.
- `edge` identifies the latest runtime image built from `master`.
- `<version>` identifies an image from a published GitHub Release.
- `buildcache` is a mutable BuildKit layer cache. It is not a deployment image.

GHCR stores the test images, runtime images, and build caches. Docker Hub only
receives runtime `edge` and version tags.
