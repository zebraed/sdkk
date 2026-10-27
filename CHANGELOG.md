# Changelog

## [2.1.0] - 2026-10-27

### Added

- Main window with Setup, I/O, Mirror, and Advanced tabs
- Pose strip, presets, and Driven Edit for keying the current pose
- History of driver and driven sets, and a Driven Key Viewer
- Preferences, with English and Japanese
- Export, import, and delete commands in the Tools menu
- Bundled Qt.py, so the GUI needs nothing else installed
- Retarget driven keys onto other driver and driven nodes

### Changed

- Copy, mirror, export, and the mirror check take `role` (driver or driven) instead of `side`, and default to the driver side
- `mirror_driven_keys` accepts `search` and `replace` without a rule object

## [2.0.0] - 2026-09-30

### Added

- Driven key commands for Maya: set, update, remove, delete, copy, and rename
- Mirror driven keys by a name rule, and check whether the mirrored side matches
- Export and import driven keys as JSON
- Convert timeline animation into driven keys
- Clean up broken driven keys

## [1.0.0] - 2020-08-06

### Added

- Key several driven attributes from one driver
- Update a key that already exists at the current driver value
- Delete the driven key of a driver and driven pair
- Mirror driven keys by replacing a name token, such as `_L` with `_R`

### Changed

- The window lists the driven attributes and the keys on the current driver

## [0.0.1] - 2019-10-02

### Added

- First release
- Set a driven key from the current driver and driven values
- A small window to pick one driver attribute, one driven attribute, and key it

[2.1.0]: https://github.com/zebraed/sdkk/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/zebraed/sdkk/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/zebraed/sdkk/compare/v0.0.1...v1.0.0
[0.0.1]: https://github.com/zebraed/sdkk/releases/tag/v0.0.1
