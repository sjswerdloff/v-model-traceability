"""Pytest configuration for V-model traceability tests."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "traces(contract_id): links test to a design contract")
