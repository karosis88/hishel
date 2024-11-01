import pytest
from sqlalchemy import Engine, create_engine


@pytest.fixture(scope="function")
def engine():
    engine_instance: Engine = create_engine(
        "sqlite://",
    )
    yield engine_instance
    engine_instance.dispose()
