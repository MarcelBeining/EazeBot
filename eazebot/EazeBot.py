#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# EazeBot
# Free python/telegram bot for easy execution and surveillance of crypto trading plans on multiple exchanges.
# Copyright (C) 2019
# Marcel Beining <marcel.beining@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
"""This module contains all functions necessary for starting the Bot"""

# %% import modules
import logging
import logging.handlers  # necessary if run as main script and not interactively...dunno why
import re
import time
import datetime as dt
import json
import signal
from typing import Union, List

import requests
import base64
import os
from telegram import (ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Update)
from telegram.bot import Bot
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters,
                          ConversationHandler, CallbackQueryHandler, CallbackContext)
from telegram.error import BadRequest
from eazebot.tradeHandler import tradeHandler
from eazebot.auxiliaries import clean_data, load_data, save_data, backup_data

logFileName = 'telegramEazeBot'
MAINMENU, SETTINGS, SYMBOL, NUMBER, TIMING, INFO = range(6)

logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
rootLogger = logging.getLogger()
rootLogger.handlers = []  # delete old handlers in case bot is restarted but not python kernel
rootLogger.setLevel('INFO')  # DEBUG
fileHandler = logging.handlers.RotatingFileHandler("{0}/{1}.log".format(os.getcwd(), logFileName), maxBytes=1000000,
                                                   backupCount=5)
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)
consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)

with open(os.path.join(os.path.dirname(__file__), '__init__.py')) as fh:
    thisVersion = re.search(r'(?<=__version__ = \')[0-9.]+', str(fh.read())).group(0)
# %% init menues
mainMenu = [['Status of Trade Sets', 'New Trade Set', 'Trade History'], ['Check Balance', 'Bot Info'],
            ['Add/update exchanges (APIs.json)', 'Settings']]
markupMainMenu = ReplyKeyboardMarkup(mainMenu)  # , one_time_keyboard=True)

tradeSetMenu = [['Add buy position', 'Add sell position', 'Add initial coins'],
                ['Add stop-loss', 'Show trade set', 'Done', 'Cancel']]
markupTradeSetMenu = ReplyKeyboardMarkup(tradeSetMenu, one_time_keyboard=True)

# init base variables
# %% load bot configuration
if not os.path.isfile("botConfig.json"):
    raise FileNotFoundError(f"botConfig.json not found in path {os.getcwd()}! Probably you did not initalize the config"
                            f"files with command 'python -c \"from eazebot.auxiliaries import copy_user_files; copy_user_files()\"'")
with open("botConfig.json", "r") as fin:
    __config__ = json.load(fin)
if isinstance(__config__['telegramUserId'], str) or isinstance(__config__['telegramUserId'], int):
    __config__['telegramUserId'] = [int(__config__['telegramUserId'])]
elif isinstance(__config__['telegramUserId'], list):
    __config__['telegramUserId'] = [int(val) for val in __config__['telegramUserId']]
if isinstance(__config__['updateInterval'], str):
    __config__['updateInterval'] = int(__config__['updateInterval'])
if 'minBalanceInBTC' not in __config__:
    __config__['minBalanceInBTC'] = 0.001
if isinstance(__config__['minBalanceInBTC'], str):
    __config__['minBalanceInBTC'] = float(__config__['minBalanceInBTC'])
if 'debug' not in __config__:
    __config__['debug'] = False
if isinstance(__config__['debug'], str):
    __config__['debug'] = bool(int(__config__['debug']))
if 'extraBackupInterval' not in __config__:
    __config__['extraBackupInterval'] = 7


def signal_handler(signal, frame):
    global interrupted
    interrupted = True


interrupted = False
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGABRT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# define  helper functions
def broadcast_msg(bot, user_id, msg, level='info'):
    # put msg into log with userId
    getattr(rootLogger, level.lower())('User %d: %s' % (user_id, msg))
    if __config__['debug'] or level.lower() != 'debug':
        # return msg to user
        count = 0
        while count < 5:
            try:
                bot.send_message(chat_id=user_id, text=level + ': ' + msg, parse_mode='markdown')
                break
            except TypeError:
                pass
            except Exception:
                count += 1
                logging.warning('Some connection (?) error occured when trying to send a telegram message. Retrying..')
                time.sleep(1)
                continue
        if count >= 5:
            logging.error('Could not send message to bot')


def noncomprende(update, context, what):
    if what == 'unknownCmd':
        txt = "Sorry, I didn't understand that command."
    elif what == 'wrongSymbolFormat':
        txt = "Sorry, the currency pair is not in the form COINA/COINB. Retry!"
    elif what == 'noNumber':
        txt = "Sorry, you did not enter a number! Retry!"
    elif what == 'noValueRequested':
        txt = "Sorry, I did not ask for anything at the moment, and unfortunately I have no KI (yet) ;-)"
    else:
        txt = what
    while True:
        try:
            context.bot.send_message(chat_id=update.message.chat_id, text=txt)
            break
        except Exception:
            continue


def get_cname(symbol, which=0):
    if which == 0:
        return re.search(r'^\w+(?=/)', symbol).group(0)
    else:
        return re.search(r'(?<=/)\w+$', symbol).group(0)


def received_info(update: Update, context: CallbackContext):
    if len(context.user_data['lastFct']) > 0:
        return context.user_data['lastFct'].pop()(update.message.text)
    else:
        context.bot.send_message(context.user_data['chatId'], 'Unknown previous error, returning to main menu')
        return MAINMENU


def received_float(update: Update, context: CallbackContext):
    if len(context.user_data['lastFct']) > 0:
        return context.user_data['lastFct'].pop()(float(update.message.text))
    else:
        context.bot.send_message(context.user_data['chatId'], 'Unknown previous error, returning to main menu')
        return MAINMENU


# define menu function
def start_cmd(update: Update, context: CallbackContext):
    # initiate user_data if it does not exist yet
    if update.message.from_user.id not in __config__['telegramUserId']:
        context.bot.send_message(update.message.from_user.id,
                                 'Sorry your Telegram ID (%d) is not recognized! Bye!' % update.message.from_user.id)
        logging.warning('Unknown user %s %s (username: %s, id: %s) tried to start the bot!' % (
            update.message.from_user.first_name, update.message.from_user.last_name, update.message.from_user.username,
            update.message.from_user.id))
        return
    else:
        logging.info('User %s %s (username: %s, id: %s) (re)started the bot' % (
            update.message.from_user.first_name, update.message.from_user.last_name, update.message.from_user.username,
            update.message.from_user.id))
    if context.user_data:
        washere = 'back '
        delete_messages(context.user_data)
        context.user_data.update({'lastFct': [],
                                  'whichCurrency': 0,
                                  'tempTradeSet': [None, None, None],
                                 'messages': {'status': {}, 'dialog': [], 'botInfo': [], 'settings': [], 'history': []}}
                                 )
    else:
        washere = ''
        context.user_data.update({
            'chatId': update.message.chat_id, 'trade': {},
            'settings': {'fiat': [], 'showProfitIn': None},
            'lastFct': [],
            'whichCurrency': 0,
            'tempTradeSet': [None, None, None],
            'messages': {'status': {}, 'dialog': [], 'botInfo': [], 'settings': [], 'history': []}})

    context.bot.send_message(context.user_data['chatId'],
                             "Welcome %s%s to the EazeBot! You are in the main menu." % (
                             washere, update.message.from_user.first_name),
                             reply_markup=markupMainMenu)
    return MAINMENU


def make_ts_inline_keyboard(exch, i_ts):
    button_list = [[
        InlineKeyboardButton("Edit Set", callback_data='2|%s|%s' % (exch, i_ts)),
        InlineKeyboardButton("Delete/SellAll", callback_data='3|%s|%s' % (exch, i_ts))]]
    return InlineKeyboardMarkup(button_list)


