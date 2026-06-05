# AGENTS.md

This project contains a blueprint and a set of guidelines for creating and deploying a RAG solution in OCI Enterprise AI, based on OCI Vector Store and the Responses API.

## Project Guidelines

- All documentation and Markdown files must always be written in English.
- Specifications must be written before implementation and stored under the `specs/` directory.
- Code must be generated only after the relevant specification exists.
- Implemented code must conform to the approved specification.
- Python code must be formatted with `black`.
- Python code must be checked with `pylint`.
- New functionality must include unit tests written with `pytest`.
- Unit tests must provide sufficient coverage, with a target above 80%.
- Done means: code formatted, tests written, pylint checks completed, tests executed, and all test and pylint issues resolved.

## Python Source Header

Every Python source file must start with a multiline header using this format:

```python
"""
Author: L. Saetta
Date last modified: YYYY-MM-DD
License: MIT
Description: Brief description of the responsibilities and functions contained in this file.
"""
```

Use the actual modification date when creating or updating a Python source file.

## Spec-Driven Development Workflow

1. Write or update the specification in `specs/`.
2. Review the specification for scope, behavior, acceptance criteria, and test expectations.
3. Implement the code according to the specification.
4. Add or update unit tests.
5. Run formatting, linting, and tests.
6. Fix all issues before considering the work done.
