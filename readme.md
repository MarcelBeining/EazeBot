# EazeBot
## Introduction
- Have you ever traded cryptocurrencies and lost overview of your planned buys/sells?
- Have you encountered the experience that your buy order was executed, but before you could place any stop-loss, the price rushed so deep that you made huge loss?
- Have you ever complained about that there is no exchange where you can set for one and the same coins a sell order and a stop-loss at the same time?
- Have you ever had a really good plan of trading but you got greedy or anxious and messed it up?

**Then EazeBot is your man!**

EazeBot is a Python-based Telegram bot that helps you defining trade sets that will then be carried out for you via API. A trade set is consisting of buy/sell levels and amounts and an optional stop-loss level. Breakout trading (set buy order if daily candle closes over price X) are supported, too. 

Most importantly: All popular exchanges are supported!
(for supported exchanges [see here](https://github.com/ccxt/ccxt#supported-cryptocurrency-exchange-markets "ccxt supported exchanges"))


## Installing

You require Python 2 or 3 to be installed on your system.

The simpliest way of installing EazeBot is using the pip install command:
````python
pip install EazeBot
````
or if you want to specify an installation folder:
````
pip install EazeBot -t <directory>
````

Alternatively, you can clone or download the newest release version from [Github](https://github.com/MarcelBeining/EazeBot) 
and install required packages with `python setup.py install` (or for Windows users `setup.py install` from the command prompt).


## Getting Started

After installation of EazeBot you have to set up the bot so that you can control him via Telegram and that he can access your exchanges. 
The following steps are necessary:
1. **Create a Telegram bot token using @botfather and add it to _botConfig.json_**  
   + This sounds very complicated but is rather simple. Start a chat with [Botfather](https://t.me/botfather) on Telegram and 
   follow [these instructions](https://core.telegram.org/bots#creating-a-new-bot). Once you have the token, copy it and replace 
   the *YOURBOTTOKEN* text in the *botConfig.json* file that comes with the EazeBot package.
2. **Add your Telegram ID to _botConfig.json_**
   + This ensures that only you are able to control the bot via Telegram.
   + Simply replace the *YOURTELEGRAMID* text in *botConfig.json* with your telegram ID. This is (normally) a 9-digit number. 
   If you do not know it, simply start EazeBot bot (by executing *startBot.py* with Python) and start a conversation with him
   (e.g. if you named your telegram bot @mysuperbot,  search for him in Telegram and click the Start button). The bot will tell you
   your Telegram ID (now you can add it to the json file) and that you are not authorized (yet). Now stop the bot (e.g. ctrl+c in Python) again, 
   so that it will see the changes to *botConfig.json* in step 4.
3. **Create API keys for each exchange you want to access via EazeBot and add them to _API.json_**
   + Please refer on your exchange on how to create an API token.
   + Normally, once you created an API token, you will see an API key and an API secret (sometimes also called private key).
   These two keys need to be copy-pasted into the APIs.json file from the EazeBot package. The json file already contains
   two examples on how this has to be done. Of course, if your exchange is not binance or coinbase, simply add your exchange keys analogously
   (i.e. your exchange's name is XYZ, then it should be: 
   ```apiKeyXYZ : "YOURAPIKEY",``` and ```apiSecretXYZ : "YOURAPISECRET",``` (no comma in the last line before the **}** )
   + Some exchanges also have more security factors, like a password or a uid. These are added analogously to the keys/secrets
   (i.e. your exchange's name is XYZ, then it should be: 
   ```apiPasswordXYZ : "YOURAPIPASSWORD",``` and ```apiUid : "YOURAPIUID",``` (no comma in the last line before the **}** )
   + Some exchanges allow you to determine what you can do with the created API token (e.g. read-only or no withdrawing etc.). Of course, 
   EazeBot bot needs the permission to set and cancel orders for you and to fetch your balance in order to work properly. Also, if you want
   to use the built-in donation feature, it needs the right to withdraw.
4. **Run the bot and start a conversation via Telegram.**
   + The bot will welcome you and show you a menu of things you can do. Everything should be rather self-explanatory as the bot will have a dialog with you on everything you click.


## Help

We will add a Wiki in the near future. You may also open an issue if you encounter bugs or want to suggest improvements.

## Versioning

For the versions available, see the [tags on this repository](https://github.com/MarcelBeining/eazebot/tags/). 

## Authors

* **Marcel Beining** - *Ground work* - [MBeining](https://github.com/MarcelBeining)

# License
You may copy, distribute and modify the software provided that modifications are described and licensed for free under LGPL-3. Derivatives works (including modifications or anything statically linked to the library) can only be redistributed under LGPL-3, but applications that use the library don't have to be.
See the [LICENSE](LICENSE) and [LICENSE.LESSER](LICENSE.LESSER) file for details

# Donations
If you want to support our project or simply want to say thank you for the profit you made with this bot, you can either use send your 
donation to one of the crypto addresses below, or use the built-in donation feature (Bot Info -> Donate button).

| Currency        | Address           | 
| ------------- |:-------------:|
| Bitcoin      | `17SfuTsJ3xpbzgArgRrjYSjvmzegMRcU3L` |
| ETH      | `0x2DdbDA69B27D36D0900970BCb8049546a9d621Ef`| 
| Neo | `AaGRMPuwtGrudXR5s7F5n11cxK595hCWUg` |
| XLM |`GCP2KKXERN4MRBPEKPA2PGMEC573NBNVSU5KNU5V2RHE46Y7ZDNRNUCM`|

**Thank you very much!**
