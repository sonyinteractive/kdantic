### Thank you for your interest in contributing to **kdantic** — a tool for generating Kubernetes **CustomResourceDefinition (CRD)** manifests from Pydantic models with an annotations-first approach.

#### We welcome contributions of all kinds: bug fixes, new features, documentation improvements, and more.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Contribution Areas](#contribution-areas)
- [Reporting Issues](#reporting-issues)

---

## Code of Conduct

Please be respectful and constructive in all interactions.
We are committed to providing a welcoming environment for everyone.

---

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/kdantic.git
   cd kdantic
   ```
3. **Create a branch** for your changes:
   ```bash
   git checkout -b feat/your-feature-name
   ```

---

## Development Setup

kdantic uses [uv](https://docs.astral.sh/uv/) for dependency management and
[PDM](https://pdm-project.org/) as the build backend.

### Prerequisites

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Install dependencies

```bash
uv sync --all-groups
```

### Verify the CLI works

```bash
uv run kdantic --help
```

### Run against example models

```bash
# From a file path
uv run kdantic --model-path ./examples/models.py --output-dir ./crds --overwrite-files

# From a dotted module path
uv run kdantic --models examples.models --project-root . --output-dir ./crds
```

---

## Running Tests

We use `pytest` with `pytest-cov` for testing and coverage.

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=kdantic --cov-report=term-missing
```

Please ensure **all tests pass** before submitting a PR.
New features and bug fixes should include corresponding tests.

### What to test

When contributing, consider testing:
- **Annotation resolution** (`apiVersion`, `kind`, `namespace` inference)
- **Precedence model** — annotations > `__crd_meta__` > settings > derivations
- **Pydantic v1 and v2 compatibility**
- **Optional fields** resolving to `nullable: true`
- **Enum / Literal / StrEnum** support
- **Helm mode** output correctness
- **CLI flag overrides** behaving as expected

---

## Code Style

KDantic uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Fix auto-fixable issues
uv run ruff check . --fix
```

Please ensure your code passes all Ruff checks before submitting.

### General guidelines

- Use **type annotations** throughout — this is a typing-first project
- Follow the established **precedence model** when touching resolution logic:
  ```bash
  Annotations > __crd_meta__ > Settings > Derivations
  ```
- Do not introduce `$ref` in generated schemas — kdantic uses **inlined schemas** by design
- Avoid breaking **Pydantic v1/v2 compatibility** unless explicitly discussed in an issue first
- Prefer `Protocol`-based interfaces (PEP 544) when adding new metadata contracts

---

## Submitting a Pull Request

1. Make sure your branch is up to date with `main`:
   ```bash
   git fetch origin
   git rebase origin/main
   ```
2. Ensure **tests pass** and **linting is clean**
3. Write a **clear PR description** explaining:
   - What the change does
   - Why it is needed
   - Any relevant issue numbers (e.g. `Closes #42`)
   - Whether it affects the precedence model, schema output, or CLI behaviour
4. Submit your PR against the `main` branch

### Commit Message Style

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```bash
feat: add support for X
fix: resolve issue with Y
docs: update contributing guide
test: add tests for Z
chore: bump dependencies
refactor: simplify resolution logic
```

---

## Contribution Areas

Not sure where to start? Here are some good areas to contribute:

| Area | Description |
|------|-------------|
| **Schema generation** | Improving OpenAPI schema output for edge-case Pydantic types |
| **Helm support** | Enhancing Helm-compatible CRD output |
| **Pydantic compatibility** | Ensuring v1/v2 parity across all features |
| **CLI UX** | Improving error messages, help text, or `--quiet` output |
| **Examples** | Adding real-world Pydantic model examples under `examples/` |
| **Documentation** | Clarifying the precedence model or `__crd_meta__` usage |
| **Tests** | Increasing coverage for resolution logic and edge cases |

---

## Reporting Issues

Found a bug or have a feature request?
Please [open an issue](https://github.com/your-org/kdantic/issues) and include:

- A clear description of the problem or request
- A minimal Pydantic model that reproduces the issue (if applicable)
- The CLI command you ran
- Expected vs actual YAML output (for schema/generation bugs)
- Your Python version, Pydantic version, and OS
- Any relevant error output or tracebacks

---

## License

By contributing to KDantic, you agree that your contributions will be
licensed under the [Apache 2.0 License](LICENSE).

