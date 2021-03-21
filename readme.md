[![GitHub](https://img.shields.io/github/tag/MarcelBeining/eazebot.svg?label=GitHub%20Release)](https://github.com/MarcelBeining/EazeBot/releases) 
[![PyPi](https://badge.fury.io/py/eazebot.svg)](https://pypi.org/project/eazebot/#history)
![Docker](https://img.shields.io/docker/v/mbeining/eazebot?sort=semver&label=Docker%20Release)
 
[![Docker Pulls](https://img.shields.io/docker/pulls/mbeining/eazebot.svg?style=flat-square)](https://hub.docker.com/r/mbeining/eazebot/)
![GitHub repo size in bytes](https://img.shields.io/github/repo-size/MarcelBeining/eazebot.svg)
[![GPLv3 license](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://github.com/MarcelBeining/EazeBot/blob/master/LICENSE)
![GitHub last commit](https://img.shields.io/github/last-commit/MarcelBeining/eazebot.svg)
![GitHub top language](https://img.shields.io/github/languages/top/MarcelBeining/eazebot.svg)
[![GitHub issues](https://img.shields.io/github/issues/MarcelBeining/EazeBot.svg)](https://GitHub.com/MarcelBeining/EazeBot/issues/)

# EazeBot
<img src="https://github.com/MarcelBeining/EazeBot/blob/master/botLogo.png" width="250">

## Introduction
- Have you ever traded cryptocurrencies and lost overview of your planned buys/sells?
- Have you encountered the experience that your buy order was executed while you slept, and before you could place any stop-loss, the price rushed so deep that you made huge loss?
- Have you ever complained about that there is no exchange where you can set for one and the same coin a sell order and a stop-loss at the same time?
- Have you ever had a really good trading plan but then you got greedy or anxious and messed it up?

**Then EazeBot is your man!**

EazeBot is a free Python-based Telegram bot that helps you defining an unlimited number of trade sets that will then be carried out for you via exchange APIs. 
Such a trade set is consisting of buy/sell levels and amounts and an optional stop-loss level. 
EazeBot lets you check the progress of your tradings, tells you about filled orders and triggered stop losses, and can tell your balances.
Breakout trading (set buy order if daily candle closes over price X) are supported, too. 

Most importantly: **All popular exchanges are supported!**
(for supported exchanges [see here](https://github.com/ccxt/ccxt#supported-cryptocurrency-exchange-markets "ccxt supported exchanges"))


## Installation
There are different ways to install EazeBot. We recommend using [Docker](#with-docker) as this guarantees system-
independent compatibility.

After the next steps, no matter if you are on Windows or Linux/Mac, you should have at least a "user_data" folder in 
your target folder containing two json files (_APIs.json_ and _botConfig.json_). Under Windows there are additional bat
files for easier execution.

### With docker
**You require [Docker](https://docs.docker.com/get-docker/) to be installed on your system.**

1. Create a new folder for EazeBot
2. Download (right click, save link as) [this File](https://github.com/MarcelBeining/EazeBot/blob/master/docker-compose.yml) to that folder.
3. Open a terminal, cd to your EazeBot directory and run 

        docker-compose run --rm eazebot --init

### With Pip
**You require [Python 3.6 or higher](https://www.python.org/downloads/) to be installed on your system.**

#### Windows
We simplified installation/configuration of the bot on Windows: 
1. Simply download (right click, save link as) [this File](https://github.com/MarcelBeining/EazeBot/blob/master/install_and_init_bot_here.bat)
) and put the file in a folder, where you wish EazeBot files to be installed. 
2. Then execute it.

#### Linux/Mac
1. The simpliest and recommended way of installing EazeBot is using the pip install command:

        sudo python3 -m pip install eazebot

2. You then need to copy the configuration files to some folder. Here is an example to make a folder in your home directory and copy the files there:

        sudo mkdir ~/eazebot
        cd ~/eazebot
        python3 -m eazebot --init"


## Getting Started
After installation of EazeBot you have to set up the bot so that you can control him via Telegram and that he can access your exchanges. 

### Obtain the necessary configuration tokens and keys
**For this the following steps are necessary:**
1. **Create a Telegram bot token using @botfather**

    * This sounds complicated but is rather simple. Start a chat with [Botfather](https://t.me/botfather) on Telegram 
      and follow [these instructions](https://core.telegram.org/bots#creating-a-new-bot). The token you get in the end 
      is needed during EazeBot configuration.

2. **Get your Telegram ID**

    + Your Telegram ID is needed during EazeBot configuration, too. It ensures that **only you** are able to control the 
      bot via Telegram. The Telegram ID is (normally) a 9-digit number. 
    + If you do not know it, you can talk to the [userinfobot](https://telegram.me/userinfobot).

3. **Create API keys for each exchange you want to access via EazeBot**

    + Please refer on your exchange on how to create an API token.
    + Some exchanges allow you to determine what you can do with the created API token (e.g. read-only or no withdrawing etc.). Of course, 
      EazeBot bot needs the permission to set and cancel orders for you and to fetch your balance in order to work properly. Also, if you want
      to use the built-in donation feature, it needs the right to withdraw.
    + Normally, once you created an API token, you will see an API key and an API secret (sometimes also called private 
      key). This information is needed during EazeBot configuration, so save it temporarily somewhere. 
    + Some exchanges also have more security factors, like a API password (not your exchange login password!)or an 
      uid. If existent, please temporarily save this information as you will need it for EazeBot configuration, too.

### Interactive configuration

#### With docker
Run the following command in your EazeBot folder:
````
docker-compose run --rm eazebot --config
````

#### With pip / others
Run the following command in your EazeBot folder:
````
python3 -m eazebot --config"
````

### Manual configuration
We recommend the interactive configuration, as editing the json files in the wrong way may lead to EazeBot not being 
functional! However, here is how you can configure EazeBot manually (all json files are located in the _user_data_ 
folder within your EazeBot folder, assuming you have [installed EazeBot](#installation) correctly):
+ The Telegram bot token needs to be inserted into the *botConfig.json* file: Replace the *PLACEHOLDER* text to the 
 right of the *telegramAPI* key (keep the quotation marks!).
+ Your Telegram ID needs to be inserted into the *botConfig.json* file: Replace the *PLACEHOLDER* text to the 
 right of the *telegramUserId* key (keep the quotation marks!).
+ Each API key information needs to be inserted into the *APIs.json* between the brackets in the following format:
    ````json
    {
    "exchange": "xxx",
    "key": "xxx",
    "secret": "xxx",
    "password": "xxx",
    "uid": "xxx"
  }
    ````
    + The value under _exchange_ needs to be in lower case and be one of the exchanges supported by 
    [ccxt](https://github.com/ccxt/ccxt/wiki/Exchange-Markets) (i.e. a value from the _id_ column).
    + As mentioned above, _password_ and _uid_ are only necessary on some exchanges. If not available, completely discard
     these lines.

### Start EazeBot
Now you can run the bot and start a conversation via Telegram.**
+ On Windows, double-click on _startBot.bat_ in your EazeBot folder.
+ On Linux/Mac use the terminal, go to your EazeBot folder and run this command:
````
python3 -m eazebot
````
1) Thereafter you should start a conversation with your bot (see 
[Token creation with bot father](#obtain-the-necessary-configuration-tokens-and-keys)) on Telegram.
2) The bot will welcome you and show you a menu of things you can do. Everything should be rather self-explanatory as 
the bot will have a dialog with you on everything you click.
3) Enjoy!


### Update EazeBot
From time to time you should update EazeBot:
1. Stop EazeBot with Telegram by clicking on _Settings_ in the main menu, then \*Stop bot\* and then confirm the stop 
dialog.
2. The way of updating depends on your OS and installation:
    + Windows:
        + Double-clicking on _updateBot.bat_ in your EazeBot folder
    + Linux/Mac:
        + Execute `python -m pip install -U eazebot` when [installed with pip](#with-pip)
        + Executing `docker-compose pull` when [installed with docker](#with-docker)
3. [Restart the Bot](#start-eazebot)

## Help

We have added a [Wiki](https://github.com/MarcelBeining/EazeBot/wiki) with more details on installing and handling the bot. You may also open an issue if you encounter bugs or want to suggest improvements.

## Versioning

For the versions available, see the [tags on this repository](https://github.com/MarcelBeining/eazebot/tags/). 

## Authors

* **Marcel Beining** - *Ground work* - [MBeining](https://github.com/MarcelBeining)

# License
You may copy, distribute and modify the software provided that modifications are described and licensed for free under LGPL-3. Derivatives works (including modifications or anything statically linked to the library) can only be redistributed under LGPL-3, but applications that use the library don't have to be.
See the [LICENSE](LICENSE) and [LICENSE.LESSER](LICENSE.LESSER) file for details

# Features to be added
Depending on my time and/or putative incentives (donations), I plan to add the following features (any suggestions welcome):
- add instant buy / sell
- move profit into fiat after trade set finished
- option to avoid flash crash SL triggering by checking e.g. after 5 min if SL is still reached.
- add info to the trade set what the current gain/loss would be when price reaches SL
- update the Wiki

# Donations
If you want to support our project or simply want to say thank you for the profit you made with this bot, you can either use send your 
donation to one of the crypto addresses below, or use the built-in donation feature (Bot Info -> Donate button).

| Currency        | Address           | 
| ------------- |:-------------:|
| Bitcoin      | `bc1q5wfzxdk3xhujs6589gzdeu6fgqpvqrel5jzzt2` |
| ETH      | `0xE0451300D96090c1F274708Bc00d791017D7a5F3`| 
| Neo | `AaGRMPuwtGrudXR5s7F5n11cxK595hCWUg` |
| XLM |`GCEAF5KYYUJSYPEDAWTZUBP4TE2LUSAPAFNHFSY54RA4HNLBVYOSFM6K`|
| USDT (ERC20) |`0x55b1be96e951bfce21973a233970245f728782f1`|
| USDT (TRC20) |`TGTh3ts5sdhBnGDm9aacUHLmdryPnCa8HJ`|


New! Also accepting payments via beerpay :beers:!
[![Beerpay](https://beerpay.io/MarcelBeining/EazeBot/badge.svg?style=beer-square)](https://beerpay.io/MarcelBeining/EazeBot) 

Want a new feature to be implemented to EazeBot? [![Beerpay](https://beerpay.io/MarcelBeining/EazeBot/make-wish.svg?style=flat-square)](https://beerpay.io/MarcelBeining/EazeBot?focus=wish)

**Thank you very much!**
