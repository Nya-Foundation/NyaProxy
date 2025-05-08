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
5. Install the package in development mode:
```bash
pip install -e .[dev]
```

## Code Style and Standards

NyaProxy uses automated formatting tools to maintain consistent code style:

- **Black**: For Python code formatting
- **isort**: For import sorting (with Black compatibility profile)

Before submitting your PR, run these tools locally:
```bash
isort --profile black .
black .
```

Our CI pipeline will automatically check and format code when you submit a PR, but it's best to format your code before pushing.

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

All new code should include appropriate tests:

- Unit tests for specific functions or classes
- Integration tests for API endpoints

To run tests locally:
```bash
pytest
```

For coverage information:
```bash
pytest --cov=nya tests/ --cov-report=term
```

Our CI pipeline automatically runs tests across Python versions 3.9 through 3.14.

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