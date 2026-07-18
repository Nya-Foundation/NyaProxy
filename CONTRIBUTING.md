# Contributing to NyaProxy

Thank you for your interest in contributing to NyaProxy! This document outlines the process for contributing to the project and helps ensure a smooth collaboration experience.

## Table of Contents
- [Code of Conduct](#code-of-conduct)
- [Development Workflow](#development-workflow)
- [Branch Strategy](#branch-strategy)
- [Setting Up Development Environment](#setting-up-development-environment)
- [Code Style and Standards](#code-style-and-standards)
- [Pull Request Process](#pull-request-process)
- [Testing](#testing)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)
- [Release Process](#release-process)

## Code of Conduct

We expect all contributors to treat each other with respect and maintain a positive, constructive environment. Please be considerate of differing viewpoints and experiences, and focus on what is best for the community and the project.

## Development Workflow

NyaProxy follows a structured development workflow with three main branches:

```
Feature Branch → dev → staging → main (production)
```

1. **dev**: Active development branch. All new features and fixes are integrated here first.
2. **staging**: Pre-production testing branch. Changes from dev are promoted here for integration testing.
3. **main**: Production branch. Only thoroughly tested code from staging reaches this branch.

This graduated deployment approach ensures stability in production while allowing active development to continue.

## Branch Strategy

- **Always create feature branches from `dev`**
- Use descriptive branch names with the following convention:
  - `feature/short-description` for new features
  - `fix/issue-description` for bug fixes
  - `docs/update-description` for documentation changes
  - `refactor/component-name` for code refactoring
- Keep branches focused on a single feature or fix

## Setting Up Development Environment

1. Fork the repository
2. Clone your fork:
```bash
git clone https://github.com/your-username/nyaproxy.git
cd nyaproxy
```
3. Add the upstream repository as a remote:
```bash
git remote add upstream https://github.com/Nya-Foundation/nyaproxy.git
```
4. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

## Code Style and Standards

NyaProxy uses automated tools to maintain consistent code style and type safety:

- **Ruff**: Python linting, import sorting, and code formatting
- **mypy**: Static type checking (see the ratchet note below)

### Type-checking ratchet

`mypy` does not yet pass on the whole codebase. `pyproject.toml`
(`[tool.mypy]`) lists the modules that are currently type-clean, and only
those are checked in CI. When you clean up a legacy module, add it to that
`files` list so it can never regress.

Our CI pipeline also checks formatting on every PR, but it's best to format
your code with `make format` before pushing. Run `make check` to reproduce
the complete CI quality checks locally.

## Pull Request Process

1. Create a branch from `dev` for your changes
2. Make your changes following our code style guidelines
3. Add tests for new features or bug fixes
4. Ensure all tests pass locally
5. Push your branch to your fork
6. Open a pull request to the `dev` branch of the main repository
7. Ensure the PR description clearly describes the changes and their purpose
8. Ensure the PR passes all CI checks
9. Address any feedback from reviewers

All pull requests require at least one approval from a maintainer before merging.

## Testing

All new code should include tests at the right level:

- Unit tests for isolated functions, classes, and edge cases
- End-to-end tests for proxy behavior that depends on real HTTP routing, config loading, queueing, retries, or upstream responses

The test suite is organized as:

```text
tests/
  unit/   # focused tests for internal logic
  e2e/    # true local proxy + mock upstream tests
```

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Or, if you use `uv`:

```bash
uv run --extra dev python -m pytest --version
```

Run the full test suite:

```bash
pytest
```

With `uv`:

```bash
uv run --extra dev python -m pytest
```

Run unit tests only:

```bash
pytest tests/unit
```

Run E2E tests only:

```bash
pytest tests/e2e -m e2e
```

With `uv`:

```bash
uv run --extra dev python -m pytest tests/e2e -m e2e
```

### End-to-End Tests

E2E tests start real local services:

- a mock upstream API on a random `127.0.0.1` port
- a NyaProxy process on a random `127.0.0.1` port
- a temporary YAML config file that points NyaProxy to the mock upstream

The mock upstream records each received request, including path, method, body, and injected upstream key. Tests then send real HTTP requests through NyaProxy and assert externally visible behavior.

Current E2E coverage includes:

- credential injection and round-robin key rotation
- retry behavior that rotates to the next key after retryable status codes such as `429`
- path policy rejection before requests reach the upstream
- key rate-limit queueing
- streaming response forwarding
- request body substitution

Keep E2E tests focused. Prefer one test per user-visible proxy behavior. Do not duplicate unit-level assertions in E2E unless the behavior only appears when the proxy, config file, queue, and upstream server run together.

For coverage information:

```bash
pytest --cov=nya tests/ --cov-report=term
```

When running E2E tests, coverage from the NyaProxy subprocess is not included in the parent pytest coverage report unless subprocess coverage is explicitly configured. Treat E2E tests primarily as behavioral checks, not coverage boosters.

Our CI pipeline automatically runs tests across supported Python versions.

## Reporting Bugs

When reporting bugs, please use the GitHub issue tracker and include:

1. A clear, descriptive title
2. Steps to reproduce the issue
3. Expected behavior
4. Actual behavior
5. Environment details (OS, Python version, etc.)
6. Screenshots or logs if applicable

## Requesting Features

Feature requests are welcome! Please include:

1. A clear description of the problem you're trying to solve
2. The solution you'd like to see
3. Alternatives you've considered
4. Any additional context or screenshots

## Release Process

Our release process is fully automated using semantic-release:

1. Changes integrated into `dev` are tested by our CI pipeline
2. When ready, changes are promoted to `staging` for further testing
3. Finally, changes are merged to `main` for production release
4. When code reaches `main`, our CI/CD pipeline:
   - Runs tests and security scans
   - Calculates the next version based on commit messages
   - Creates a GitHub release with changelog
   - Publishes the package to PyPI
   - Builds and pushes Docker images

We follow [Semantic Versioning](https://semver.org/) for version numbers.

## Commit Message Format

We use the [Conventional Commits](https://www.conventionalcommits.org/) specification for commit messages, which helps with automated versioning:

- `feat: add new feature` (triggers a minor version bump)
- `fix: resolve bug` (triggers a patch version bump)
- `docs: update documentation` (no version bump)
- `refactor: improve code structure` (no version bump)
- `test: add tests` (no version bump)
- `chore: update dependencies` (no version bump)

Breaking changes should be noted with `BREAKING CHANGE:` in the commit message, which will trigger a major version bump.

---

Thank you for contributing to NyaProxy! Your time and expertise help make this project better for everyone.
