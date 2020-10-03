# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 
### Added
* Possibility to name the trade set [Marcel]
* Provides the possibility to update eazebot via Telegram [Marcel]


## [v2.7.2] - 2020-09-21 12:45
### Fixed
* Exchanges are added directly, if a new user starts the bot [Marcel]
* Bug with missing taxWarn setting for new user fixed [Marcel]


## [v2.7.1] - 2020-08-25 17:57
### Fixed
* Fixed double master push in dev tools [Marcel]
* Fixed iteration over trade set object during deletion of trade set [Marcel]
* Docker image does not restart automatically anymore [Marcel]


## [v2.7.0] - 2020-08-17 08:35
### Added
* Added scripts and hooks for automated multi-arch building on docker hub [Marcel]


## [v2.6.2] - 2020-08-15 10:01
### Fixed
* Bug during SL trigger [Marcel]
* Bug with trailing SLs [Marcel]
* Allow merge into master only [Marcel]
* Fix version text bug [Marcel]


## [v2.6.1] - 2020-08-05 09:10
### Fixed
* Added possibility to delete regular buying plan [Marcel]
* Fixed error when using base currency during defining buy/sell level [Marcel]


## [v2.6.0] - 2020-08-04 19:35
### Added
* Activated regular buy feature [Marcel]
* Activated "hide filled orders" feature [Marcel]

### Fixed
* Fixed empty change log [Marcel]


## [v2.5.3] - 2020-08-04 09:39
### Fixed
* Fix missing argument in delete trade set function [Marcel]


## [v2.5.2] - 2020-07-31 10:07
### Fixed
* Fixed typo that prevented trade set deletion [Marcel]


## [v2.5.1] - 2020-07-29 19:23
### Fixed
* Added necessary module dateparser to requirements [Marcel]


## [v2.5.0] - 2020-07-29 10:27
### Added
* Adding prerequisites for a new type of buy (regular buy) to buy with some interval [Marcel]
* Adding prerequisites for a new option to hide filled orders (option within each trade set) [Marcel]


## [v2.4.3] - 2020-07-26 06:38
### Fixed
* Fixed old attribute calls [Marcel]


## [v2.4.2] - 2020-07-13 11:45
### Fixed
* Fixed bug with precision calculation during balance fetching [Marcel]


## [v2.4.1] - 2020-07-13 09:08
### Fixed
* Fix version info, which now comes from __init__.py [Marcel]


## [v2.4.0] - 2020-07-13 08:57
### Added
* Added change log functionality and improved git manager [Marcel]
* Added upper cap for backup files configurable via maxBackupFileCount in botConfig.json [Marcel]

### Changed
* Transformed trade set dictionaries into class [Marcel]
* Transformed SL dictionaries into classes [Marcel]
* Prices are now kept and updated in a price class including time stamp to avoid rest api calls for prices that have already been queries recently [Marcel]
* Modules now communicate with telegram via the Telegram logging handler by handing over the chatId as extra argument [Marcel]
* More refactoring [Marcel]
* Updated ccxt and python-telegram-version [Marcel]

### Fixed
* Typos in dev_utils [Marcel]



## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.7.2...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.7.1...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.7.0...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.6.2...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.6.1...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.6.0...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.5.3...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.5.2...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.5.1...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.5.0...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.4.3...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.4.2...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.4.1...dev>
## Changes comparison
* **[Unreleased]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.4.0...dev>
