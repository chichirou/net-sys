# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-05-27

### Added
- Per-NIC traffic monitoring (dropdown to select interface)
- IPv4 / IPv6 protocol-level packet statistics (Windows)
- "ALL" aggregated traffic mode (default)
- Real-time GPU metrics update via LHM (1s interval, was 5s)
- DASHBOARD layout drag-and-drop editor
- System health score (0-100) with weighted CPU/MEM/temp/SSD/GPU aggregation
- AI-style diagnostic marquee in HEALTH card
- Color-coded GPU usage (cyan solid) + power (yellow dashed) chart
- Window width lock (fixed 440px) with auto-correction
- Auto-hide scrollbar (recovers right-edge space)
- SI-formatted packet counts (e.g. `2.78M pkts`)

### Changed
- Improved startup speed: parallel collector initialization
- Reduced per-second overhead: PowerShell calls cached in background thread
- LHM HTTP cache: 5s → 1s (for smoother live charts)
- MEM/HEALTH card width ratio: now auto-balanced for visual symmetry
- Header layout: `EDIT LAYOUT` and `PIN` moved to second row beside MODE
- Various visual refinements (donut sizes, spacing, color matching)

### Fixed
- Bug: NIC dropdown selection had no effect (chart always showed aggregated)
- Bug: HEALTH `[ system score ]` text clipping at narrow widths
- Bug: `_evaluate_alerts` key mismatch (CPU temp lookup)
- Bug: MEM card right padding excessive when widened

## [1.0.0] - earlier

- Initial release
