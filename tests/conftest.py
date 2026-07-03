import pytest


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False,
                     help="run tests marked 'live' against the real Kalshi API")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip = pytest.mark.skip(reason="needs --run-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