def buttons_edit_ts(ct, uid_ts, mode='full'):
    exch = ct.exchange.name.lower()
    buttons = [[InlineKeyboardButton("Add buy level", callback_data='2|%s|%s|buyAdd|chosen' % (exch, uid_ts)),
                InlineKeyboardButton("Add sell level", callback_data='2|%s|%s|sellAdd|chosen' % (exch, uid_ts))]]
    for i, trade in enumerate(ct.tradeSets[uid_ts]['InTrades']):
        if trade['oid'] == 'filled':
            buttons.append([InlineKeyboardButton("Readd BuyOrder from level #%d" % i,
                                                 callback_data='2|%s|%s|buyReAdd%d|chosen' % (exch, uid_ts, i))])
        else:
            buttons.append([InlineKeyboardButton("Delete Buy level #%d" % i,
                                                 callback_data='2|%s|%s|BLD%d|chosen' % (exch, uid_ts, i))])
    for i, trade in enumerate(ct.tradeSets[uid_ts]['OutTrades']):
        if trade['oid'] == 'filled':
            buttons.append([InlineKeyboardButton("Readd SellOrder from level #%d" % i,
                                                 callback_data='2|%s|%s|sellReAdd%d|chosen' % (exch, uid_ts, i))])
        else:
            buttons.append([InlineKeyboardButton("Delete Sell level #%d" % i,
                                                 callback_data='2|%s|%s|SLD%d|chosen' % (exch, uid_ts, i))])
    if mode == 'full':
        buttons.append([InlineKeyboardButton("Set/Change SL", callback_data='2|%s|%s|SLM' % (exch, uid_ts))])
        buttons.append([InlineKeyboardButton(
            "%s trade set" % ('Deactivate' if ct.tradeSets[uid_ts]['active'] else 'Activate'),
            callback_data='2|%s|%s|%s|chosen' % (exch, uid_ts, 'TSstop' if ct.tradeSets[uid_ts]['active'] else 'TSgo')),
                        InlineKeyboardButton("Delete trade set", callback_data='3|%s|%s' % (exch, uid_ts))])
    elif mode == 'init':
        buttons.append([InlineKeyboardButton("Add initial coins", callback_data='2|%s|%s|AIC|chosen' % (exch, uid_ts)),
                        InlineKeyboardButton("Add/change SL", callback_data='2|%s|%s|SLC|chosen' % (exch, uid_ts))])
        buttons.append(
            [InlineKeyboardButton("Activate trade set", callback_data='2|%s|%s|TSgo|chosen' % (exch, uid_ts)),
             InlineKeyboardButton("Delete trade set", callback_data='3|%s|%s|ok|no|chosen' % (exch, uid_ts))])
    if mode == 'full':
        buttons.append([InlineKeyboardButton("Back", callback_data='2|%s|%s|back|chosen' % (exch, uid_ts))])
    return buttons


def buttons_sl(ct, uid_ts):
    exch = ct.exchange.name.lower()
    buttons = [[InlineKeyboardButton("Set SL Break Even", callback_data='2|%s|%s|SLBE|chosen' % (exch, uid_ts))],
               [InlineKeyboardButton("Change/Delete SL", callback_data='2|%s|%s|SLC|chosen' % (exch, uid_ts))],
               [InlineKeyboardButton("Set daily-close SL", callback_data='2|%s|%s|DCSL|chosen' % (exch, uid_ts))],
               [InlineKeyboardButton("Set weekly-close SL", callback_data='2|%s|%s|WCSL|chosen' % (exch, uid_ts))]]
    if ct.num_buy_levels(uid_ts, 'notfilled') == 0:  # only show trailing SL option if all buy orders are filled
        buttons.append([InlineKeyboardButton("Set trailing SL", callback_data='2|%s|%s|TSL|chosen' % (exch, uid_ts))])
    buttons.append([InlineKeyboardButton("Back", callback_data='2|%s|%s|back|chosen' % (exch, uid_ts))])
    return buttons


def buttons_edit_tsh(ct):
    exch = ct.exchange.name.lower()
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Clear Trade History", callback_data='resetTSH|%s|XXX' % exch)]])


def delete_messages(user_data, typ: Union[str, List[str]] = 'all', only_forget=False, i_ts=None):
    if isinstance(typ, str):
        if typ == 'all':
            typ = list(user_data['messages'].keys())
        elif not isinstance(typ, list):
            typ = [typ]
    for t in typ:
        if not only_forget and t in user_data['messages']:
            for msg in user_data['messages'][t]:
                # status messages are as dict to remove not all trade sets when changing only one
                if t == 'status' and isinstance(user_data['messages'][t], dict):
                    if i_ts is None or i_ts == msg or msg == '1':
                        msg = user_data['messages'][t][msg]
                    else:
                        continue
                try:
                    msg.delete()
                except Exception:
                    pass
        if t == 'status':
            if i_ts is None:
                user_data['messages'][t] = {}
            else:
                try:
                    user_data['messages'][t].pop(i_ts)
                except Exception:
                    pass
        else:
            user_data['messages'][t] = []
    return 1


def print_trade_status(update: Update, context: CallbackContext, only_this_ts=None):
    delete_messages(context.user_data, 'status', i_ts=only_this_ts)
    for iex, ex in enumerate(context.user_data['trade']):
        ct = context.user_data['trade'][ex]
        if only_this_ts is not None and only_this_ts not in ct.tradeSets:
            continue
        count = 0
        for iTs in ct.tradeSets:
            try:  # catch errors in order to be able to see the statuses of other exchs, if one exchange has a problem
                ts = ct.tradeSets[iTs]
                if only_this_ts is not None and only_this_ts != iTs:
                    continue
                if ts['virgin']:
                    markup = InlineKeyboardMarkup(buttons_edit_ts(ct, iTs, mode='init'))
                else:
                    markup = make_ts_inline_keyboard(ex, iTs)
                count += 1
                context.user_data['messages']['status'][iTs] = context.bot.send_message(
                    context.user_data['chatId'],
                    ct.get_trade_set_info(iTs,
                                          context.user_data[
                                            'settings'][
                                            'showProfitIn']),
                    reply_markup=markup, parse_mode='markdown')
            except Exception as e:
                logging.error(str(e))
                pass
        if count == 0:
            context.user_data['messages']['status']['1'] = context.bot.send_message(
                context.user_data['chatId'],
                'No Trade sets found on %s' % ex)
    if len(context.user_data['trade']) == 0:
        context.user_data['messages']['status']['1'] = context.bot.send_message(
            context.user_data['chatId'],
            'No exchange found to check trade sets')
    return MAINMENU


def print_trade_history(update: Update, context: CallbackContext):
    delete_messages(context.user_data, 'history')  # %!!!
    for iex, ex in enumerate(context.user_data['trade']):
        ct = context.user_data['trade'][ex]
        context.user_data['messages']['history'].append(
            context.bot.send_message(context.user_data['chatId'], ct.get_trade_history(), parse_mode='markdown',
                                     reply_markup=buttons_edit_tsh(ct)))
    return MAINMENU


