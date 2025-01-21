# Changelog

## development

- Fix compatibility with httpx. (#291)
- Use `SyncByteStream` instead of `ByteStream`. (#298)
- Always return `cache_metadata`. (#305)

## 0.1.1 (2nd Nov, 2024)

- Fix typing extensions not found. (#290)

## 0.1.0 (2nd Nov, 2024)

- Add support for Python 3.12 / drop Python 3.8. (#286)
- Specify usedforsecurity=False in blake2b. (#285)

## 0.0.33 (4th Oct, 2024)

- Added a [Logging](https://hishel.com/advanced/logging/) section to the documentation.

## 0.0.32 (27th Sep, 2024)

- Don't raise an exception if the `Date` header is not present. (#273)

## 0.0.31 (22nd Sep, 2024)

- Ignore file not found error when cleaning up a file storage. (#264)  
- Fix `AssertionError` on `client.close()` when use SQLiteStorage. (#269)  
- Fix ignored flags when use `force_cache`. (#271)  

## 0.0.30 (12th July, 2024)

- Fix cache update on revalidation response with content (rfc9111 section 4.3.3) (#239)
- Fix request extensions that were not passed into revalidation request for transport-based implementation (but were
  passed for the pool-based impl) (#247).
- Add `cache_private` property to the controller to support acting as shared cache. (#224)
- Improve efficiency of scanning cached responses in `FileStorage` by reducing number of syscalls. (#252)
- Add `remove` support for storages (#241)

## 0.0.29 (23th June, 2024)

- Documentation hotfix. (#244)

## 0.0.28 (23th June, 2024)

- Add `revalidated` response extension. (#242)

## 0.0.27 (31th May, 2024)

- Fix `RedisStorage` when using without ttl. (#231)

## 0.0.26 (12th April, 2024)

- Expose `AsyncBaseStorage` and `BaseStorage`. (#220)
- Prevent cache hits from resetting the ttl. (#215)

## 0.0.25 (26th March, 2024)

- Add `force_cache` property to the controller, allowing RFC9111 rules to be completely disabled. (#204)
- Add `.gitignore` to cache directory created by `FIleStorage`. (#197)
- Remove `stale_*` headers from the `CacheControl` class. (#199)

## 0.0.24 (14th February, 2024)

- Fix `botocore is not installed` exception when using any kind of storage. (#186)

## 0.0.23 (14th February, 2024)

- Make `S3Storage` to check staleness of all cache files with set interval. (#182)
- Fix an issue where an empty file in `FileCache` could cause a parsing error. (#181)
- Support caching for `POST` and other HTTP methods. (#183)

## 0.0.22 (31th January, 2024)

- Make `FileStorage` to check staleness of all cache files with set interval. (#169)
- Support AWS S3 storages. (#164)
- Move `typing_extensions` from requirements.txt to pyproject.toml. (#161)

## 0.0.21 (29th December, 2023)

- Fix inner transport and connection pool instances closing. (#147)
- Improved error message when the storage type is incorrect. (#138)

## 0.0.20 (12th December, 2023)

- Add in-memory storage. (#133)
- Allow customization of cache key generation. (#130)

## 0.0.19 (30th November, 2023)

- Add `force_cache` extension to enforce the request to be cached, ignoring the HTTP headers. (#117)
- Fix issue where sqlite storage cache get deleted immediately. (#119)
- Support float numbers for storage ttl. (#107)

## 0.0.18 (23rd November, 2023)

- Fix issue where freshness cannot be calculated to re-send request. (#104)
- Add `cache_disabled` extension to temporarily disable the cache (#109)
- Update `datetime.datetime.utcnow()` to `datetime.datetime.now(datetime.timezone.utc)` since `datetime.datetime.utcnow()` has been deprecated. (#111)

## 0.0.17 (6th November, 2023)

- Fix `Last-Modified` validation.

## 0.0.16 (25th October, 2023)

- Add `install_cache` function. (#95)
- Add sqlite support. (#92)
- Move `ttl` argument to `BaseStorage` class. (#94)

## 0.0.14 (23rd October, 2023)

- Replace `AsyncResponseStream` with `AsyncCacheStream`. (#86)
- Add `must-understand` response directive support. (#90)

## 0.0.13 (5th October, 2023)

- Add support for Python 3.12. (#71)
- Fix connections releasing from the connection pool. (#83)

## 0.0.12 (8th September, 2023)

- Add metadata into the response extensions. (#56)

## 0.0.11 (15th August, 2023)

- Add support for request `cache-control` directives. (#42)
- Drop httpcore dependency. (#40)
- Support HTTP methods only if they are defined as cacheable. (#37)

## 0.0.10 (7th August, 2023)

- Add Response metadata. (#33)
- Add API Reference documentation. (#30)
- Use stale responses only if the client is disconnected. (#28)

## 0.0.9 (1st August, 2023)

- Expose Controller API. (#23)

## 0.0.8 (31st July, 2023)

- Skip redis tests if the server was not found. (#16)
- Decrease sleep time for the storage ttl tests. (#18)
- Fail coverage under 100. (#19)

## 0.0.7 (30th July, 2023)

- Add support for `Heuristic Freshness`. (#11)
- Change `Controller.cache_heuristically` to `Controller.allow_heuristics`. (#12)
- Handle import errors. (#13)

## 0.0.6 (29th July, 2023)

- Fix `Vary` header validation. (#8)
- Dump original requests with the responses. (#7)

## 0.0.5 (29th July, 2023)

- Fix httpx response streaming.

## 0.0.4 (29th July, 2023)

- Change `YamlSerializer` name to `YAMLSerializer`.

## 0.0.3 (28th July, 2023)

- Add `from_cache` response extension.
- Add `typing_extensions` into the requirements.

## 0.0.2 (25th July, 2023)

- Add [redis](https://redis.io/) support.
- Make backends thread and task safe.
- Add black as a new linter.
- Add an expire time for cached responses.
