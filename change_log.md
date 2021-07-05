# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v2.13.0] - 2021-07-04 14:53
### Changed
* Using single point of truth for cost handling [Marcel]
* Important attributes are stored in a dict now for easier version changes in the future [Marcel]


## [v2.12.0] - 2021-03-21 11:20
### Changed
* Updated donation addresses [Marcel]

### Fixed
* Fix problems with creating a trading set using a signal text [Marcel]


## [v2.11.1] - 2021-02-23 00:54
### Fixed
* Fixed problem with message container during update check [Marcel]


## [v2.11.0] - 2021-02-23 00:40
### Added
* Pasting raw text containing formatted buy signals when defining a new trade set is now supported in a limited range. [Marcel]
* The leftover coins (coins not sold) are now mentioned during trade set activation and deletion [Marcel]

### Changed
* Changing donation addresses [Marcel]


## [v2.10.1] - 2021-01-20 16:41
### Fixed
* Fix problem with already deleted messages [Marcel]


## [v2.10.0] - 2021-01-20 16:05
### Fixed
* Fixed autosave problem that arised from new telegram version. [Marcel]


## [v2.9.3] - 2021-01-08 09:45
### Fixed
* User is now informed if there are problems with showing a trade set [Marcel]


## [v2.9.2] - 2020-12-28 10:41
### Fixed
* Fixed error with new python telegram bot version [Marcel]


## [v2.9.1] - 2020-11-22 18:06
### Fixed
* Fix dev tool dependency [Marcel]


## [v2.9.0] - 2020-11-22 17:46
### Added
* Provides the possibility to update eazebot via Telegram [Marcel]

### Changed
* Instead of GitHub commit messages, the changes written in the change log are now shown in Telegram [Marcel]

### Fixed
* Fixed version comparison which was not working correctly for some versions. [Marcel]
* Fixed change log template to correctly list the branch comparisons at the bottom [Marcel]
* Fix dependency on dev package pystache when only loading ChangeLog class for accessing changes [Marcel]
* Trade set name now also appears in the 1 year buy warning [Marcel]


## [v2.8.0] - 2020-10-03 11:55
### Added
* Possibility to name the trade set [Marcel]


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
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.12.0...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.11.1...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.11.0...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.10.1...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.10.0...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.9.3...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.9.2...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.9.1...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.9.0...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.8.0...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.7.2...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.7.1...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.7.0...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.6.2...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.6.1...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.6.0...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.5.3...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.5.2...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.5.1...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.5.0...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.4.3...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.4.2...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.4.1...v2.13.0>
* **[v2.13.0]**: <https://github.com/MarcelBeining/EazeBot/compare/v2.4.0...v2.13.0>