def check_balance(update: Update, context: CallbackContext, exchange=None):
    if exchange:
        ct = context.user_data['trade'][exchange]
        ct.update_balance()
        if ct.exchange.has['fetchTickers']:
            tickers = ct.safe_run(ct.exchange.fetchTickers)
            func = lambda sym: tickers[sym] if sym in tickers else ct.safe_run(
                lambda: ct.exchange.fetchTicker(sym))  # includes a hot fix for some ccxt problems
        else:
            func = lambda sym: ct.safe_run(lambda: ct.exchange.fetchTicker(sym))
        coins = list(ct.balance['total'].keys())
        string = '*Balance on %s (>%g BTC):*\n' % (exchange, __config__['minBalanceInBTC'])
        no_check_coins = []
        for c in coins:
            btc_pair = '%s/BTC' % c
            btc_pair2 = 'BTC/%s' % c
            if ct.balance['total'][c] > 0:
                if c == 'BTC' and ct.balance['total'][c] > __config__['minBalanceInBTC']:
                    string += '*%s:* %s _(free: %s)_\n' % (
                    c, ct.cost2Prec('ETH/BTC', ct.balance['total'][c]), ct.cost2Prec('ETH/BTC', ct.balance['free'][c]))
                elif btc_pair2 in ct.exchange.symbols and ct.exchange.markets[btc_pair2]['active']:
                    last_price = func(btc_pair2)['last']
                    if last_price is not None and ct.balance['total'][c] / last_price > __config__['minBalanceInBTC']:
                        string += '*%s:* %s _(free: %s)_\n' % (c, ct.cost2Prec(btc_pair2, ct.balance['total'][c]),
                                                               ct.cost2Prec(btc_pair2, ct.balance['free'][c]))
                elif btc_pair in ct.exchange.symbols and ct.exchange.markets[btc_pair]['active']:
                    last_price = func(btc_pair)['last']
                    if last_price is not None and last_price * ct.balance['total'][c] > __config__['minBalanceInBTC']:
                        string += '*%s:* %s _(free: %s)_\n' % (c, ct.amount2Prec(btc_pair, ct.balance['total'][c]),
                                                               ct.amount2Prec(btc_pair, ct.balance['free'][c]))
                elif not (btc_pair2 in ct.exchange.symbols and ct.exchange.markets[btc_pair2]['active']) and not (
                        btc_pair in ct.exchange.symbols and ct.exchange.markets[btc_pair]['active']):
                    # handles cases where BTCpair and BTCpair2 do not exist or are not active
                    if __config__['minBalanceInBTC'] == 0:
                        string += '*%s:* %0.4f _(free: %0.4f)_\n' % (c, ct.balance['total'][c], ct.balance['free'][c])
                    else:
                        no_check_coins.append(c)
        if len(no_check_coins) > 0:
            string += f"\nYou have some coins ({', '.join(no_check_coins)}) which do not have a (currently) active " + \
                "BTC trading pair, and could thus not be filtered.\n"
        try:
            context.bot.send_message(context.user_data['chatId'], string, parse_mode='markdown')
        except BadRequest as e:
            # handle too many coins making message to long by splitting it up
            if 'too long' in str(e):
                string_list = string.splitlines()
                counter = 0
                steps = 10
                while counter < len(string_list):
                    string = '\n'.join(string_list[counter:min([len(string_list), counter + steps])])
                    context.bot.send_message(context.user_data['chatId'], string, parse_mode='markdown')
                    counter += steps
            else:
                raise e
    else:
        delete_messages(context.user_data, 'dialog')
        context.user_data['lastFct'].append(lambda res: check_balance(update, context, res))
        # list all available exanches for choosing
        exchs = [ct.exchange.name for _, ct in context.user_data['trade'].items()]
        buttons = [[InlineKeyboardButton(exch, callback_data='chooseExch|%s|xxx' % (exch.lower()))] for exch in
                   sorted(exchs)] + [[InlineKeyboardButton('Cancel', callback_data='chooseExch|xxx|xxx|cancel')]]
        context.user_data['messages']['dialog'].append(
            context.bot.send_message(context.user_data['chatId'], 'For which exchange do you want to see your balance?',
                                     reply_markup=InlineKeyboardMarkup(buttons)))


def create_trade_set(update: Update, context: CallbackContext, exchange=None, symbol=None):
    # check if user is registered and has any authenticated exchange
    if 'trade' in context.user_data and len(context.user_data['trade']) > 0:
        # check if exchange was already chosen
        if exchange:
            ct = context.user_data['trade'][exchange]
            if symbol and symbol.upper() in ct.exchange.symbols:
                delete_messages(context.user_data, 'dialog')
                symbol = symbol.upper()
                ts, uid_ts = ct.init_trade_set(symbol)
                ct.update_balance()
                context.user_data['messages']['dialog'].append(
                    context.bot.send_message(
                        context.user_data['chatId'], 'Thank you, now let us begin setting the trade set'))
                print_trade_status(update, context, uid_ts)
                return MAINMENU
            else:
                if symbol:
                    text = 'Symbol %s was not found on exchange %s' % (symbol, exchange)
                else:
                    text = 'Please specify your trade set. Which currency pair do you want to trade? (e.g. ETH/BTC)'
                context.user_data['lastFct'].append(lambda res: create_trade_set(update, context, exchange, res))
                context.user_data['messages']['dialog'].append(
                    context.bot.send_message(
                        context.user_data['chatId'],
                        text,
                        reply_markup=InlineKeyboardMarkup([[
                                                           InlineKeyboardButton(
                                                               'List all pairs on %s' % exchange,
                                                               callback_data='showSymbols|%s|%s' % (
                                                                   exchange,
                                                                   'xxx')),
                                                           InlineKeyboardButton(
                                                               'Cancel',
                                                               callback_data='blabla|cancel')]])))
                return SYMBOL
        else:
            context.user_data['lastFct'].append(lambda res: create_trade_set(update, context, res))
            # list all available exanches for choosing
            exchs = [ct.exchange.name for _, ct in context.user_data['trade'].items()]
            buttons = [[InlineKeyboardButton(exch, callback_data='chooseExch|%s|xxx' % (exch.lower()))] for exch in
                       sorted(exchs)] + [[InlineKeyboardButton('Cancel', callback_data='chooseExch|xxx|xxx|cancel')]]
            context.user_data['messages']['dialog'].append(
                context.bot.send_message(
                    context.user_data['chatId'],
                    'For which of your authenticated exchanges do you want to add a trade set?',
                    reply_markup=InlineKeyboardMarkup(buttons)))
    else:
        context.user_data['messages']['dialog'].append(
            context.bot.send_message(
                context.user_data['chatId'],
                'No authenticated exchanges found for your account! Please click "Add exchanges"'))
        return MAINMENU


def ask_amount(user_data, exch, uid_ts, direction, bot_or_query):
    ct = user_data['trade'][exch]
    ts = ct.tradeSets[uid_ts]
    coin = ts['coinCurrency']
    currency = ts['baseCurrency']
    if direction == 'sell':
        # free balance is coins available in trade set minus coins that will be sold plus coins that will be bought
        bal = ts['coinsAvail'] - ct.sum_sell_amounts(uid_ts, 'notinitiated') + ct.sum_buy_amounts(uid_ts, 'notfilled',
                                                                                                  subtract_fee=True)
        if user_data['whichCurrency'] == 0:
            bal = ct.amount2Prec(ts['symbol'], bal)
            cname = coin
            action = 'sell'
            bal_text = 'available %s [fee subtracted] is' % coin
        else:
            bal = ct.cost2Prec(ts['symbol'], bal * user_data['tempTradeSet'][0])
            cname = currency
            action = 'receive'
            bal_text = 'return from available %s [fee subtracted] would be' % coin
    elif direction == 'buy':
        # free balance is free currency minus cost for coins that will be bought
        if ct.get_balance(currency) is not None:
            bal = ct.get_balance(currency) - ct.sum_buy_costs(uid_ts, 'notinitiated')
            unsure = ' '
        else:
            # estimate the amount of free coins... this is wrong if more than one trade uses this coin
            bal = ct.get_balance(currency, 'total') - ct.sum_buy_costs(uid_ts, 'notfilled')
            unsure = ' (estimated!) '
        if user_data['whichCurrency'] == 0:
            bal = ct.amount2Prec(ts['symbol'], bal / user_data['tempTradeSet'][0])
            cname = coin
            action = 'buy'
            bal_text = f'possible buy amount from your{unsure}remaining free balance is'
        else:
            bal = ct.cost2Prec(ts['symbol'], bal)
            cname = currency
            action = 'use'
            bal_text = '{unsure}remaining free balance is'
    else:
        raise ValueError('Unknown direction specification')

    text = "What amount of %s do you want to %s (%s ~%s)?" % (cname, action, bal_text, bal)
    if isinstance(bot_or_query, Bot):
        user_data['messages']['dialog'].append(
            bot_or_query.send_message(
                user_data['chatId'],
                text,
                reply_markup=InlineKeyboardMarkup([[
                                                      InlineKeyboardButton(
                                                          "Choose max amount",
                                                          callback_data='maxAmount|%s' % bal)],
                                                  [
                                                      InlineKeyboardButton(
                                                          "Toggle currency",
                                                          callback_data='toggleCurrency|%s|%s|%s' % (
                                                              exch,
                                                              uid_ts,
                                                              direction))],
                                                  [
                                                      InlineKeyboardButton(
                                                          "Cancel",
                                                          callback_data='askAmount|cancel')]])))
    else:
        bot_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Choose max amount", callback_data='maxAmount|%s' % bal)], [
                InlineKeyboardButton("Toggle currency",
                                     callback_data='toggleCurrency|%s|%s|%s' % (exch, uid_ts, direction))],
             [InlineKeyboardButton("Cancel", callback_data='askAmount|cancel')]]))
        bot_or_query.answer('Currency switched')


