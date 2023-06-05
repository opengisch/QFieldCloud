# Development

## Collaboration

All code collaboration happens in GitHub using a `git` repository.

### Version control

Commits should have a concise but descriptive messages.

When needed, additional commit body with detailed explanation should be added, which usually matches the pull request description.

### Pull requests (PRs)

Each bugfix or feature should be developed in a separate branch.

PR titles should be short and descriptive.

When the task is defined in a GitHub issue or another task management platform, then:

- the PR description must refer to that task;
- the branch name must be prefixed with the corresponding task id from the other platform.
- ideally the PR and task title should be the same;

Before closing a PR and in order to ease the changelog generation, the PR must be tagged with a combination of a single "version" tag and "type" tag:

Version tags:

- `patch` - minor patch that fixes a bug or adds a small feature;
- `minor` - a PR that contains a migration or changes the application logic;
- `major` - A PR that contains major breaking changes. Only used when reached

Type tags:

- `bug` - fixes an existing bug/undesired behavior;
- `feature` - adds a new feature/functionality;
- `chore` - improves docs, bumps dependencies, changes CI, refactors code.

When creating a new PR, the preferred method of updating with upstream changes is rebasing over merging.

After opening a pull-request and asking for a review, please do not force-push.

### Unfinished PRs

All unfinished PR must have a title prefixed with `[WIP]` and optionally marked as "Draft PR" on GitHub.

### Submodule updates

Submodule updates are done in a PR, so if any test adjustments are needed, they must be part of the same (merge) commit on `master`.
