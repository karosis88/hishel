import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@pytest.fixture(scope="function")
async def engine():
    engine_instance: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite://",
    )
    yield engine_instance
    await engine_instance.dispose()