def add_init_balance(bot, user_data, exch, uid_ts, input_type=None, response=None, fct=None):
    ct = user_data['trade'][exch]
    if input_type is None:
        user_data['lastFct'].append(lambda res: add_init_balance(bot, user_data, exch, uid_ts, 'initCoins', res, fct))
        bal = ct.get_balance(ct.tradeSets[uid_ts]['coinCurrency'])
        user_data['messages']['dialog'].append(bot.send_message(
            user_data['chatId'],
            "You already have %s that you want to add to the trade set? How much is it (found %s free %s on %s)?" % (
                ct.tradeSets[uid_ts]['coinCurrency'],
                f'{bal:.5g}' if bal is not None else 'N/A',
                ct.tradeSets[uid_ts]['coinCurrency'], exch),
            reply_markup=InlineKeyboardMarkup([[
                                                   InlineKeyboardButton(
                                                       "Cancel",
                                                       callback_data='addInitBal|cancel')]])))
        return NUMBER
    elif input_type == 'initCoins':
        user_data['tempTradeSet'][0] = response
        user_data['lastFct'].append(lambda res: add_init_balance(bot, user_data, exch, uid_ts, 'initPrice', res, fct))
        user_data['messages']['dialog'].append(
            bot.send_message(
                user_data['chatId'],
                f"What was the average price {ct.tradeSets[uid_ts]['symbol']} you bought it for? "
                "Type 0 if received for free and a negative number if you do not know?",
                reply_markup=InlineKeyboardMarkup([[
                   InlineKeyboardButton(
                       "Cancel",
                       callback_data='addInitBal|cancel')]])))
        return NUMBER
    elif input_type == 'initPrice':
        delete_messages(user_data, 'dialog')
        if response >= 0:
            user_data['tempTradeSet'][1] = response
        add_pos(bot, user_data, exch, uid_ts, 'init', fct)
        return MAINMENU


def add_pos(bot, user_data, exch, uid_ts, direction, fct=None):
    ct = user_data['trade'][exch]
    try:
        if direction == 'buy':
            ct.add_buy_level(uid_ts, user_data['tempTradeSet'][0], user_data['tempTradeSet'][1],
                             user_data['tempTradeSet'][2])
        elif direction == 'sell':
            ct.add_sell_level(uid_ts, user_data['tempTradeSet'][0], user_data['tempTradeSet'][1])
        else:
            ct.add_init_coins(uid_ts, user_data['tempTradeSet'][0], user_data['tempTradeSet'][1])
    except Exception as e:
        broadcast_msg(bot, user_data['chatId'], str(e), 'error')
    user_data['tempTradeSet'] = [None, None, None]
    if fct:
        fct()


def ask_pos(bot, user_data, exch, uid_ts, direction, apply_fct=None, input_type=None, response=None):
    ct = user_data['trade'][exch]
    symbol = ct.tradeSets[uid_ts]['symbol']
    if input_type is None:
        user_data['tempTradeSet'] = [None, None, None]
        user_data['lastFct'].append(lambda r: ask_pos(bot, user_data, exch, uid_ts, direction, apply_fct, 'price', r))
        user_data['messages']['dialog'].append(
            bot.send_message(user_data['chatId'], "At which price do you want to %s %s" % (direction, symbol),
                             reply_markup=InlineKeyboardMarkup(
                                 [[InlineKeyboardButton("Cancel", callback_data='askPos|cancel')]])))
        return NUMBER
    elif input_type == 'price':
        if response == 0:
            user_data['lastFct'].append(
                lambda res: ask_pos(bot, user_data, exch, uid_ts, direction, apply_fct, 'price', res))
            user_data['messages']['dialog'].append(
                bot.send_message(user_data['chatId'], "Zero not allowed, please retry."))
            return NUMBER
        else:
            price = ct.safe_run(lambda: ct.exchange.fetchTicker(symbol))['last']
            if direction == 'buy':
                if response > 1.1 * price:
                    user_data['lastFct'].append(
                        lambda res: ask_pos(bot, user_data, exch, uid_ts, direction, apply_fct, 'price', res))
                    user_data['messages']['dialog'].append(
                        bot.send_message(
                            user_data['chatId'],
                            f"Cannot set buy price as it is much larger than current price of {price:.2f}. "
                            "Please use instant buy or specify smaller price."))
                    return NUMBER
            else:
                if response < 0.9 * price:
                    user_data['lastFct'].append(
                        lambda res: ask_pos(bot, user_data, exch, uid_ts, direction, apply_fct, 'price', res))
                    user_data['messages']['dialog'].append(
                        bot.send_message(
                            user_data['chatId'],
                            f"Cannot set sell price as it is much smaller than current price of {price:.2f}. "
                            "Please use instant sell or specify smaller price."))
                    return NUMBER
        response = float(user_data['trade'][exch].exchange.priceToPrecision(symbol, response))
        user_data['tempTradeSet'][0] = response
        user_data['lastFct'].append(lambda r: ask_pos(bot, user_data, exch, uid_ts, direction, apply_fct, 'amount', r))
        ask_amount(user_data, exch, uid_ts, direction, bot)
        return NUMBER
    elif input_type == 'amount':
        if user_data['whichCurrency'] == 1:
            response = response / user_data['tempTradeSet'][0]
        response = float(user_data['trade'][exch].exchange.amountToPrecision(symbol, response))
        user_data['tempTradeSet'][1] = response
        if direction == 'buy':
            user_data['lastFct'].append(
                lambda res: ask_pos(bot, user_data, exch, uid_ts, direction, apply_fct, 'candleAbove', res))
            user_data['messages']['dialog'].append(
                bot.send_message(
                    user_data['chatId'],
                    'Do you want to make this a timed buy (buy only if daily candle closes above X)',
                    reply_markup=InlineKeyboardMarkup([[
                                                           InlineKeyboardButton(
                                                               "Yes",
                                                               callback_data='Yes'),
                                                           InlineKeyboardButton(
                                                               "No",
                                                               callback_data='No')],
                                                       [
                                                           InlineKeyboardButton(
                                                               "Cancel",
                                                               callback_data='askPos|cancel')]])))
            return TIMING
        else:
            input_type = 'apply'
    if input_type == 'candleAbove':
        user_data['tempTradeSet'][2] = response
        input_type = 'apply'
    if input_type == 'apply':
        delete_messages(user_data, 'dialog')
        if apply_fct is None:
            return add_pos(bot, user_data, exch, uid_ts, direction)
        else:
            return apply_fct()


def add_exchanges(update, context: CallbackContext):
    idx = [i for i, x in enumerate(__config__['telegramUserId']) if x == context.user_data['chatId']][0] + 1
    if idx == 1:
        api_file = "APIs.json"
    else:
        api_file = "APIs%d.json" % idx
    with open(api_file, "r") as fin:
        apis = json.load(fin)

    if isinstance(apis, dict):
        # transform old style api json to new style
        keys = list(apis.keys())
        has_key = [re.search(r'(?<=^apiKey).*', val).group(0) for val in keys if
                   re.search(r'(?<=^apiKey).*', val, re.IGNORECASE) is not None]
        has_secret = [re.search(r'(?<=^apiSecret).*', val).group(0) for val in keys if
                      re.search(r'(?<=^apiSecret).*', val, re.IGNORECASE) is not None]

        apis_tmp = []
        for a in set(has_key).intersection(set(has_secret)):
            exch_params = {'exchange': a.lower(), 'key': apis['apiKey%s' % a], 'secret': apis['apiSecret%s' % a]}
            if 'apiUid%s' % a in apis:
                exch_params['uid'] = apis['apiUid%s' % a]
            if 'apiPassword%s' % a in apis:
                exch_params['password'] = apis['apiPassword%s' % a]
            apis_tmp.append(exch_params)
        apis = apis_tmp
        with open(api_file, "w") as fin:
            json.dump(apis, fin)

    available_exchanges = {val['exchange']: val for val in apis
                           if 'key' in val and 'secret' in val and 'exchange' in val}
    has_password = [key for key in available_exchanges if 'password' in available_exchanges[key]]
    has_uid = [key for key in available_exchanges if 'uid' in available_exchanges[key]]

    has_key = list(available_exchanges.keys())
    has_secret = list(available_exchanges.keys())

    if len(available_exchanges) > 0:
        logging.info('Found exchanges %s with keys %s, secrets %s, uids %s, password %s' % (
            available_exchanges, has_key, has_secret, has_uid, has_password))
        authenticated_exchanges = []
        for exch_name in available_exchanges:
            exch_params = available_exchanges[exch_name]
            exch_params.pop('exchange')
            # if no tradeHandler object has been created yet, create one, but also check for correct authentication
            messager_fct = lambda msg, lvl='info': broadcast_msg(context.bot, context.user_data['chatId'], msg, lvl)
            if exch_name not in context.user_data['trade']:
                context.user_data['trade'][exch_name] = tradeHandler(
                    exch_name, **exch_params,
                    messager_fct=messager_fct,
                    logger=rootLogger)
            else:
                context.user_data['trade'][exch_name].update_keys(**exch_params)
                context.user_data['trade'][exch_name].update_messager_fct(messager_fct)
            if not context.user_data['trade'][exch_name].authenticated and \
                    not context.user_data['trade'][exch_name].tradeSets:
                logging.warning('Authentication failed for %s' % exch_name)
                context.user_data['trade'].pop(exch_name)
            else:
                authenticated_exchanges.append(exch_name)
        context.bot.send_message(context.user_data['chatId'], 'Exchanges %s added/updated' % authenticated_exchanges)
    else:
        context.bot.send_message(context.user_data['chatId'], 'No exchange found to add')

    old_exchanges = set(context.user_data['trade'].keys()) - set(available_exchanges.keys())
    removed_exchanges = []
    for exch in old_exchanges:
        if len(context.user_data['trade'][exch].tradeSets) == 0:
            context.user_data['trade'].pop(exch)
            removed_exchanges.append(exch)
    if len(removed_exchanges) > 0:
        context.bot.send_message(
            context.user_data['chatId'], 'Old exchanges %s with no tradeSets removed' % removed_exchanges)


