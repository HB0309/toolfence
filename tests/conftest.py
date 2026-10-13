# tests/conftest.py — shared pytest configuration for ToolFence.


def pytest_addoption(parser):
    parser.addoption(
        "--skip-network",
        action="store_true",
        default=False,
        help="Skip tests that require network access or fetching target repos.",
    )
