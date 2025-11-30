# Contributing to Discord Selfbot Logger

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/your-username/Discord-selfbot-logger.git`
3. Create a branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes
6. Commit: `git commit -m 'Add your feature'`
7. Push: `git push origin feature/your-feature-name`
8. Open a Pull Request

## Code Style

- Follow PEP 8 Python style guide
- Use type hints where appropriate
- Add docstrings to functions and classes
- Keep functions focused and single-purpose
- Write meaningful commit messages

## Testing

- Add unit tests for new features
- Ensure all tests pass: `python -m pytest tests/`
- Test manually before submitting PR

## Security

- **Never commit**:
  - `.env` files
  - `accounts.json` with real tokens
  - `settings.json` with sensitive data
  - Any hardcoded tokens or secrets

- Always use environment variables or encrypted storage for sensitive data

## Pull Request Process

1. Update README.md if needed
2. Update tests if adding new features
3. Ensure code passes linting
4. Request review from maintainers

## Questions?

Open an issue for questions or discussions about features.

