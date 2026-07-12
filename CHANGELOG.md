# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Introduced `OfficialAHNBase` and `GeotilesAHNBase` to cleanly separate COPC and LAZ fetching logic.
- Index downloading and caching functionality now shared across `OfficialAHNBase`, `GeotilesAHNBase`, and `CanElevation`.

### Fixed
- `IGNLidarHD` now directly queries the official Géoplateforme API, bypassing the deprecated OVH mirror.
- `AHN2` through `AHN6` now route directly to the official `basisdata.nl` 1x1km COPC proxies.
- Implemented "Docs as Code" using `pytest-codeblocks` to test quickstart block in `README.md`.
- Started keeping a changelog :)