def get_remote_version():
    try:
        pypi_version = re.search(r'(?<=p class="release__version">\n)((.*\n){1})',
                                requests.get('https://pypi.org/project/eazebot/').text, re.M).group(0).strip()
    except:
        pypi_version = ''
    remote_txt = base64.b64decode(
        requests.get('https://api.github.com/repos/MarcelBeining/eazebot/contents/eazebot/__init__.py').json()[
            'content'])
    remote_version = re.search(r'(?<=__version__ = \\\')[0-9.]+', str(remote_txt)).group(0)
    remote_version_commit = \
    [val['commit']['url'] for val in requests.get('https://api.github.com/repos/MarcelBeining/EazeBot/tags').json() if
     val['name'] in ('EazeBot_%s' % remote_version, 'v%s' % remote_version)][0]
    return remote_version, requests.get(remote_version_commit).json()['commit']['message'], \
           pypi_version == remote_version


def bot_info(update: Update, context: CallbackContext):
    delete_messages(context.user_data, 'botInfo')
    string = '<b>******** EazeBot (v%s) ********</b>\n' % thisVersion
    string += r'<i>Free python bot for easy execution and surveillance of crypto tradings on multiple exchanges</i>\n'
    remote_version, versionMessage, onPyPi = get_remote_version()
    if remote_version != thisVersion and all(
            [int(a) >= int(b) for a, b in zip(remote_version.split('.'), thisVersion.split('.'))]):
        string += '\n<b>There is a new version of EazeBot available on git (v%s) %s with these changes:\n%s\n</b>\n' % (
            remote_version, 'and PyPi' if onPyPi else '(not yet on PyPi)', versionMessage)
    string += '\nReward my efforts on this bot by donating some cryptos!'
    context.user_data['messages']['botInfo'].append(context.bot.send_message(context.user_data['chatId'], string, parse_mode='html',
                                                             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                                                                 'Donate', callback_data='1|xxx|xxx')]])))
    return MAINMENU


def done_cmd(update: Update, context: CallbackContext):
    global interrupted
    interrupted = True
    chat_obj = context.bot.get_chat(context.user_data['chatId'])
    logging.info('User %s (id: %s) ends the bot!' % (chat_obj.first_name, chat_obj.id))


# job functions   
def check_for_updates_and_tax(context):
    updater = context.job.context
    remote_version, version_message, on_py_pi = get_remote_version()
    if remote_version != thisVersion and all(
            [int(a) >= int(b) for a, b in zip(remote_version.split('.'), thisVersion.split('.'))]):
        for user in updater.dispatcher.user_data:
            if 'chatId' in updater.dispatcher.user_data[user]:
                updater.dispatcher.user_data[user]['messages']['botInfo'].append(
                    context.bot.send_message(
                        updater.dispatcher.user_data[user]['chatId'],
                        f"There is a new version of EazeBot available on git (v{remote_version}) "
                        f"{'and PyPi' if on_py_pi else '(not yet on PyPi)'} with these changes:\n{version_message}"))

    for user in updater.dispatcher.user_data:
        if user in __config__['telegramUserId']:
            if updater.dispatcher.user_data[user]['settings']['taxWarn']:
                logging.info('Checking 1 year buy period limit')
                for iex, ex in enumerate(updater.dispatcher.user_data[user]['trade']):
                    updater.dispatcher.user_data[user]['trade'][ex].update(special_check=2)


def update_trade_sets(context):
    updater = context.job.context
    logging.info('Updating trade sets...')
    for user in updater.dispatcher.user_data:
        if user in __config__['telegramUserId'] and 'trade' in updater.dispatcher.user_data[user]:
            for iex, ex in enumerate(updater.dispatcher.user_data[user]['trade']):
                try:  # make sure other exchanges are checked too, even if one has a problem
                    updater.dispatcher.user_data[user]['trade'][ex].update()
                except Exception as e:
                    logging.error(str(e))
                    pass
    logging.info('Finished updating trade sets...')


def update_balance(context):
    updater = context.job.context
    logging.info('Updating balances...')
    for user in updater.dispatcher.user_data:
        if user in __config__['telegramUserId'] and 'trade' in updater.dispatcher.user_data[user]:
            for iex, ex in enumerate(updater.dispatcher.user_data[user]['trade']):
                updater.dispatcher.user_data[user]['trade'][ex].update_balance()
    logging.info('Finished updating balances...')


def check_candle(context, which=1):
    updater = context.job.context
    logging.info('Checking candles for all trade sets...')
    for user in updater.dispatcher.user_data:
        if user in __config__['telegramUserId']:
            for iex, ex in enumerate(updater.dispatcher.user_data[user]['trade']):
                # avoid to hit it during updating
                updater.dispatcher.user_data[user]['trade'][ex].update(special_check=which)
    logging.info('Finished checking candles for all trade sets...')


def timing_callback(update: Update, context: CallbackContext, query=None, response=None):
    if query is None:
        query = update.callback_query
    if query is None:
        return 0
    query.message.delete()
    if 'Yes' in query.data:
        query.answer('Please give the price above which the daily candle should close in order to initiate the buy!')
        return NUMBER
    else:
        query.answer()
        return context.user_data['lastFct'].pop()(None)


def show_settings(update: Update, context: CallbackContext, bot_or_query=None):
    # show gain/loss in fiat
    # give preferred fiat
    # stop bot with security question
    string = '*Settings:*\n\n_Fiat currencies(descending priority):_ %s\n\n_Show gain/loss in:_ %s\n\n_%sarn if filled buys approach 1 year_' % (
        ', '.join(context.user_data['settings']['fiat']),
        'Fiat (if available)' if context.user_data['settings']['showProfitIn'] is not None else 'Base currency',
        'W' if context.user_data['settings']['taxWarn'] else 'Do not w')
    setting_buttons = [
        [InlineKeyboardButton('Define your fiat', callback_data='settings|defFiat')],
        [InlineKeyboardButton("Toggle showing gain/loss in baseCurrency or fiat",
                              callback_data='settings|toggleProfit')],
        [InlineKeyboardButton("Toggle 1 year filled buy warning", callback_data='settings|toggleTaxWarn')],
        [InlineKeyboardButton("*Stop bot*", callback_data='settings|stopBot'),
         InlineKeyboardButton("Back", callback_data='settings|cancel')]]
    if bot_or_query is None or isinstance(bot_or_query, type(context.bot)):
        context.user_data['messages']['settings'].append(
            context.bot.send_message(context.user_data['chatId'], string, parse_mode='markdown',
                                     reply_markup=InlineKeyboardMarkup(setting_buttons)))
    else:
        try:
            bot_or_query.answer('Settings updated')
            bot_or_query.edit_message_text(string, parse_mode='markdown',
                                           reply_markup=InlineKeyboardMarkup(setting_buttons))
        except BadRequest:
            context.user_data['messages']['settings'].append(
                context.bot.send_message(context.user_data['chatId'], string, parse_mode='markdown',
                                 reply_markup=InlineKeyboardMarkup(setting_buttons)))


