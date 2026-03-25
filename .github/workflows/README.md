# GitHub Actions Workflows

This directory contains CI/CD workflows for the LocalCode project.

## Workflows

### 1. CI (`ci.yml`)

**Triggers:**
- Pull requests to `main`, `develop`, or `feat/**` branches
- Pushes to `main` or `develop` branches

**Jobs:**

#### Lint
- Runs `ruff check` for code quality
- Runs `ruff format --check` for formatting
- Continues on error (non-blocking)

#### Test
- Runs full test suite with coverage
- Tests on Python 3.12
- Generates coverage reports (XML, HTML, term)
- Uploads coverage to Codecov
- Uploads test results as artifacts
- Creates test summary in PR

#### Test Summary
- Aggregates results from lint and test jobs
- Fails if tests fail
- Provides overall status

**Artifacts:**
- `test-results-{python-version}` - JUnit XML and HTML coverage
- Retention: 30 days

### 2. Tests (`test.yml`)

**Triggers:**
- Pull requests to `main` or `develop`
- Pushes to `main` or `develop`

**Jobs:**

#### Test
- Runs pytest with coverage
- Uploads coverage to Codecov
- Creates test summary

**Simpler workflow focused on just running tests.**

### 3. PR Comment (`pr-comment.yml`)

**Triggers:**
- When CI workflow completes successfully

**Jobs:**

#### Comment
- Posts test results as a comment on the PR
- Shows test statistics
- Links to full test results

**Requires:**
- `pull-requests: write` permission

## Setup Instructions

### 1. Enable GitHub Actions

GitHub Actions should be enabled by default. If not:

1. Go to repository Settings
2. Navigate to Actions → General
3. Enable "Allow all actions and reusable workflows"

### 2. Configure Codecov (Optional)

For coverage reporting:

1. Sign up at [codecov.io](https://codecov.io)
2. Add your repository
3. Get your Codecov token
4. Add it as a repository secret:
   - Go to Settings → Secrets and variables → Actions
   - Click "New repository secret"
   - Name: `CODECOV_TOKEN`
   - Value: Your Codecov token

**Note:** Codecov is optional. Tests will still run without it.

### 3. Branch Protection Rules

Recommended branch protection for `main`:

1. Go to Settings → Branches
2. Add rule for `main` branch
3. Enable:
   - ✅ Require a pull request before merging
   - ✅ Require status checks to pass before merging
   - ✅ Require branches to be up to date before merging
   - ✅ Status checks: `test`, `lint`
   - ✅ Require conversation resolution before merging

### 4. Update Badge URLs

In `README.md`, replace `YOUR_USERNAME` with your GitHub username:

```markdown
[![CI](https://github.com/YOUR_USERNAME/localcode/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/localcode/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/YOUR_USERNAME/localcode/branch/main/graph/badge.svg)](https://codecov.io/gh/YOUR_USERNAME/localcode)
```

## Workflow Features

### Caching

- **pip cache**: Speeds up dependency installation
- **uv cache**: Caches uv packages for faster installs

### Matrix Strategy

Currently tests on:
- Python 3.12

To add more Python versions, update the matrix in `ci.yml`:

```yaml
strategy:
  matrix:
    python-version: ["3.12", "3.13"]
```

### Test Summary

Each workflow run creates a summary visible in:
- PR checks
- Actions tab
- Workflow run page

Summary includes:
- Test count
- Failures and errors
- Coverage information
- Links to artifacts

### Artifacts

Test artifacts are uploaded and retained for 30 days:
- `junit.xml` - Test results in JUnit format
- `htmlcov/` - HTML coverage report

Download from:
- Actions tab → Workflow run → Artifacts section

## Local Testing

Test the workflow locally before pushing:

```bash
# Install act (GitHub Actions local runner)
brew install act

# Run workflow locally
act pull_request

# Run specific job
act -j test
```

## Troubleshooting

### Tests fail in CI but pass locally

**Possible causes:**
1. Environment differences
2. Missing dependencies
3. Timing issues

**Solutions:**
```bash
# Test with same Python version as CI
python3.12 -m pytest

# Clean install dependencies
rm -rf .venv
uv sync
uv pip install -e ".[test]"
```

### Codecov upload fails

**Solution:**
- Check `CODECOV_TOKEN` is set correctly
- Verify token has correct permissions
- Check Codecov service status

**Note:** Workflow is configured with `fail_ci_if_error: false`, so Codecov failures won't block PRs.

### Workflow doesn't trigger

**Check:**
1. Workflow file is in `.github/workflows/`
2. YAML syntax is valid
3. Branch matches trigger conditions
4. Actions are enabled in repository settings

### Permission errors

If PR comment workflow fails:

1. Go to Settings → Actions → General
2. Scroll to "Workflow permissions"
3. Select "Read and write permissions"
4. Save

## Customization

### Change test command

Edit `ci.yml`:

```yaml
- name: Run tests with coverage
  run: |
    pytest \
      --cov=. \
      --cov-report=xml \
      -v \
      --your-custom-flags
```

### Add linting tools

Add to the lint job:

```yaml
- name: Run mypy
  run: |
    uv pip install --system mypy
    mypy .

- name: Run black
  run: |
    uv pip install --system black
    black --check .
```

### Add deployment

Create a new workflow for deployment:

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      # Your deployment steps
```

## Monitoring

### View workflow runs

1. Go to Actions tab
2. Select workflow
3. View runs and logs

### Check test trends

- Codecov provides test coverage trends
- GitHub Actions shows workflow run history
- Artifacts contain detailed reports

## Best Practices

1. **Keep workflows fast** - Use caching, parallel jobs
2. **Fail fast** - Stop on first failure with `fail-fast: true`
3. **Clear names** - Use descriptive job and step names
4. **Artifacts** - Upload important files for debugging
5. **Summaries** - Provide clear test summaries
6. **Security** - Use secrets for sensitive data
7. **Versioning** - Pin action versions (e.g., `@v4`)

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Workflow Syntax](https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions)
- [pytest Documentation](https://docs.pytest.org/)
- [Codecov Documentation](https://docs.codecov.com/)
