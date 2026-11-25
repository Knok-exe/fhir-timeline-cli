# Changelog

## 0.1.1
- `--until 2024` / `--until 2024-06` now run through the end of that year or month (they used to
  stop on the first day)
- Warn on stderr when paging stops at the page limit, instead of silently showing a partial
  timeline
- A server that answers 200 with non-JSON (e.g. a wrong base URL serving HTML) is now an error,
  not an empty timeline
- Timestamps with any number of fractional-second digits parse on Python 3.10
- CI runs on Python 3.10 to 3.13; removed the unused `FALLBACK_SERVER` constant; 35 tests

## 0.1.0
- Timeline CLI: search, pagination, flags, table/markdown/csv, `--demo`
- Retry/backoff, `--since/--until/--code/--latest`, clipped-text ellipsis
- 27 tests incl. local-HTTP integration tests
