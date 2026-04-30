# Changelog

## Version 1.1.12

- Bird search filters all charts: typing a search term updates Detection Timeline, Daily Trend, Top Species, Activity Heatmap, and stat banners to show only matching detections
- Search supports plain text (LIKE) and glob patterns (* ? [a-h])
- Green filter badge above charts shows active search with clear button
- Enhanced tooltips on timeline chart and heatmap cells show per-species breakdown

## Version 1.1.11

- Today banner chart bars visually dominant with pointer cursor on hover

## Version 1.1.10

- Hover tooltip on Today chart shows nearest element (bar or cumulative line)

## Version 1.1.9

- Cumulative detection line overlaid on Today chart with secondary Y axis

## Version 1.1.8

- Today chart hours padded from 00:00 to current hour (no gaps in the axis)

## Version 1.1.7

- Today banner chart shows midnight-to-now instead of rolling 24 hours

## Version 1.1.6

- Today chart axis and tooltip refinements

## Version 1.1.5

- Bug fixes and minor improvements

## Version 1.1.4

- Health panel drawer: click the green dot in the header to view system health
- Two-tier loading: instant data (pipeline status, DB size, versions, config) plus async checks (CPU temp, memory, disk, microphone, network/WiFi/Tailscale, systemd service, BirdNET model, DB integrity)
- Health dot polls every 30 seconds; colour changes: green = ok, yellow = degraded, red = down
- New module: `web/health_checks.py` with 14 probe functions
- New template: `_health_panel.html` slide-out drawer
- New API endpoints: `/api/health`, `/api/health/quick`, `/api/health/tier2/*`

## Version 0.2.19

- Server-side 60-second TTL cache for all chart API responses
- Cache-Control headers on chart endpoints for browser caching
- Loading skeleton animations while chart data is fetched

## Version 0.2.18

- Daily trend chart with dual-axis display: detection count and unique species count
- Activity heatmap: hour-of-day vs day-of-week CSS grid with green intensity scale

## Version 0.2.17

- Chart.js 4.x and date-fns adapter loaded via CDN
- Detection timeline line chart on the Charts tab
- Species frequency horizontal bar chart
- Period selector for charts: Today, 7d, 30d, All

## Version 0.2.16

- Seven new filter and pagination route tests
- Documentation updates covering v0.2.13 and v0.2.14

## Version 0.2.15

- Mobile-first responsive layout with tab navigation (Live, Charts, Species)
- Two-column layout on desktop; single-column with tabs on mobile
- Responsive stat cards
- Compass widget hidden on narrow screens

## Version 0.2.14

- Filter bar UI for the web dashboard: search by species name, confidence threshold slider, date range pickers
- Load More pagination for browsing older detections
- All filters combine so users can narrow results by name, confidence, and date simultaneously

## Version 0.2.13

- Chart API endpoints: `/api/charts/timeline`, `/api/charts/species`, `/api/charts/heatmap`, `/api/charts/trend`
- Species list endpoint (`/api/species`) with optional search query
- Detection API (`/api/detections`) now supports filtering by species, confidence, date range, and free-text search

## Version 0.0.6

- Ruff lint fixes applied across the codebase
- `.claude/` directory partially tracked in git (settings.json committable)
- Release workflow documented: `make release KIND=patch` after every fix

## Version 0.0.5

- GitHub Actions CI workflow added (`.github/workflows/ci.yml`)
- Lint job: Ruff check on Python 3.12
- Test job: unit and integration tests on Python 3.12 and 3.13
- CI installs `libportaudio2` system dependency for sounddevice

## Version 0.0.4

- Unit and integration test suites added (`tests/unit/`, `tests/integration/`)
- Tests mock sounddevice and BirdNET-Analyzer (not required locally)
- pytest markers: `integration`, `live`

## Version 0.0.3

- Makefile with incremental test caching via stamps
- `make release KIND=patch|minor|major` workflow (tests, changelog, git tag, push)
- `make bootstrap`, `make lint`, `make format`, `make docs` targets

## Version 0.0.2

- Ruff linter and formatter configuration in pyproject.toml
- Development dependencies (`.[dev]`) including pytest, ruff, sphinx, coverage

## Version 0.0.1

- Initial implementation of the core detection pipeline
- `config.py` — centralised Config dataclass with all tunable parameters
- `audio_capture.py` — sounddevice stream feeding an asyncio.Queue
- `detector.py` — BirdNET TFLite wrapper for 3-second chunk inference
- `logger.py` — async SQLite logger with auto-created schema (aiosqlite)
- `dashboard.py` — Rich live terminal dashboard for recent detections
- `main.py` — async orchestrator wiring all pipeline stages
- `cli.py` — Click CLI with options for location, threshold, device, and dashboard
- `api.py` — public Python API exposing Config, Detection, Detector, DetectionLogger
