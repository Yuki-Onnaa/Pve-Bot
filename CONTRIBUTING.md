# Contributing to Pve-Bot

Thank you for your interest in contributing! This document provides guidelines for contributing to the Pve-Bot project.

## Code of Conduct

This project adheres to the Contributor Covenant Code of Conduct. By participating, you are expected to uphold this code.

## Getting Started

### Prerequisites
- Python 3.9+
- Git
- Discord bot token (for testing)

### Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Pve-Bot.git
   cd Pve-Bot
   ```

3. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # Development dependencies
   ```

5. Set up pre-commit hooks:
   ```bash
   pre-commit install
   ```

6. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Workflow

### Code Style

- Follow PEP 8 guidelines
- Use Black for code formatting: `black .`
- Use isort for import sorting: `isort .`
- Maximum line length: 120 characters
- Docstrings required for all public functions

### Naming Conventions

```python
# Functions and variables: snake_case
def calculate_threat_score():
    pass

member_count = 42

# Classes: PascalCase
class MemberRecord:
    pass

# Constants: UPPER_SNAKE_CASE
MAX_THREAT_SCORE = 100
```

### Testing

- Write tests for all new features
- Run tests before submitting PR: `pytest`
- Maintain >80% code coverage
- Use descriptive test names

```python
def test_threat_score_increases_with_dormancy():
    """Verify threat score increases when member is dormant."""
    pass
```

### Commit Messages

Follow conventional commits format:

```
type(scope): subject

body

footer
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

Example:
```
feat(analytics): add churn prediction algorithm

Implement machine learning model to predict member churn
based on activity patterns and engagement metrics.

Closes #123
```

### Linting & Formatting

Before committing, run:
```bash
# Format code
black .
isort .

# Lint code
flake8 .
pylint vouch_bot.py dashboard.py data_store.py

# Run tests
pytest tests/ -v --cov

# Type checking (if using type hints)
mypy .
```

## Submitting Changes

1. Push your branch to your fork
2. Create a Pull Request against the main repository
3. Fill out the PR template completely
4. Link any related issues
5. Ensure CI/CD checks pass

## Pull Request Review

- Expect feedback and be open to suggestions
- Make requested changes in new commits (don't force push)
- Resolve conversations once addressed
- Re-request review once changes complete

## Reporting Bugs

### Before Submitting

1. Check existing issues (open and closed)
2. Enable debug logging and capture error messages
3. Verify bug exists on latest version

### Submitting Bug Report

Use the bug report template and include:
- Steps to reproduce
- Expected behavior
- Actual behavior
- Environment details
- Error logs/screenshots

## Feature Requests

1. Use the feature request issue template
2. Explain the use case clearly
3. Provide examples of expected behavior
4. Discuss potential implementation approach

## Documentation

- Update docs for any user-facing changes
- Add docstrings to new functions
- Update README.md for command changes
- Update API_REFERENCE.md for new endpoints

## Release Process

1. Version follows [Semantic Versioning](https://semver.org/)
2. Update CHANGELOG.md
3. Tag release: `git tag v2.1.0`
4. Create GitHub release with changelog

## Recognition

Contributors will be recognized in:
- README.md contributors section
- Release notes
- GitHub contributors graph

## Questions?

- Open a discussion on GitHub
- Check existing documentation
- Review closed issues for similar questions

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

---

**Thank you for contributing to Pve-Bot! 🎉**