def update_ts_text(update: Update, context: CallbackContext, uid_ts, query=None):
    if query:
        try:
            query.message.delete()
        except Exception:
            pass
    print_trade_status(update, context, uid_ts)


def inline_button_callback(update: Update, context: CallbackContext, query=None, response=None):
    if query is None:
        query = update.callback_query
    if query is None:
        return 0
    command, *args = query.data.split('|')
    if 'chosen' in args:
        tmp = query.data.split('|')
        tmp.remove('chosen')
        query.data = '|'.join(tmp)

    if 'cancel' in args:
        context.user_data['tempTradeSet'] = [None, None, None]
        delete_messages(context.user_data, ['dialog', 'botInfo', 'settings'])
    else:
        if command == 'settings':
            subcommand = args.pop(0)
            if subcommand == 'stopBot':
                if len(args) == 0:
                    query.answer('')
                    context.bot.send_message(context.user_data['chatId'],
                                             'Are you sure you want to stop the bot? *Caution! '
                                             'You have to restart the Python script; '
                                             'until then the bot will not be responding to Telegram input!*',
                                             parse_mode='markdown', reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton('Yes', callback_data='settings|stopBot|Yes')],
                             [InlineKeyboardButton("No", callback_data='settings|cancel')]]))
                elif args[0] == 'Yes':
                    query.answer('stopping')
                    context.bot.send_message(context.user_data['chatId'], 'Bot is aborting now. Goodbye!')
                    done_cmd(update, context)
            else:
                if subcommand == 'defFiat':
                    if response is None:
                        context.user_data['lastFct'].append(
                            lambda res: inline_button_callback(update, context, query, res))
                        context.user_data['messages']['dialog'].append(
                            context.bot.send_message(context.user_data['chatId'],
                                                     'Please name your fiat currencies (e.g. USD). '
                                                     'You can also name multiple currencies separated with commata,'
                                                     '(e.g. type: USD,USDT,TUSD) such that in case the first currency '
                                                     'does not exist on an exchange, the second one is used, and so on.'
                                                     ))
                        return INFO
                    else:
                        context.user_data['settings']['fiat'] = response.upper().split(',')

                elif subcommand == 'toggleProfit':
                    if context.user_data['settings']['showProfitIn'] is None:
                        if len(context.user_data['settings']['fiat']) > 0:
                            context.user_data['settings']['showProfitIn'] = context.user_data['settings']['fiat']
                        else:
                            query.answer('Please first specify fiat currency(s) in the settings.')
                    else:
                        context.user_data['settings']['showProfitIn'] = None
                elif subcommand == 'toggleTaxWarn':
                    context.user_data['settings']['taxWarn'] = not context.user_data['settings']['taxWarn']
                show_settings(update, context, query)
        elif command == 'maxAmount':
            if len(context.user_data['lastFct']) > 0:
                query.answer('Max amount chosen')
                return context.user_data['lastFct'].pop()(float(args.pop(0)))
            else:
                query.answer('An error occured, please type in the number')
                return NUMBER
        else:
            exch = args.pop(0)
            uidTS = args.pop(0)
            if command == 'toggleCurrency':
                context.user_data['whichCurrency'] = (context.user_data['whichCurrency'] + 1) % 2
                return ask_amount(context.user_data, exch, uidTS, args[0], query)
            elif command == 'showSymbols':
                syms = [val for val in context.user_data['trade'][exch].exchange.symbols if '.d' not in val]
                buttons = list()
                rowbuttons = []
                string = ''
                for count, sym in enumerate(syms):
                    if count % 4 == 0:  # 4 buttons per row
                        if len(rowbuttons) > 0:
                            buttons.append(rowbuttons)
                        rowbuttons = [InlineKeyboardButton(sym, callback_data='chooseSymbol|%s|%s' % (exch, sym))]
                    else:
                        rowbuttons.append(InlineKeyboardButton(sym, callback_data='chooseSymbol|%s|%s' % (exch, sym)))
                    string += (sym + ', ')
                buttons.append(rowbuttons)
                buttons.append([InlineKeyboardButton('Cancel', callback_data='xxx|cancel')])
                try:
                    query.edit_message_text('Choose a pair...', reply_markup=InlineKeyboardMarkup(buttons))
                except BadRequest:
                    try:
                        query.edit_message_text(
                            'Too many pairs to make buttons, you have to type the pair. '
                            'Here is a list of all pairs:\n' + string[0:-2],
                            reply_markup=[])
                        return SYMBOL
                    except BadRequest:
                        query.edit_message_text('Too many pairs to make buttons, you have to type the pair manually.\n',
                                                reply_markup=[])
                        return SYMBOL

            elif command == 'chooseSymbol':
                query.message.delete()
                return context.user_data['lastFct'].pop()(
                    uidTS)  # it is no uidTS but the chosen symbol..i was too lazy to use new variable ;-)

            elif command == '1':  # donations
                if len(args) > 0:
                    if exch == 'xxx':
                        # get all exchange names that list the chosen coin and ask user from where to withdraw
                        exchs = [ct.exchange.name for _, ct in context.user_data['trade'].items() if
                                 args[0] in ct.exchange.currencies]
                        buttons = [[InlineKeyboardButton(exch,
                                                         callback_data='1|%s|%s|%s' % (exch.lower(), 'xxx', args[0]))]
                                   for exch in sorted(exchs)] + [
                                      [InlineKeyboardButton('Cancel', callback_data='1|xxx|xxx|cancel')]]
                        query.edit_message_text('From which exchange listing %s do you want to donate?' % args[0],
                                                reply_markup=InlineKeyboardMarkup(buttons))
                        query.answer('')
                    else:
                        if response is not None:
                            if args[0] == 'BTC':
                                address = '3AP2u8wMwdSFJWCXNhUbfbV1xirqshfqg6'
                            elif args[0] == 'ETH':
                                address = '0xE0451300D96090c1F274708Bc00d791017D7a5F3'
                            elif args[0] == 'NEO':
                                address = 'AaGRMPuwtGrudXR5s7F5n11cxK595hCWUg'
                            elif args[0] == 'XLM':
                                address = 'GBJEFEFUAUVTWL5UYK3NTWW7J5J3SMH4XB7SYDZRWWEON5S5YHPI2LAR'
                            else:
                                raise ValueError(f"Unknown currency {args[0]}")
                            try:
                                if response > 0:
                                    context.user_data['trade'][exch].exchange.withdraw(args[0], response, address)
                                    context.bot.send_message(context.user_data['chatId'],
                                                             'Donation suceeded, thank you very much!!!')
                                else:
                                    context.bot.send_message(context.user_data['chatId'],
                                                             'Amount <= 0 %s. Donation canceled =(' % args[0])
                            except Exception as e:
                                context.bot.send_message(
                                    context.user_data['chatId'],
                                    'There was an error during withdrawing, thus donation failed! =( '
                                    'Please consider the following reasons:\n- Insufficient funds?\n'
                                    '-2FA authentication required?\n-API key has no withdrawing permission?\n\n'
                                    'Server response was:\n<i>%s</i>' % str(
                                     e), parse_mode='html')
                        else:
                            ct = context.user_data['trade'][exch]
                            balance = ct.exchange.fetch_balance()
                            if ct.exchange.fees['funding']['percentage']:
                                query.answer('')
                                context.bot.send_message(
                                    context.user_data['chatId'],
                                    'Error. Exchange using relative withdrawal fees. '
                                    'Not implemented, please contact developer.')
                            if balance['free'][args[0]] > ct.exchange.fees['funding']['withdraw'][args[0]]:
                                query.answer('')
                                context.bot.send_message(
                                    context.user_data['chatId'],
                                    'Your free balance is %.8g %s and withdrawing fee on %s is %.8g %s. '
                                    'How much do you want to donate (excluding fees)' % (
                                        balance['free'][args[0]], args[0], exch,
                                        ct.exchange.fees['funding']['withdraw'][args[0]], args[0]))
                                context.user_data['lastFct'].append(
                                    lambda res: inline_button_callback(update, context, query, res))
                                return NUMBER
                            else:
                                query.answer('%s has insufficient free %s. Choose another exchange!' % (exch, args[0]))
                else:
                    buttons = [[InlineKeyboardButton("Donate BTC", callback_data='1|%s|%s|BTC' % ('xxx', 'xxx')),
                                InlineKeyboardButton("Donate ETH", callback_data='%s|%s|%d|ETH' % ('xxx', 'xxx', 1)),
                                InlineKeyboardButton("Donate NEO", callback_data='1|%s|%s|NEO' % ('xxx', 'xxx')),
                                InlineKeyboardButton("Donate XLM", callback_data='1|%s|%s|XLM' % ('xxx', 'xxx'))]]
                    query.edit_message_text(
                        'Thank you very much for your intention to donate some crypto! '
                        'Accepted coins are BTC, ETH and NEO.\nYou may either donate by sending coins manually to one '
                        'of the addresses below, or more easily by letting the bot send coins (amount will be asked in '
                        'a later step) from one of your exchanges by clicking the corresponding button below.\n\n'
                        '*BTC address:*\n17SfuTsJ3xpbzgArgRrjYSjvmzegMRcU3L\n*'
                        'ETH address:*\n0x2DdbDA69B27D36D0900970BCb8049546a9d621Ef\n'
                        '*NEO address:*\nAaGRMPuwtGrudXR5s7F5n11cxK595hCWUg',
                        reply_markup=InlineKeyboardMarkup(buttons), parse_mode='markdown')

            elif command == 'chooseExch':
                query.answer('%s chosen' % exch)
                query.message.delete()
                return context.user_data['lastFct'].pop()(exch)

            elif command == 'resetTSH':
                ct = context.user_data['trade'][exch]
                if 'yes' in args:
                    query.message.delete()
                    ct.reset_trade_history()
                elif 'no' in args:
                    query.edit_message_reply_markup(reply_markup=buttons_edit_tsh(ct))
                else:
                    query.answer('Are you sure? This cannot be undone!')
                    query.edit_message_reply_markup(
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton("Yes",
                             callback_data=f'resetTSH|{exch}|XXX|yes'),
                             InlineKeyboardButton("No",
                             callback_data=f'resetTSH|{exch}|XXX|no')]]))

            else:  # trade set commands
                if exch not in context.user_data['trade'] or uidTS not in context.user_data['trade'][exch].tradeSets:
                    query.edit_message_reply_markup()
                    query.edit_message_text('This trade set is not found anymore. Probably it was deleted')
                else:
                    ct = context.user_data['trade'][exch]
                    if command == '2':  # edit trade set
                        if 'chosen' in args:
                            try:
                                query.edit_message_reply_markup(reply_markup=make_ts_inline_keyboard(exch, uidTS))
                            except Exception:
                                pass

                        if 'back' in args:
                            query.answer('')

                        elif any(['BLD' in val for val in args]):
                            ct.delete_buy_level(uidTS, int([re.search(r'(?<=^BLD)\d+', val).group(0) for val in args if
                                                            isinstance(val, str) and 'BLD' in val][0]))
                            update_ts_text(update, context, uidTS, query)
                            query.answer('Deleted buy level')

                        elif any(['SLD' in val for val in args]):
                            ct.delete_sell_level(uidTS, int([re.search(r'(?<=^SLD)\d+', val).group(0) for val in args if
                                                             isinstance(val, str) and 'SLD' in val][0]))
                            update_ts_text(update, context, uidTS, query)
                            query.answer('Deleted sell level')

                        elif 'buyAdd' in args:
                            if response is None:
                                query.answer('Adding new buy level')
                                return ask_pos(context.bot, context.user_data, exch, uidTS, direction='buy',
                                               apply_fct=lambda: inline_button_callback(update, context, query,
                                                                                        'continue'))
                            else:
                                ct.add_buy_level(uidTS, context.user_data['tempTradeSet'][0],
                                                 context.user_data['tempTradeSet'][1],
                                                 context.user_data['tempTradeSet'][2])
                                context.user_data['tempTradeSet'] = [None, None, None]
                                update_ts_text(update, context, uidTS, query)

                        elif 'sellAdd' in args:
                            if response is None:
                                query.answer('Adding new sell level')
                                return ask_pos(context.bot, context.user_data, exch, uidTS, direction='sell',
                                               apply_fct=lambda: inline_button_callback(update, context, query,
                                                                                        'continue'))
                            else:
                                ct.add_sell_level(uidTS, context.user_data['tempTradeSet'][0],
                                                  context.user_data['tempTradeSet'][1])
                                context.user_data['tempTradeSet'] = [None, None, None]
                                update_ts_text(update, context, uidTS, query)

                        elif any(['buyReAdd' in val for val in args]):
                            logging.info(args)
                            level = int([re.search(r'(?<=^buyReAdd)\d+', val).group(0) for val in args if
                                         isinstance(val, str) and 'buyReAdd' in val][0])
                            trade = ct.tradeSets[uidTS]['InTrades'][level]
                            ct.add_buy_level(uidTS, trade['price'], trade['amount'], trade['candleAbove'])
                            update_ts_text(update, context, uidTS, query)

                        elif any(['sellReAdd' in val for val in args]):
                            level = int([re.search(r'(?<=^sellReAdd)\d+', val).group(0) for val in args if
                                         isinstance(val, str) and 'sellReAdd' in val][0])
                            trade = ct.tradeSets[uidTS]['OutTrades'][level]
                            ct.add_sell_level(uidTS, trade['price'], trade['amount'])
                            update_ts_text(update, context, uidTS, query)

                        elif 'AIC' in args:
                            query.answer('Adding initial coins')
                            return add_init_balance(context.bot, context.user_data, exch, uidTS, input_type=None,
                                                    response=None,
                                                    fct=lambda: print_trade_status(update, context, uidTS))

                        elif 'TSgo' in args:
                            ct.activate_trade_set(uidTS)
                            update_ts_text(update, context, uidTS, query)
                            query.answer('Trade set activated')

                        elif 'TSstop' in args:
                            ct.deactivate_trade_set(uidTS, 1)
                            update_ts_text(update, context, uidTS, query)
                            query.answer('Trade set deactivated!')

                        elif 'SLM' in args:
                            buttons = buttons_sl(ct, uidTS)
                            query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
                            query.answer('Choose an option')

                        elif 'SLBE' in args:
                            ans = ct.set_sl_break_even(uidTS)
                            if ans:
                                query.answer('SL set break even')
                            else:
                                query.answer('SL break even failed to set')
                            update_ts_text(update, context, uidTS, query)

                        elif 'DCSL' in args:
                            # set a daily-close SL
                            if response is None:
                                if 'yes' in args:
                                    query.message.delete()
                                    context.user_data['messages']['dialog'].append(
                                        context.bot.send_message(
                                            context.user_data['chatId'],
                                            'Type the daily candle closing price below which SL would be triggered'))
                                    return NUMBER
                                else:
                                    context.user_data['lastFct'].append(
                                        lambda res: inline_button_callback(update, context, query, res))

                                    context.user_data['messages']['dialog'].append(
                                        context.bot.send_message(
                                            context.user_data['chatId'],
                                            'Do you want an SL, which is triggered if the daily candle closes < X?',
                                            reply_markup=InlineKeyboardMarkup(
                                                [[InlineKeyboardButton(
                                                    "Yes",
                                                    callback_data='2|%s|%s|DCSL|yes' % (
                                                        exch, uidTS)),
                                                  InlineKeyboardButton(
                                                      "No",
                                                      callback_data='2|%s|%s|cancel' % (
                                                        exch, uidTS))], [
                                                     InlineKeyboardButton(
                                                         "Cancel",
                                                         callback_data='2|%s|%s|cancel' % (
                                                             exch,
                                                             uidTS))]])))
                            else:
                                ct.set_daily_close_sl(uidTS, response)
                                delete_messages(context.user_data, 'dialog')
                                update_ts_text(update, context, uidTS, query)

                        elif 'WCSL' in args:
                            # set a daily-close SL
                            if response is None:
                                if 'yes' in args:
                                    query.message.delete()
                                    context.user_data['messages']['dialog'].append(
                                        context.bot.send_message(
                                            context.user_data['chatId'],
                                            'Type the weekly candle closing price below which SL would be triggered'))
                                    return NUMBER
                                else:
                                    context.user_data['lastFct'].append(
                                        lambda res: inline_button_callback(update, context, query, res))
                                    context.user_data['messages']['dialog'].append(
                                        context.bot.send_message(
                                            context.user_data['chatId'],
                                            'Do you want an SL, which is triggered if the weekly candle closes < X?',
                                            reply_markup=InlineKeyboardMarkup(
                                                [[InlineKeyboardButton(
                                                    "Yes",
                                                    callback_data='2|%s|%s|WCSL|yes' % (exch, uidTS)),
                                                  InlineKeyboardButton(
                                                      "No",
                                                      callback_data='2|%s|%s|cancel' % (exch, uidTS))],
                                                    [
                                                     InlineKeyboardButton(
                                                         "Cancel",
                                                         callback_data='2|%s|%s|cancel' % (exch, uidTS))]])))
                            else:
                                ct.set_weekly_close_sl(uidTS, response)
                                delete_messages(context.user_data, 'dialog')
                                update_ts_text(update, context, uidTS, query)

                        elif 'TSL' in args:
                            # set a trailing stop-loss
                            if response is None:
                                query.answer()
                                if 'abs' in args or 'rel' in args:
                                    query.message.delete()
                                    context.user_data['messages']['dialog'].append(
                                        context.bot.send_message(
                                            context.user_data['chatId'],
                                            'Please enter the trailing SL offset%s' % (
                                                '' if 'abs' in args else ' in %')))
                                    context.user_data['lastFct'].append(
                                        lambda res: inline_button_callback(update, context, query, res))
                                    return NUMBER
                                else:
                                    context.user_data['messages']['dialog'].append(
                                        context.bot.send_message(
                                            context.user_data['chatId'],
                                            "What kind of trailing stop-loss offset do you want to set?",
                                            reply_markup=InlineKeyboardMarkup(
                                                [[InlineKeyboardButton(
                                                    "Absolute",
                                                    callback_data='2|%s|%s|TSL|abs' % (exch, uidTS)),
                                                  InlineKeyboardButton(
                                                      "Relative",
                                                      callback_data='2|%s|%s|TSL|rel' % (exch, uidTS))]])))
                            else:
                                response = float(response)
                                if 'rel' in args:
                                    response /= 100
                                ct.set_trailing_sl(uidTS, response, typ='abs' if 'abs' in args else 'rel')
                                delete_messages(context.user_data, 'dialog')
                                update_ts_text(update, context, uidTS, query)

                        elif 'SLC' in args:
                            if response is None:
                                query.answer('Please enter the new SL (0 = no SL)')
                                context.user_data['lastFct'].append(
                                    lambda res: inline_button_callback(update, context, query, res))
                                return NUMBER
                            else:
                                response = float(response)
                                if response == 0:
                                    response = None
                                ct.set_sl(uidTS, response)
                                update_ts_text(update, context, uidTS, query)
                        else:
                            buttons = buttons_edit_ts(ct, uidTS, 'full')
                            query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
                            query.answer('Choose an option')
                    elif command == '3':  # init trade set deletion
                        if 'ok' in args:
                            query.message.delete()
                            ct.delete_trade_set(uidTS, sellAll='yes' in args)
                            query.answer('Trade Set deleted')
                        elif 'yes' in args or 'no' in args:
                            query.answer('Ok, and are you really sure to delete this trade set?')
                            query.edit_message_reply_markup(
                                reply_markup=InlineKeyboardMarkup(
                                    [[
                                     InlineKeyboardButton("Yes", callback_data=f"3|{exch}|{uidTS}|ok|{'|'.join(args)}"),
                                     InlineKeyboardButton("Cancel", callback_data='3|%s|%s|cancel' % (exch, uidTS))
                                     ]]))
                        else:
                            query.answer('Do you want to sell your remaining coins?')
                            query.edit_message_reply_markup(
                                reply_markup=InlineKeyboardMarkup(
                                    [[InlineKeyboardButton("Yes", callback_data='3|%s|%s|yes' % (exch, uidTS)),
                                      InlineKeyboardButton("No", callback_data='3|%s|%s|no' % (exch, uidTS))
                                      ]]))
    return MAINMENU


