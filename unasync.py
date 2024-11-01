#!venv/bin/python
import os
import re
import sys

SUBS = [
    ("async def", "def"),
    ("async with", "with"),
    (r"await \(", "("),
    ("await ", ""),
    ("async for", "for"),
    ("__aiter__", "__iter__"),
    ("AsyncIterator", "Iterator"),
    ("AsyncFileStorage", "FileStorage"),
    ("AsyncBaseStorage", "BaseStorage"),
    ("AsyncFileManager", "FileManager"),
    ("MockAsyncConnectionPool", "MockConnectionPool"),
    ("MockAsyncTransport", "MockTransport"),
    ("AsyncRedisStorage", "RedisStorage"),
    ("AsyncSQLiteStorage", "SQLiteStorage"),
    ("AsyncInMemoryStorage", "InMemoryStorage"),
    ("AsyncS3Storage", "S3Storage"),
    ("AsyncSQLStorage", "SQLStorage"),
    ("AsyncS3Manager", "S3Manager"),
    ("import redis.asyncio as redis", "import redis"),
    ("AsyncCacheTransport", "CacheTransport"),
    ("AsyncBaseTransport", "BaseTransport"),
    ("AsyncCacheClient", "CacheClient"),
    ("AsyncClient", "Client"),
    ("AsyncIterable", "Iterable"),
    ("AsyncCacheStream", "CacheStream"),
    ("AsyncByteStream", "ByteStream"),
    ("AsyncCacheConnectionPool", "CacheConnectionPool"),
    ("handle_async_request", "handle_request"),
    ("aread", "read"),
    ("aclose", "close"),
    ("asleep", "sleep"),
    ("AsyncLock", "Lock"),
    (
        "from httpcore._async.interfaces import AsyncRequestInterface",
        "from httpcore._sync.interfaces import RequestInterface",
    ),
    ("from hishel._async._transports", "from hishel._sync._transports"),
    ("AsyncRequestInterface", "RequestInterface"),
    ("sqlalchemy.ext.asyncio.AsyncSession", "sqlalchemy.orm.Session"),
    ("sqlalchemy.ext.asyncio.AsyncEngine", "sqlalchemy.Engine"),
    ("AsyncEngine", "Engine"),
    ("create_async_engine", "create_engine"),
    ("from sqlalchemy.ext.asyncio import", "from sqlalchemy import"),
    ("sqlalchemy.ext.asyncio.AsyncAttrs, ", ""),
    (".stream_scalars", ".scalars"),
    (r", self._engine.begin\(\) as conn", ""),
    (r"conn.run_sync\(self\.\_base.metadata.create_all\)", "self._base.metadata.create_all(self._engine)"),
    ("__aenter__", "__enter__"),
    ("__aexit__", "__exit__"),
    ("*@pytest.mark.anyio", ""),
    (r'*@pytest.mark.parametrize\("anyio_backend", \["asyncio"\]\)', ""),
    (", anyio_backend", ""),
    ("anyio_backend, ", ""),
    (r"\+aiosqlite", ""),
    ("anysqlite", "sqlite3"),
]
COMPILED_SUBS = [(re.compile(r"(^|\b)" + regex + r"($|\b)"), repl) for regex, repl in SUBS]

USED_SUBS = set()


def unasync_line(line):
    for index, (regex, repl) in enumerate(COMPILED_SUBS):
        old_line = line
        line = re.sub(regex, repl, line)
        if index not in USED_SUBS:
            if line != old_line:
                USED_SUBS.add(index)
    return line


def unasync_file(in_path, out_path):
    with open(in_path) as in_file:
        with open(out_path, "w", newline="") as out_file:
            for line in in_file.readlines():
                line = unasync_line(line)
                out_file.write(line)


def unasync_file_check(in_path, out_path):
    with open(in_path) as in_file:
        with open(out_path) as out_file:
            for in_line, out_line in zip(in_file.readlines(), out_file.readlines()):
                expected = unasync_line(in_line)
                if out_line != expected:
                    print(f"unasync mismatch between {in_path!r} and {out_path!r}")
                    print(f"Async code:         {in_line!r}")
                    print(f"Expected sync code: {expected!r}")
                    print(f"Actual sync code:   {out_line!r}")
                    sys.exit(1)


def unasync_dir(in_dir, out_dir, check_only=False):
    for dirpath, dirnames, filenames in os.walk(in_dir):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            rel_dir = os.path.relpath(dirpath, in_dir)
            in_path = os.path.normpath(os.path.join(in_dir, rel_dir, filename))
            out_path = os.path.normpath(os.path.join(out_dir, rel_dir, filename))
            print(in_path, "->", out_path)
            if check_only:
                unasync_file_check(in_path, out_path)
            else:
                unasync_file(in_path, out_path)


def main():
    check_only = "--check" in sys.argv
    unasync_dir("hishel/_async", "hishel/_sync", check_only=check_only)
    unasync_dir("tests/_async", "tests/_sync", check_only=check_only)

    if len(USED_SUBS) != len(SUBS):
        unused_subs = [SUBS[i] for i in range(len(SUBS)) if i not in USED_SUBS]

        from pprint import pprint

        print("This SUBS was not used")
        pprint(unused_subs)
        exit(1)


if __name__ == "__main__":
    main()