def start_bot():
    print(
        f'\n\n******** Welcome to EazeBot (v{thisVersion}) ********\n'
        'Free python/telegram bot for easy execution & surveillance of crypto trading plans on multiple exchanges\n\n')

    # %% define the handlers to communicate with user
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_cmd)],
        states={
            MAINMENU: [MessageHandler(Filters.regex('^Status of Trade Sets$'), print_trade_status),
                       MessageHandler(Filters.regex('^New Trade Set$'), create_trade_set),
                       MessageHandler(Filters.regex('^Trade History$'), print_trade_history),
                       MessageHandler(Filters.regex('^Add/update exchanges'), add_exchanges),
                       MessageHandler(Filters.regex('^Bot Info$'), bot_info),
                       MessageHandler(Filters.regex('^Check Balance$'), check_balance),
                       MessageHandler(Filters.regex('^Settings$'), show_settings),
                       CallbackQueryHandler(inline_button_callback),
                       MessageHandler(Filters.text, lambda u, c: noncomprende(u, c, 'noValueRequested'))],
            SYMBOL: [MessageHandler(Filters.regex(r'\w+/\w+'), received_info),
                     MessageHandler(Filters.text, lambda u, c: noncomprende(u, c, 'wrongSymbolFormat')),
                     CallbackQueryHandler(inline_button_callback)],
            NUMBER: [MessageHandler(Filters.regex(r'^[\+,\-]?\d+\.?\d*$'), received_float),
                     MessageHandler(Filters.text, lambda u, c: noncomprende(u, c, 'noNumber')),
                     CallbackQueryHandler(inline_button_callback)],
            TIMING: [CallbackQueryHandler(timing_callback),
                     CallbackQueryHandler(inline_button_callback)],
            INFO: [MessageHandler(Filters.regex(r'\w+'), received_info)]
        },
        fallbacks=[CommandHandler('exit', done_cmd)], allow_reentry=True)  # , per_message = True)
    unknown_handler = MessageHandler(Filters.command, lambda u, c: noncomprende(u, c, 'unknownCmd'))

    # %% start telegram API, add handlers to dispatcher and start bot
    updater = Updater(token=__config__['telegramAPI'], use_context=True, request_kwargs={'read_timeout': 10,
                                                                                         'connect_timeout': 10})
    updater.dispatcher.add_handler(conv_handler)
    updater.dispatcher.add_handler(unknown_handler)
    updater.dispatcher.user_data = clean_data(load_data(), __config__['telegramUserId'])

    for user in __config__['telegramUserId']:
        if user in updater.dispatcher.user_data and len(updater.dispatcher.user_data[user]) > 0:
            context = CallbackContext(updater.dispatcher)
            context._user_data = updater.dispatcher.user_data[user]
            time.sleep(2)  # wait because of possibility of temporary exchange lockout
            add_exchanges(None, context)

    # start a job updating the trade sets each interval
    updater.job_queue.run_repeating(update_trade_sets, interval=60 * __config__['updateInterval'], first=5,
                                    context=updater)
    # start a job checking for updates once a day
    updater.job_queue.run_repeating(check_for_updates_and_tax, interval=60 * 60 * 24, first=0, context=updater)
    # start a job checking every day 10 sec after midnight (UTC time)
    updater.job_queue.run_daily(lambda context: check_candle(context, 1),
                                (dt.datetime(1900, 5, 5, 0, 0, 10) + (dt.datetime.now() - dt.datetime.utcnow())).time(),
                                context=updater, name='dailyCheck')
    # start a job saving the user data each 5 minutes
    updater.job_queue.run_repeating(save_data, interval=5 * 60, context=updater)
    # start a job making backup of the user data each x days
    updater.job_queue.run_repeating(backup_data, interval=60 * 60 * 24 * __config__['extraBackupInterval'],
                                    context=updater)
    if not __config__['debug']:
        for user in __config__['telegramUserId']:
            try:
                updater.bot.send_message(user, 'Bot was restarted.\n Please press /start to continue.',
                                         reply_markup=ReplyKeyboardMarkup([['/start']]), one_time_keyboard=True)
            except Exception:
                pass
        updater.start_polling()
        while True:
            time.sleep(1)
            if interrupted:
                updater.stop()
                for user in __config__['telegramUserId']:
                    chat_obj = updater.bot.get_chat(user)
                    try:
                        updater.bot.send_message(user,
                                                 f"Bot was stopped! "
                                                 f"Trades are not surveilled until bot is started again! "
                                                 f"See you soon {chat_obj.first_name}!")
                    except Exception:
                        pass
                break

        save_data(updater.dispatcher.user_data)  # last data save when finishing
    else:
        return updater
