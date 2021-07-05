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
import random
import re
import string
import traceback
import time
import datetime as dt
import json
import signal
from enum import Enum
from typing import Union, Dict
from dateutil.relativedelta import relativedelta
from dateparser import parse as dateparse
import requests
import base64
import os
from telegram import (ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Update)
from telegram.bot import Bot
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters,
                          ConversationHandler, CallbackQueryHandler, CallbackContext)
from telegram.error import BadRequest

from eazebot.tradeHandler import tradeHandler
from eazebot.handling import ValueType, ExchContainer, DateFilter, TempTradeSet, BaseTradeSet, RegularBuy, OrderType
from eazebot.auxiliary_methods import clean_data, load_data, save_data, backup_data, is_higher_version, ChangeLog, \
    MessageContainer

MAINMENU, SETTINGS, SYMBOL_OR_RAW, NUMBER, DAILY_CANDLE, INFO, DATE, TS_NAME = range(8)

logger = logging.getLogger(__name__)


class STATE(Enum):
    ACTIVE = 1
    INTERRUPTED = 2
    UPDATING = 3


class EazeBot:
    def __init__(self, config: Dict, user_dir: str = 'user_data'):
        self.user_dir = user_dir
        self.__config__ = config
        self.temp_ts = {}
        with open(os.path.join(os.path.dirname(__file__), '__init__.py')) as fh:
            self.thisVersion = re.search(r'(?<=__version__ = \')[0-9.]+', str(fh.read())).group(0)

        # %% init menues
        self.mainMenu = [['Status of Trade Sets', 'New Trade Set', 'Trade History'], ['Check Balance', 'Bot Info'],
                         ['Update exchanges', 'Settings']]
        self.markupMainMenu = ReplyKeyboardMarkup(self.mainMenu)  # , one_time_keyboard=True)

        self.updater = Updater(token=self.__config__['telegramAPI'], use_context=True,
                               request_kwargs={'read_timeout': 10, 'connect_timeout': 10})

        self.state = STATE.ACTIVE
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGABRT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    # define  helper functions
    def signal_handler(self, signal, frame):
        self.state = STATE.INTERRUPTED

    def update_cmd(self, update: Update, context: CallbackContext):
        self.state = STATE.UPDATING
        chat_obj = context.bot.get_chat(context.user_data['chatId'])
        logger.info('User %s (id: %s) ends the bot for updating!' % (chat_obj.first_name, chat_obj.id))

    def exit_cmd(self, update: Update, context: CallbackContext):
        self.state = STATE.INTERRUPTED
        chat_obj = context.bot.get_chat(context.user_data['chatId'])
        logger.info('User %s (id: %s) ends the bot!' % (chat_obj.first_name, chat_obj.id))

    @staticmethod
    def noncomprende(update, context, what):
        if what == 'unknownCmd':
            txt = "Sorry, I didn't understand that command."
        elif what == 'wrongSymbolFormat':
            txt = "Sorry, the currency pair is not in the form COINA/COINB. Retry!"
        elif what == 'noNumber':
            txt = "Sorry, you did not enter a number! Retry!"
        elif what == 'noDate':
            txt = "Sorry, the date you entered could not be parsed! Try a standard format such as YYYY-MM-DDTHH:MM!"
        elif what == 'noValueRequested':
            txt = "Sorry, I did not ask for anything at the moment, and unfortunately I am no AI (yet) ;-)"
        elif what == 'noShortName':
            txt = 'Sorry, the name must consist of letters, numbers and (!,#,?) only with a max length of 15.'
        else:
            txt = what
        while True:
            try:
                context.user_data['msgs'].send(which='error',
                                               text=txt)
                break
            except Exception:
                continue

    @staticmethod
    def get_cname(symbol, which=0):
        if which == 0:
            return re.search(r'^\w+(?=/)', symbol).group(0)
        else:
            return re.search(r'(?<=/)\w+$', symbol).group(0)

    @staticmethod
    def received_info(update: Update, context: CallbackContext):
        if len(context.user_data['lastFct']) > 0:
            return context.user_data['lastFct'].pop()(update.message.text)
        else:
            context.user_data['msgs'].send(which='error',
                                           text='Unknown previous error, returning to main menu')
            return MAINMENU

    @staticmethod
    def received_float(update: Update, context: CallbackContext):
        if len(context.user_data['lastFct']) > 0:
            return context.user_data['lastFct'].pop()(float(update.message.text))
        else:
            context.user_data['msgs'].send(which='error',
                                           text='Unknown previous error, returning to main menu')
            return MAINMENU

    @staticmethod
    def received_date(update: Update, context: CallbackContext):
        if len(context.user_data['lastFct']) > 0:
            return context.user_data['lastFct'].pop()(dateparse(update.message.text))
        else:
            context.user_data['msgs'].send(which='error',
                                           text='Unknown previous error, returning to main menu')
            return MAINMENU

    @staticmethod
    def received_short_name(update: Update, context: CallbackContext):
        if len(context.user_data['lastFct']) > 0:
            return context.user_data['lastFct'].pop()(update.message.text)
        else:
            context.user_data['msgs'].send(which='error',
                                           text='Unknown previous error, returning to main menu')
            return MAINMENU

    @staticmethod
    def daily_candle_callback(update: Update, context: CallbackContext, query=None, response=None):
        if query is None:
            query = update.callback_query
        if query is None:
            return 0
        query.message.delete()
        if 'Yes' in query.data:
            query.answer(
                'Please give the price above which the daily candle should close in order to initiate the buy!')
            return NUMBER
        else:
            query.answer()
            if len(context.user_data['lastFct']) > 0:
                return context.user_data['lastFct'].pop()(None)
            else:
                return MAINMENU

    # define menu function
    def start_cmd(self, update: Update, context: CallbackContext):
        # initiate user_data if it does not exist yet
        if update.message.from_user.id not in self.__config__['telegramUserId']:
            context.bot.send_message(
                update.message.from_user.id,
                'Sorry your Telegram ID (%d) is not recognized! Bye!' % update.message.from_user.id)
            logger.warning('Unknown user %s %s (username: %s, id: %s) tried to start the bot!' % (
                update.message.from_user.first_name, update.message.from_user.last_name,
                update.message.from_user.username,
                update.message.from_user.id))
            return
        else:
            logger.info('User %s %s (username: %s, id: %s) (re)started the bot' % (
                update.message.from_user.first_name, update.message.from_user.last_name,
                update.message.from_user.username,
                update.message.from_user.id))
        if 'msgs' not in context.user_data or context.user_data['msgs'] is None:
            context.user_data.update({'msgs': MessageContainer(bot=context.bot, chat_id=update.message.chat_id)})

        if 'chatId' in context.user_data:
            washere = 'back '
            context.user_data['msgs'].delete_msgs(which='all')
            context.user_data.update({'lastFct': []})
        else:
            washere = ''
            context.user_data.update({
                'chatId': update.message.chat_id,
                'trade': {},
                'settings': {'fiat': [], 'showProfitIn': None, 'taxWarn': True},
                'lastFct': []})
            self.add_exchanges(context.user_data)
        context.user_data['msgs'].send(which='start',
                                       text="Welcome %s%s to the EazeBot! You are in the main menu." % (
                                           washere, update.message.from_user.first_name),
                                       reply_markup=self.markupMainMenu)
        return MAINMENU

    @staticmethod
    def make_ts_inline_keyboard(exch, i_ts):
        button_list = [[
            InlineKeyboardButton("Edit Set", callback_data='2|%s|%s' % (exch, i_ts)),
            InlineKeyboardButton("Delete/SellAll", callback_data='3|%s|%s' % (exch, i_ts))]]
        return InlineKeyboardMarkup(button_list)

    @staticmethod
    def buttons_edit_ts(ct, uid_ts, mode='full'):
        exch = ct.exchange.name.lower()
        ts = ct.tradeSets[uid_ts]

        buttons = [[InlineKeyboardButton("Add buy level", callback_data='2|%s|%s|buyAdd|chosen' % (exch, uid_ts)),
                    InlineKeyboardButton("Add sell level", callback_data='2|%s|%s|sellAdd|chosen' % (exch, uid_ts))]]

        for i, trade in enumerate(ts.in_trades):
            if trade['oid'] == 'filled':
                if ts.show_filled_orders:
                    buttons.append([InlineKeyboardButton("Readd BuyOrder from level #%d" % i,
                                                         callback_data='2|%s|%s|buyReAdd%d|chosen' % (exch,
                                                                                                      uid_ts, i))])
            else:
                buttons.append([InlineKeyboardButton("Delete Buy level #%d" % i,
                                                     callback_data='2|%s|%s|BLD%d|chosen' % (exch, uid_ts, i))])
        for i, trade in enumerate(ts.out_trades):
            if trade['oid'] == 'filled':
                if ts.show_filled_orders:
                    buttons.append([InlineKeyboardButton("Readd SellOrder from level #%d" % i,
                                                         callback_data='2|%s|%s|sellReAdd%d|chosen' % (exch,
                                                                                                       uid_ts, i))])
            else:
                buttons.append([InlineKeyboardButton("Delete Sell level #%d" % i,
                                                     callback_data='2|%s|%s|SLD%d|chosen' % (exch, uid_ts, i))])

        if ts.regular_buy is None:
            buttons.append([InlineKeyboardButton(
                "Add regular buy", callback_data='2|%s|%s|buyRegAdd|chosen' % (exch, uid_ts))])
        else:
            buttons.append([InlineKeyboardButton(
                "Delete regular buy", callback_data='2|%s|%s|buyRegDel|chosen' % (exch, uid_ts))])
        buttons.append([InlineKeyboardButton("Edit trade set name", callback_data='2|%s|%s|ETSM' % (exch, uid_ts))])

        if mode == 'full':
            text = 'Hide' if ts.show_filled_orders else 'Show'
            buttons.append([InlineKeyboardButton("Set/Change SL", callback_data='2|%s|%s|SLM' % (exch, uid_ts))])
            buttons.append(
                [InlineKeyboardButton(f"{text} filled orders", callback_data='2|%s|%s|TFO' % (exch, uid_ts))])
            buttons.append([InlineKeyboardButton(
                "%s trade set" % ('Deactivate' if ts.is_active() else 'Activate'),
                callback_data='2|%s|%s|%s|chosen' % (
                    exch, uid_ts, 'TSstop' if ts.is_active() else 'TSgo')),
                InlineKeyboardButton("Delete trade set", callback_data='3|%s|%s' % (exch, uid_ts))])
        elif mode == 'init':
            buttons.append(
                [InlineKeyboardButton("Add initial coins", callback_data='2|%s|%s|AIC|chosen' % (exch, uid_ts)),
                 InlineKeyboardButton("Add/change SL", callback_data='2|%s|%s|SLC|chosen' % (exch, uid_ts))])
            buttons.append(
                [InlineKeyboardButton("Activate trade set", callback_data='2|%s|%s|TSgo|chosen' % (exch, uid_ts)),
                 InlineKeyboardButton("Delete trade set", callback_data='3|%s|%s|ok|no|chosen' % (exch, uid_ts))])
        if mode == 'full':
            buttons.append([InlineKeyboardButton("Back", callback_data='2|%s|%s|back|chosen' % (exch, uid_ts))])
        return buttons

    @staticmethod
    def buttons_sl(ct, uid_ts):
        exch = ct.exchange.name.lower()
        buttons = [[InlineKeyboardButton("Set SL Break Even", callback_data='2|%s|%s|SLBE|chosen' % (exch, uid_ts))],
                   [InlineKeyboardButton("Change/Delete SL", callback_data='2|%s|%s|SLC|chosen' % (exch, uid_ts))],
                   [InlineKeyboardButton("Set daily-close SL", callback_data='2|%s|%s|DCSL|chosen' % (exch, uid_ts))],
                   [InlineKeyboardButton("Set weekly-close SL", callback_data='2|%s|%s|WCSL|chosen' % (exch, uid_ts))]]
        if ct.tradeSets[uid_ts].num_buy_levels('notfilled') == 0:
            # only show trailing SL option if all buy orders are filled
            buttons.append(
                [InlineKeyboardButton("Set trailing SL", callback_data='2|%s|%s|TSL|chosen' % (exch, uid_ts))])
        buttons.append([InlineKeyboardButton("Back", callback_data='2|%s|%s|back|chosen' % (exch, uid_ts))])
        return buttons

    @staticmethod
    def buttons_edit_tsh(ct):
        exch = ct.exchange.name.lower()
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("Clear Trade History", callback_data='resetTSH|%s|XXX' % exch)]])

    def print_trade_status(self, update: Union[Update, None], context: CallbackContext, only_this_ts=None):
        context.user_data['msgs'].delete_msgs(which='status', note=only_this_ts)
        for iex, ex in enumerate(context.user_data['trade']):
            ct = context.user_data['trade'][ex]
            if only_this_ts is not None and only_this_ts not in ct.tradeSets:
                continue
            count = 0
            for iTs in ct.tradeSets:
                ts = ct.tradeSets[iTs]
                try:  # catch errors in order to see the statuses of other exchs, if one exchange has a problem
                    if only_this_ts is not None and only_this_ts != iTs:
                        continue
                    if ts.is_virgin():
                        markup = InlineKeyboardMarkup(self.buttons_edit_ts(ct, iTs, mode='init'))
                    else:
                        markup = self.make_ts_inline_keyboard(ex, iTs)
                    count += 1
                    context.user_data['msgs'].send(which='status',
                                                   text=ct.get_trade_set_info(iTs,
                                                                              context.user_data[
                                                                                  'settings'][
                                                                                  'showProfitIn']),
                                                   note=iTs,
                                                   reply_markup=markup,
                                                   parse_mode='markdown')
                except Exception as e:
                    logger.error(traceback.print_exc())
                    try:
                        context.user_data['msgs'].send(which='status',
                                                       text='There was an error with trade set %s on exchange %s' % (
                                                           ts.name, ex),
                                                       note=f'error_{ts.name}_ex')
                    except Exception:
                        pass

            if count == 0:
                context.user_data['msgs'].send(which='status',
                                               text='No Trade sets found on %s' % ex,
                                               note=f'no_ts_{ex}')
        if len(context.user_data['trade']) == 0:
            context.user_data['msgs'].send(which='status',
                                           text='No exchange found to check trade sets',
                                           note='1')
        return MAINMENU

    def print_trade_history(self, update: Update, context: CallbackContext):
        context.user_data['msgs'].delete_msgs(which='history')
        for iex, ex in enumerate(context.user_data['trade']):
            ct = context.user_data['trade'][ex]
            context.user_data['msgs'].send(which='history',
                                           text=ct.get_trade_history(),
                                           reply_markup=self.buttons_edit_tsh(ct),
                                           parse_mode='markdown',
                                           note=f'history_{ex}')
        return MAINMENU

    def check_balance(self, update: Update, context: CallbackContext, exchange=None):
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
            string = '*Balance on %s (>%g BTC):*\n' % (exchange, self.__config__['minBalanceInBTC'])
            no_check_coins = []
            for c in coins:
                btc_pair = '%s/BTC' % c
                btc_pair2 = 'BTC/%s' % c
                if ct.balance['total'][c] > 0:
                    if c == 'BTC' and ct.balance['total'][c] > self.__config__['minBalanceInBTC']:
                        string += '*%s:* %s _(free: %s)_\n' % (
                            c, ct.nf.cost2Prec('ETH/BTC', ct.balance['total'][c]),
                            ct.nf.cost2Prec('ETH/BTC', ct.balance['free'][c]))
                    elif btc_pair2 in ct.exchange.symbols and ct.exchange.markets[btc_pair2]['active']:
                        last_price = func(btc_pair2)['last']
                        if last_price is not None and ct.balance['total'][c] / last_price > self.__config__[
                            'minBalanceInBTC']:
                            string += '*%s:* %s _(free: %s)_\n' % (c, ct.nf.cost2Prec(btc_pair2,
                                                                                      ct.balance['total'][c]),
                                                                   ct.nf.cost2Prec(btc_pair2, ct.balance['free'][c]))
                    elif btc_pair in ct.exchange.symbols and ct.exchange.markets[btc_pair]['active']:
                        last_price = func(btc_pair)['last']
                        if last_price is not None and last_price * ct.balance['total'][c] > self.__config__[
                            'minBalanceInBTC']:
                            string += '*%s:* %s _(free: %s)_\n' % (c, ct.nf.amount2Prec(btc_pair,
                                                                                        ct.balance['total'][c]),
                                                                   ct.nf.amount2Prec(btc_pair, ct.balance['free'][c]))
                    elif not (btc_pair2 in ct.exchange.symbols and ct.exchange.markets[btc_pair2]['active']) and not (
                            btc_pair in ct.exchange.symbols and ct.exchange.markets[btc_pair]['active']):
                        # handles cases where BTCpair and BTCpair2 do not exist or are not active
                        if self.__config__['minBalanceInBTC'] == 0:
                            string += '*%s:* %0.4f _(free: %0.4f)_\n' % (
                                c, ct.balance['total'][c], ct.balance['free'][c])
                        else:
                            no_check_coins.append(c)
            if len(no_check_coins) > 0:
                string += f"\nYou have some coins ({', '.join(no_check_coins)}) which do not have a (currently) " \
                          f"active BTC trading pair, and could thus not be filtered.\n"
            try:
                context.user_data['msgs'].send(which='balance',
                                               text=string,
                                               parse_mode='markdown')
            except BadRequest as e:
                # handle too many coins making message to long by splitting it up
                if 'too long' in str(e):
                    string_list = string.splitlines()
                    counter = 0
                    steps = 10
                    while counter < len(string_list):
                        string = '\n'.join(string_list[counter:min([len(string_list), counter + steps])])
                        context.user_data['msgs'].send(which='balance',
                                                       text=string,
                                                       parse_mode='markdown')
                        counter += steps
                else:
                    raise e
        else:
            context.user_data['msgs'].delete_msgs(which='dialog')
            context.user_data['lastFct'].append(lambda res: self.check_balance(update, context, res))
            # list all available exanches for choosing
            exchs = [ct.exchange.name for _, ct in context.user_data['trade'].items()]
            buttons = [[InlineKeyboardButton(exch, callback_data='chooseExch|%s|xxx' % (exch.lower()))] for exch in
                       sorted(exchs)] + [[InlineKeyboardButton('Cancel', callback_data='chooseExch|xxx|xxx|cancel')]]

            context.user_data['msgs'].send(which='dialog',
                                           text='For which exchange do you want to see your balance?',
                                           reply_markup=InlineKeyboardMarkup(buttons),
                                           parse_mode='markdown')

    def create_trade_set(self, update: Update, context: CallbackContext, exchange=None, symbol_or_raw=None):
        # check if user is registered and has any authenticated exchange
        if 'trade' in context.user_data and len(context.user_data['trade']) > 0:
            # check if exchange was already chosen
            if exchange:
                ct = context.user_data['trade'][exchange]
                if symbol_or_raw is not None:
                    if re.match(r'^\w+/\w+\n.*QUANTITY', symbol_or_raw, re.DOTALL):
                        current = 'quantity'
                        match = re.search(r'^QUANTITY (?P<quan>([0-9]*[.])?[0-9]+)$', symbol_or_raw, re.MULTILINE)
                        if match is not None:
                            quantity = float(match.group('quan'))
                            current = 'symbol / trading pair'
                            match = re.match(r'^(?P<symbol>\w+/\w+)\n', symbol_or_raw)
                            if match is not None:
                                symbol = match.group('symbol').upper()
                                current = 'entry'
                                match = re.search(r'^ENTRY (?P<entries>[-\s0-9\.]+)$', symbol_or_raw, re.MULTILINE)
                                if match is not None:
                                    entries = [float(val) for val in match.group('entries').split('-')]
                                    current = 'targets'
                                    match = re.search(r'^TARGETS (?P<targets>[-\s0-9\.]+)$', symbol_or_raw,
                                                      re.MULTILINE)
                                    if match is not None:
                                        targets = [float(val) for val in match.group('targets').split('-')]
                                        current = 'stop loss'
                                        match = re.search(r'^STOP LOSS (?P<time>DAILY)?\s?(BELOW )?(?P<SL>[0-9\.]+)$',
                                                          symbol_or_raw,
                                                          re.MULTILINE)
                                        if match is not None:
                                            stop_loss = float(match.group('SL'))
                                            sl_time_frame = match.group('time')
                                        else:
                                            stop_loss = None
                                            sl_time_frame = None

                                        coin_currency = re.search(".*(?=/)", symbol).group(0)
                                        amount_per_buy = []
                                        for price in entries:
                                            amount = quantity / (len(entries) * price)
                                            fee = ct.exchange.calculate_fee(symbol, 'limit', 'buy', amount, price,
                                                                            'maker')
                                            if fee['currency'] == coin_currency and not ct.is_paid_by_exchange_token(
                                                    fee['cost'], coin_currency):
                                                amount -= fee['cost']
                                            amount_per_buy.append(float(ct.exchange.amountToPrecision(
                                                symbol, amount)))

                                        amount_per_sell = [float(
                                            ct.exchange.amountToPrecision(symbol,
                                                                          sum(amount_per_buy) / len(targets)))
                                                          ] * len(targets)
                                        # fixing the precision rounding difference
                                        amount_per_sell[-1] = float(ct.exchange.amountToPrecision(
                                            symbol, amount_per_sell[-1] -
                                            (sum(amount_per_sell) - sum(amount_per_buy))))

                                        assert sum(amount_per_sell) <= sum(amount_per_buy), \
                                            'Amount to sell exceeds amount to buy'

                                        try:
                                            ts = ct.new_trade_set(symbol,
                                                                  buy_levels=entries,
                                                                  buy_amounts=amount_per_buy,
                                                                  sell_levels=targets,
                                                                  sell_amounts=amount_per_sell,
                                                                  sl=stop_loss,
                                                                  sl_close=sl_time_frame,
                                                                  force=True)
                                            self.print_trade_status(None, context, ts.get_uid())
                                            current = None
                                        except Exception as e:
                                            current = e
                        if current is not None:
                            if isinstance(current, Exception):
                                text = f"ERROR: {current}"
                                msg_type = 'error'
                            else:
                                text = f"ERROR: Had problem finding {current} in the raw text! Aborting..."
                                msg_type = 'error'
                        else:
                            text = f"Successfully created and activated new trade set!"
                            msg_type = 'dialog'

                    elif symbol_or_raw.upper() in ct.exchange.symbols:
                        context.user_data['msgs'].delete_msgs(which='dialog')
                        symbol_or_raw = symbol_or_raw.upper()
                        ts = ct.init_trade_set(symbol_or_raw)
                        uid_ts = ts.get_uid()
                        ct.update_balance()
                        text = 'Thank you, now let us begin setting the trade set'
                        msg_type = 'dialog'
                        self.print_trade_status(None, context, uid_ts)
                    else:
                        text = 'ERROR: Symbol %s was not found on exchange %s! Aborting...' % (symbol_or_raw, exchange)
                        msg_type = 'error'

                    context.user_data['msgs'].send(which=msg_type,
                                                   text=text,
                                                   parse_mode='markdown',
                                                   )
                    return MAINMENU
                else:
                    text = 'Please specify your trade set. Which currency pair do you want to trade ' \
                           '(e.g. ETH/BTC)? Alternatively paste in a text with buy/sell commands formatted as\n' \
                           '"_XXX/YYY_\nQUANTITY _XXX_\nENTRY _XXX_ - _YYY_ - _ZZZ_ - ...\n' \
                           'TARGETS _XXX_ - _YYY_ - _ZZZ_ - ...\nSTOP LOSS BELOW _XXX_"'
                    context.user_data['lastFct'].append(
                        lambda res: self.create_trade_set(update, context, exchange, res))
                    context.user_data['msgs'].send(which='dialog',
                                                   text=text,
                                                   parse_mode='markdown',
                                                   reply_markup=InlineKeyboardMarkup([[
                                                       InlineKeyboardButton(
                                                           'List all pairs on %s' % exchange,
                                                           callback_data='showSymbols|%s|%s' % (
                                                               exchange,
                                                               'xxx')),
                                                       InlineKeyboardButton(
                                                           'Cancel',
                                                           callback_data='blabla|cancel')]])
                                                   )
                    return SYMBOL_OR_RAW
            else:
                context.user_data['lastFct'].append(lambda res: self.create_trade_set(update, context, res))
                # list all available exanches for choosing
                exchs = [ct.exchange.name for _, ct in context.user_data['trade'].items()]
                buttons = [[InlineKeyboardButton(exch, callback_data='chooseExch|%s|xxx' % (exch.lower()))] for exch in
                           sorted(exchs)] + [
                              [InlineKeyboardButton('Cancel', callback_data='chooseExch|xxx|xxx|cancel')]]
                context.user_data['msgs'].send(which='dialog',
                                               text='For which of your authenticated exchanges do you want to add a '
                                                    'trade set?',
                                               parse_mode='markdown',
                                               reply_markup=InlineKeyboardMarkup(buttons))
        else:
            context.user_data['msgs'].send(which='dialog',
                                           text='No authenticated exchanges found for your account! '
                                                'Please click "Add exchanges"',
                                           )
            return MAINMENU

    def ask_amount(self, user_data, exch, uid_ts, utid, direction, bot_or_query):
        ct = user_data['trade'][exch]
        ts = ct.tradeSets[uid_ts]
        temp_ts = self.temp_ts[utid]
        coin = ts.coinCurrency
        currency = ts.baseCurrency
        bal = None
        if direction == 'sell':
            # free balance is coins available in trade set minus coins that will be sold plus coins that will be bought
            bal = ts.coins_avail() - ts.sum_sell_amounts('notinitiated') + \
                  ts.sum_buy_amounts('notfilled', subtract_fee=True)
            if temp_ts.coin_or_base == 0:
                bal = ct.nf.amount2Prec(ts.symbol, bal)
                cname = coin
                action = 'sell'
                bal_text = f' (available {coin} [fee subtracted] is ~{bal})'
            else:
                bal = ct.nf.cost2Prec(ts.symbol, bal * temp_ts.price)
                cname = currency
                action = 'receive'
                bal_text = f' (return from available {coin} [fee subtracted] would be ~ {bal})'
        elif direction == 'buy':
            # free balance is free currency minus cost for coins that will be bought
            if ct.get_balance(currency) is not None:
                bal = ct.get_balance(currency) - ts.sum_buy_costs('notinitiated')
                unsure = ' '
            else:
                # estimate the amount of free coins... this is wrong if more than one trade uses this coin
                bal = ct.get_balance(currency, 'total') - ts.sum_buy_costs('notfilled')
                unsure = ' (estimated!) '
            if temp_ts.coin_or_base == 0:
                bal = ct.nf.amount2Prec(ts.symbol, bal / temp_ts.price)
                cname = coin
                action = 'buy'
                bal_text = f' ( possible buy amount from your{unsure}remaining free balance is ~{bal})'
            else:
                bal = ct.nf.cost2Prec(ts.symbol, bal)
                cname = currency
                action = 'use'
                bal_text = f' ( {unsure}remaining free balance is ~{bal})'
        elif direction == 'reg_buy':
            bal_text = ''
            if temp_ts.coin_or_base == 0:
                cname = coin
                action = 'buy'
            else:
                cname = currency
                action = 'use'
        else:
            raise ValueError('Unknown direction specification')

        text = f"What amount of {cname} do you want to {action}{bal_text}?"

        buttons = [
            [
                InlineKeyboardButton(
                    "Toggle currency",
                    callback_data='toggleCurrency|%s|%s|%s|%s' % (
                        exch,
                        uid_ts,
                        utid,
                        direction))],
            [
                InlineKeyboardButton(
                    "Cancel",
                    callback_data='askAmount|cancel')]
        ]

        if direction != 'reg_buy':
            buttons.insert(0, [InlineKeyboardButton("Choose max amount", callback_data='maxAmount|%s' % bal)])
        user_data['msgs'].send(which='dialog',
                               text=text,
                               reply_markup=InlineKeyboardMarkup(buttons),
                               note='amount',
                               overwrite_last=True
                               )
        if not isinstance(bot_or_query, Bot):
            bot_or_query.answer('Currency switched')

    def add_init_balance(self, bot, user_data, exch, uid_ts, input_type=None, response=None, fct=None, utid=None):
        ct = user_data['trade'][exch]
        if input_type is None:
            random.seed()
            utid = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
            self.temp_ts[utid] = TempTradeSet()
            user_data['lastFct'].append(lambda res: self.add_init_balance(bot, user_data, exch, uid_ts, 'initCoins',
                                                                          res, fct, utid))
            bal = ct.get_balance(ct.tradeSets[uid_ts].coinCurrency)
            user_data['msgs'].send(which='dialog',
                                   text="You already have %s that you want to add to the trade set? "
                                        "How much is it (found %s free %s on %s)?" % (
                                            ct.tradeSets[uid_ts].coinCurrency,
                                            f'{bal:.5g}' if bal is not None else 'N/A',
                                            ct.tradeSets[uid_ts].coinCurrency, exch),
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                                       "Cancel",
                                       callback_data='addInitBal|cancel')]]),
                                   )
            return NUMBER
        elif input_type == 'initCoins':
            self.temp_ts[utid].amount = response
            user_data['lastFct'].append(lambda res: self.add_init_balance(bot, user_data, exch, uid_ts, 'initPrice',
                                                                          res, fct, utid))
            user_data['msgs'].send(which='dialog',
                                   text=f"What was the average price {ct.tradeSets[uid_ts].symbol} you bought it for? "
                                        "Type 0 if received for free and a negative number if you do not know?",
                                   reply_markup=InlineKeyboardMarkup([[
                                       InlineKeyboardButton(
                                           "Cancel",
                                           callback_data='addInitBal|cancel')]]),
                                   )
            return NUMBER
        elif input_type == 'initPrice':
            user_data['msgs'].delete_msgs(which='dialog')
            if response >= 0:
                self.temp_ts[utid].price = response
            self.add_pos(user_data, ct.tradeSets[uid_ts], 'init', utid, fct)
            return MAINMENU

    def add_pos(self, user_data, ts: BaseTradeSet, direction, utid, fct=None):
        temp_ts = self.temp_ts.pop(utid)
        try:
            if direction == 'reg_buy':
                currency = ts.coinCurrency if temp_ts.coin_or_base == 0 else ts.baseCurrency
                ts.regular_buy = RegularBuy(amount=temp_ts.amount, currency=currency,
                                            order_type=temp_ts.add_params['order_type'],
                                            interval=temp_ts.add_params['interval'],
                                            start=temp_ts.add_params['start'])
            elif direction == 'buy':
                ts.add_buy_level(temp_ts.price, temp_ts.amount, **temp_ts.add_params)
            elif direction == 'sell':
                ts.add_sell_level(temp_ts.price, temp_ts.amount)
            elif direction == 'init':
                ts.add_init_coins(temp_ts.price, temp_ts.amount)
        except Exception as e:
            logger.error(str(e), extra={'chatId': user_data['chatId']})

        if fct is not None:
            fct()

    def ask_pos(self, context, exch, uid_ts, direction, input_type=None, response=None, utid=None):
        bot = context.bot
        user_data = context.user_data
        ct = user_data['trade'][exch]
        symbol = ct.tradeSets[uid_ts].symbol
        if input_type is None:
            random.seed()
            utid = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
            self.temp_ts[utid] = TempTradeSet()
            if direction == 'reg_buy':
                self.temp_ts[utid].reg_buy = True
                user_data['lastFct'].append(lambda r: self.ask_pos(context, exch, uid_ts, direction, 'amount', r, utid))
                self.ask_amount(user_data, exch, uid_ts, utid, direction, bot)
            else:
                user_data['lastFct'].append(lambda r: self.ask_pos(context, exch, uid_ts, direction, 'price', r, utid))

                user_data['msgs'].send(which='dialog',
                                       text="At which price do you want to %s %s" % (direction, symbol),
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton("Cancel", callback_data='askPos|cancel')]]),
                                       )
            return NUMBER
        elif input_type == 'price':
            if response == 0:
                user_data['lastFct'].append(
                    lambda res: self.ask_pos(context, exch, uid_ts, direction, 'price', res, utid))
                user_data['msgs'].send(which='dialog',
                                       text="Zero not allowed, please retry.",
                                       )
                return NUMBER
            else:
                price = ct.safe_run(lambda: ct.exchange.fetchTicker(symbol))['last']
                if 'buy' in direction:
                    if response > 1.1 * price:
                        user_data['lastFct'].append(
                            lambda res: self.ask_pos(context, exch, uid_ts, direction, 'price', res, utid))
                        user_data['msgs'].send(which='dialog',
                                               text=f"Cannot set buy price as it is much larger than current price of "
                                                    f"{price:.2f}. Please use instant buy or specify smaller price."
                                               )
                        return NUMBER
                else:
                    if response < 0.9 * price:
                        user_data['lastFct'].append(
                            lambda res: self.ask_pos(context, exch, uid_ts, direction, 'price', res, utid))
                        user_data['msgs'].send(which='dialog',
                                               text=f"Cannot set sell price as it is much smaller than current price of"
                                                    f" {price:.2f}. Please use instant sell or specify smaller price."
                                               )
                        return NUMBER
            response = float(user_data['trade'][exch].exchange.priceToPrecision(symbol, response))
            self.temp_ts[utid].price = response
            user_data['lastFct'].append(lambda r: self.ask_pos(context, exch, uid_ts, direction, 'amount', r, utid))
            self.ask_amount(user_data, exch, uid_ts, utid, direction, bot)
            return NUMBER
        elif input_type == 'amount':
            if self.temp_ts[utid].reg_buy is False:
                if self.temp_ts[utid].coin_or_base == 1:
                    response = response / self.temp_ts[utid].price
                response = float(user_data['trade'][exch].exchange.amountToPrecision(symbol, response))
            self.temp_ts[utid].amount = response
            if direction == 'buy':
                user_data['lastFct'].append(
                    lambda res: self.ask_pos(context, exch, uid_ts, direction, 'candleAbove', res, utid))
                user_data['msgs'].send(which='dialog',
                                       text='Do you want to make this a timed buy (buy only if daily candle closes '
                                            'above X)',
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
                                                   callback_data='askPos|cancel')]])
                                       )
                return DAILY_CANDLE
            elif self.temp_ts[utid].reg_buy:
                user_data['lastFct'].append(lambda r: self.ask_pos(context, exch, uid_ts, direction, 'order_type', r,
                                                                   utid))
                user_data['msgs'].send(which='dialog',
                                       text="Do you want to buy using market or limit order?\n"
                                            "Note that market order fees are usually higher, while it "
                                            r"cannot be guaranteed that the limit order (set at 0.02 % "
                                            "below the market price at the date of buy) will be filled!",
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton("Market", callback_data='askPos|market'),
                                             InlineKeyboardButton("Limit", callback_data='askPos|limit')],
                                            [InlineKeyboardButton("Cancel", callback_data='askPos|cancel')]])
                                       )
                return MAINMENU
            else:
                input_type = 'apply'
        elif input_type == 'order_type':
            if response == 'market':
                self.temp_ts[utid].add_params['order_type'] = OrderType.MARKET
            else:
                self.temp_ts[utid].add_params['order_type'] = OrderType.LIMIT

            user_data['lastFct'].append(lambda r: self.ask_pos(context, exch, uid_ts, direction, 'interval', r,
                                                               utid))
            user_data['msgs'].send(which='dialog',
                                   text="At which interval do you want to buy regularly?",
                                   reply_markup=InlineKeyboardMarkup(
                                       [[InlineKeyboardButton("Daily", callback_data='askPos|daily'),
                                         InlineKeyboardButton("Weekly", callback_data='askPos|weekly')],
                                        [InlineKeyboardButton("Monthly", callback_data='askPos|monthly'),
                                         InlineKeyboardButton("Cancel", callback_data='askPos|cancel')]])
                                   )
            return MAINMENU
        elif input_type == 'interval':
            if response == 'daily':
                self.temp_ts[utid].add_params['interval'] = relativedelta(days=1)
            elif response == 'weekly':
                self.temp_ts[utid].add_params['interval'] = relativedelta(weeks=1)
            elif response == 'monthly':
                self.temp_ts[utid].add_params['interval'] = relativedelta(months=1)
            else:
                logger.error(f"Unknown interval {response}, returning to main menu.")
                return MAINMENU

            user_data['lastFct'].append(lambda r: self.ask_pos(context, exch, uid_ts, direction, 'start', r,
                                                               utid))
            user_data['msgs'].send(which='dialog',
                                   text="When do you want to start with the buys? Type in a valid date "
                                        "(e.g. YYYY-MM-DD HH:mm) or press the 'Now' button",
                                   reply_markup=InlineKeyboardMarkup(
                                       [[InlineKeyboardButton("Now", callback_data='askPos|now'),
                                         InlineKeyboardButton("Cancel", callback_data='askPos|cancel')]])
                                   )
            return DATE
        elif input_type == 'start':
            self.temp_ts[utid].add_params['start'] = response
            input_type = 'apply'

        if input_type == 'candleAbove':
            self.temp_ts[utid].add_params['candle_above'] = response
            input_type = 'apply'
        if input_type == 'apply':
            context.user_data['msgs'].delete_msgs(which='dialog')
            self.add_pos(user_data, ct.tradeSets[uid_ts], direction, utid)
        self.update_ts_text(context, uid_ts)
        return MAINMENU

    def edit_trade_set_name(self, context, exch, uid_ts, ts_name=None):
        bot = context.bot
        user_data = context.user_data
        ct = user_data['trade'][exch]

        if ts_name is None:
            user_data['lastFct'].append(lambda r: self.edit_trade_set_name(context, exch, uid_ts, ts_name=r))
            user_data['msgs'].send(which='dialog',
                                   text="Please give the new name for the trade set.",
                                   )
            return TS_NAME
        else:
            ct.tradeSets[uid_ts].name = ts_name
            context.user_data['msgs'].delete_msgs(which='dialog')
            self.update_ts_text(context, uid_ts)
            return MAINMENU

    def add_exchanges_from_context(self, update, context: CallbackContext):
        self.add_exchanges(context.user_data)

    def add_exchanges(self, user_data: Dict):
        if 'msgs' in user_data:
            user_data['msgs'].send(which='dialog',
                                           text='Adding/Updating exchanges, please wait...',
                                           parse_mode='markdown')
        idx = [i for i, x in enumerate(self.__config__['telegramUserId']) if x == user_data['chatId']][0] + 1
        if idx == 1:
            api_file = os.path.join(self.user_dir, "APIs.json")
        else:
            api_file = os.path.join(self.user_dir, "APIs%d.json" % idx)
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
            exch_container = ExchContainer(user_data['chatId'])
            logger.info('Found exchanges with keys %s, secrets %s, uids %s, password %s' % (
                has_key, has_secret, has_uid, has_password))
            authenticated_exchanges = []
            for exch_name in available_exchanges:
                exch_params = available_exchanges[exch_name]
                exch_params.pop('exchange')
                exch_container.add(exch_name, **exch_params)
                # if no tradeHandler object has been created yet, create one, but also check for correct authentication
                if exch_name not in user_data['trade']:
                    user_data['trade'][exch_name] = tradeHandler(exch_name,
                                                                 user=user_data['chatId'])
                else:
                    # necessary for backward compatibility
                    user_data['trade'][exch_name].set_user(user_data['chatId'])

                if not user_data['trade'][exch_name].authenticated and \
                        not user_data['trade'][exch_name].tradeSets:
                    logger.warning('Authentication failed for %s' % exch_name)
                    user_data['trade'].pop(exch_name)
                else:
                    authenticated_exchanges.append(exch_name)
            if 'msgs' in user_data:
                user_data['msgs'].send(which='dialog',
                                       text='Exchanges %s added/updated' % authenticated_exchanges,
                                       parse_mode='markdown')
        else:
            if 'msgs' in user_data:
                user_data['msgs'].send(which='dialog',
                                       text='No exchange found to add',
                                       parse_mode='markdown')

        old_exchanges = set(user_data['trade'].keys()) - set(available_exchanges.keys())
        removed_exchanges = []
        for exch in old_exchanges:
            if len(user_data['trade'][exch].tradeSets) == 0:
                user_data['trade'].pop(exch)
                removed_exchanges.append(exch)
            else:
                user_data['trade'][exch].set_user(user_data['chatId'])
        if len(removed_exchanges) > 0:
            if 'msgs' in user_data:
                user_data['msgs'].send(which='dialog',
                                       text='Old exchanges %s with no tradeSets removed' % removed_exchanges,
                                       parse_mode='markdown')

    def get_remote_version(self):
        try:
            pypi_version = re.search(r'(?<=p class="release__version">\n)((.*\n){1})',
                                     requests.get('https://pypi.org/project/eazebot/').text, re.M).group(0).strip()
        except Exception:
            pypi_version = ''
        remote_txt = base64.b64decode(
            requests.get('https://api.github.com/repos/MarcelBeining/eazebot/contents/eazebot/__init__.py').json()[
                'content'])
        latest_version = re.search(r'(?<=__version__ = \')[0-9.]+', str(remote_txt)).group(0)
        # remote_version_commit = \
        #     [val['commit']['url'] for val in
        #      requests.get('https://api.github.com/repos/MarcelBeining/EazeBot/tags').json() if
        #      val['name'] in ('EazeBot_%s' % latest_version, 'v%s' % latest_version)][0]
        # chg_text = requests.get(remote_version_commit).json()['commit']['message']
        chg_log = requests.get(
            f'https://raw.githubusercontent.com/MarcelBeining/EazeBot/v{latest_version}/change_log.json').json()
        with open('tmp.json', 'w') as fh:
            json.dump(chg_log, fh)
        chg_text = '-' + '\n-'.join(ChangeLog('tmp', version_prefix='v').get_changes(prev_version=self.thisVersion,
                                                                                     this_version=latest_version,
                                                                                     text_only=True))
        try:
            os.remove('tmp.json')
        except:
            pass

        return latest_version, chg_text, pypi_version == latest_version

    def bot_info(self, update: Update, context: CallbackContext):
        context.user_data['msgs'].delete_msgs(which='botInfo')
        string = '<b>******** EazeBot (v%s) ********</b>\n' % self.thisVersion
        string += r'<i>Free python bot for easy execution and surveillance of crypto tradings on multiple ' \
                  'exchanges</i>\n'
        buttons = [InlineKeyboardButton('Donate', callback_data='1|xxx|xxx')]
        remote_version, version_message, on_py_pi = self.get_remote_version()
        if is_higher_version(next_version=remote_version, this_version=self.thisVersion):
            string += '\n<b>There is a new version of EazeBot available on git/docker (v%s) %s with these ' \
                      'changes:</b>\n' \
                      '%s\n\n' % (remote_version, 'and PyPi' if on_py_pi else '(not yet on PyPi)', version_message)
            buttons.append(InlineKeyboardButton("*Update bot*", callback_data='settings|updateBot'))
        string += '\n<b>Reward my efforts on this bot by donating some cryptos!</b>'
        context.user_data['msgs'].send(which='botInfo',
                                       text=string,
                                       parse_mode='html',
                                       reply_markup=InlineKeyboardMarkup([buttons]))
        return MAINMENU

    # job functions
    def check_for_updates_and_tax(self, context):
        self.updater = context.job.context
        remote_version, version_message, on_py_pi = self.get_remote_version()
        if is_higher_version(next_version=remote_version, this_version=self.thisVersion):
            for user in self.updater.dispatcher.user_data:
                if 'msgs' in self.updater.dispatcher.user_data[user]:
                    self.updater.dispatcher.user_data[user]['msgs'].send(
                        which='botInfo',
                        text=f"There is a new version of EazeBot available on git "
                             f"(v{remote_version}) "
                             f"{'and PyPi' if on_py_pi else '(not yet on PyPi)'} with these"
                             f" changes:\n{version_message}",
                        parse_mode='html',
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("*Update bot*",
                                                 callback_data='settings|updateBot')]]))

        for user in self.updater.dispatcher.user_data:
            if user in self.__config__['telegramUserId']:
                if self.updater.dispatcher.user_data[user]['settings']['taxWarn']:
                    logger.info('Checking 1 year buy period limit')
                    for iex, ex in enumerate(self.updater.dispatcher.user_data[user]['trade']):
                        self.updater.dispatcher.user_data[user]['trade'][ex].update(special_check=2)

    def update_trade_sets(self, context):
        self.updater = context.job.context
        logger.info('Updating trade sets...')
        for user in self.updater.dispatcher.user_data:
            if user in self.__config__['telegramUserId'] and 'trade' in self.updater.dispatcher.user_data[user]:
                for iex, ex in enumerate(self.updater.dispatcher.user_data[user]['trade']):
                    try:  # make sure other exchanges are checked too, even if one has a problem
                        self.updater.dispatcher.user_data[user]['trade'][ex].update()
                    except Exception as e:
                        logger.error(traceback.print_exc())
        logger.info('Finished updating trade sets...')

    def update_balance(self, context):
        self.updater = context.job.context
        logger.info('Updating balances...')
        for user in self.updater.dispatcher.user_data:
            if user in self.__config__['telegramUserId'] and 'trade' in self.updater.dispatcher.user_data[user]:
                for iex, ex in enumerate(self.updater.dispatcher.user_data[user]['trade']):
                    self.updater.dispatcher.user_data[user]['trade'][ex].update_balance()
        logger.info('Finished updating balances...')

    def check_candle(self, context, which=1):
        self.updater = context.job.context
        logger.info('Checking candles for all trade sets...')
        for user in self.updater.dispatcher.user_data:
            if user in self.__config__['telegramUserId']:
                for iex, ex in enumerate(self.updater.dispatcher.user_data[user]['trade']):
                    # avoid to hit it during updating
                    self.updater.dispatcher.user_data[user]['trade'][ex].update(special_check=which)
        logger.info('Finished checking candles for all trade sets...')

    @staticmethod
    def show_settings(update: Update, context: CallbackContext, bot_or_query=None):
        # show gain/loss in fiat
        # give preferred fiat
        # stop bot with security question
        string = f"*Settings:*\n\n_Fiat currencies(descending priority):_ " \
                 f"{', '.join(context.user_data['settings']['fiat'])}\n\n_Show gain/loss in:_ " \
                 f"{'Fiat (if avail.)' if context.user_data['settings']['showProfitIn'] is not None else 'Base currency'}" \
                 f"\n\n_{'W' if context.user_data['settings']['taxWarn'] else 'Do not w'}arn if filled buys approach 1 year_"
        setting_buttons = [
            [InlineKeyboardButton('Define your fiat', callback_data='settings|defFiat')],
            [InlineKeyboardButton("Toggle showing gain/loss in baseCurrency or fiat",
                                  callback_data='settings|toggleProfit')],
            [InlineKeyboardButton("Toggle 1 year filled buy warning", callback_data='settings|toggleTaxWarn')],
            [InlineKeyboardButton("*Stop bot*", callback_data='settings|stopBot'),
             InlineKeyboardButton("Back", callback_data='settings|cancel')]]
        if bot_or_query is None or isinstance(bot_or_query, type(context.bot)):
            context.user_data['msgs'].send(which='settings',
                                           text=string,
                                           parse_mode='markdown',
                                           reply_markup=InlineKeyboardMarkup(setting_buttons))
        else:
            try:
                bot_or_query.answer('Settings updated')
                bot_or_query.edit_message_text(string, parse_mode='markdown',
                                               reply_markup=InlineKeyboardMarkup(setting_buttons))
            except BadRequest:
                context.user_data['msgs'].send(which='settings',
                                               text=string,
                                               parse_mode='markdown',
                                               reply_markup=InlineKeyboardMarkup(setting_buttons))

    def update_ts_text(self, context: CallbackContext, uid_ts, query=None):
        if query:
            try:
                query.message.delete()
            except Exception:
                pass
        self.print_trade_status(None, context, uid_ts)

    @staticmethod
    def ask_stop_bot_message( update: Update, context: CallbackContext):
        context.user_data['msgs'].send(which='start',
                                       text='Are you sure you want to stop the bot? *Caution! '
                                            'You have to restart the Python script; '
                                            'until then the bot will not be responding to Telegram '
                                            'input!*',
                                       parse_mode='markdown',
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton('Yes',
                                                                  callback_data='settings|stopBot|Yes')],
                                            [InlineKeyboardButton("No",
                                                                  callback_data='settings|cancel')]]))
        return MAINMENU

    def inline_button_callback(self, update: Update, context: CallbackContext, query=None, response=None):
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
            self.temp_ts = {}
            context.user_data['msgs'].delete_msgs(which=['dialog', 'botInfo', 'settings'])
        else:
            if command == 'settings':
                subcommand = args.pop(0)
                if subcommand == 'stopBot':
                    if len(args) == 0:
                        query.answer('')
                        self.ask_stop_bot_message(update, context)
                    elif args[0] == 'Yes':
                        query.answer('stopping')
                        context.user_data['msgs'].send(which='start',
                                                       text='Bot is aborting now. Goodbye!')
                        self.exit_cmd(update, context)
                elif subcommand == 'updateBot':
                    query.answer('updating')
                    context.user_data['msgs'].send(which='start',
                                                   text='Bot is stopped for updating now. '
                                                        'Should be back in a few minutes. Goodbye!')
                    self.update_cmd(update, context)
                else:
                    if subcommand == 'defFiat':
                        if response is None:
                            context.user_data['lastFct'].append(
                                lambda res: self.inline_button_callback(update, context, query, res))
                            context.user_data['msgs'].send(which='dialog',
                                                           text='Please name your fiat currencies (e.g. USD). '
                                                                'You can also name multiple currencies separated with '
                                                                'commata, (e.g. type: USD,USDT,TUSD) that in case the '
                                                                'first currency does not exist on an exchange, the next'
                                                                ' one is used.'
                                                           )
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
                    self.show_settings(update, context, query)
            elif command == 'maxAmount':
                if len(context.user_data['lastFct']) > 0:
                    query.answer('Max amount chosen')
                    return context.user_data['lastFct'].pop()(float(args.pop(0)))
                else:
                    query.answer('An error occured, please type in the number')
                    return NUMBER
            elif command == 'askPos':
                subcommand = args.pop(0)
                if subcommand in ['limit', 'market']:
                    query.answer(f'{subcommand} order type chosen')
                elif subcommand in ['daily', 'weekly', 'monthly']:
                    query.answer(f'{subcommand} interval chosen')
                elif subcommand == 'now':
                    query.answer(f'Regular buy starting now chosen')
                    subcommand = dt.datetime.now()
                else:
                    query.answer('Unknown command')
                    return MAINMENU
                return context.user_data['lastFct'].pop()(subcommand)
            else:
                exch = args.pop(0)
                uid_ts = args.pop(0)
                if command == 'toggleCurrency':
                    utid = args.pop(0)
                    self.temp_ts[utid].coin_or_base = (self.temp_ts[utid].coin_or_base + 1) % 2
                    return self.ask_amount(context.user_data, exch, uid_ts, utid, args[0], query)
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
                            rowbuttons.append(
                                InlineKeyboardButton(sym, callback_data='chooseSymbol|%s|%s' % (exch, sym)))
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
                            return SYMBOL_OR_RAW
                        except BadRequest:
                            query.edit_message_text(
                                'Too many pairs to make buttons, you have to type the pair manually.\n',
                                reply_markup=[])
                            return SYMBOL_OR_RAW

                elif command == 'chooseSymbol':
                    query.message.delete()
                    return context.user_data['lastFct'].pop()(
                        uid_ts)  # it is no uidTS but the chosen symbol..i was too lazy to use new variable ;-)

                elif command == '1':  # donations
                    if len(args) > 0:
                        if exch == 'xxx':
                            # get all exchange names that list the chosen coin and ask user from where to withdraw
                            exchs = [ct.exchange.name for _, ct in context.user_data['trade'].items() if
                                     args[0] in ct.exchange.currencies]
                            buttons = [[InlineKeyboardButton(exch,
                                                             callback_data='1|%s|xxx|%s' % (exch.lower(), args[0]))]
                                       for exch in sorted(exchs)] + [
                                          [InlineKeyboardButton('Cancel', callback_data='1|xxx|xxx|cancel')]]
                            query.edit_message_text('From which exchange listing %s do you want to donate?' % args[0],
                                                    reply_markup=InlineKeyboardMarkup(buttons))
                            query.answer('')
                        else:
                            if response is not None:
                                if args[0] == 'BTC':
                                    address = 'bc1q5wfzxdk3xhujs6589gzdeu6fgqpvqrel5jzzt2'
                                elif args[0] == 'ETH':
                                    address = '0xE0451300D96090c1F274708Bc00d791017D7a5F3'
                                elif args[0] == 'NEO':
                                    address = 'AaGRMPuwtGrudXR5s7F5n11cxK595hCWUg'
                                elif args[0] == 'XLM':
                                    address = 'GCEAF5KYYUJSYPEDAWTZUBP4TE2LUSAPAFNHFSY54RA4HNLBVYOSFM6K'
                                elif args[0] == 'USDT (ERC20)':
                                    address = '0x55b1be96e951bfce21973a233970245f728782f1'
                                else:
                                    raise ValueError(f"Unknown currency {args[0]}")
                                try:
                                    if response > 0:
                                        context.user_data['trade'][exch].exchange.withdraw(args[0], response, address)
                                        context.user_data['msgs'].send(which='donation',
                                                                       text='Donation suceeded, thank you very much!!!')
                                    else:
                                        context.user_data['msgs'].send(which='donation',
                                                                       text='Amount <= 0 %s. Donation canceled =(' %
                                                                            args[0])
                                except Exception as e:
                                    context.user_data['msgs'].send(which='donation',
                                                                   text='There was an error during withdrawing, thus '
                                                                        'donation failed! =( Please consider the '
                                                                        'following reasons:\n- Insufficient funds?\n'
                                                                        '-2FA authentication required?\n'
                                                                        '-API key has no withdrawing permission?\n\n'
                                                                        'Server response was:\n<i>%s</i>' % str(e),
                                                                   parse_mode='html')
                            else:
                                ct = context.user_data['trade'][exch]
                                balance = ct.exchange.fetch_balance()
                                if ct.exchange.fees['funding']['percentage']:
                                    query.answer('')
                                    context.user_data['msgs'].send(which='donation',
                                                                   text='Error. Exchange using relative withdrawal fees'
                                                                        '. Not implemented, please contact developer.')
                                if balance['free'][args[0]] > ct.exchange.fees['funding']['withdraw'][args[0]]:
                                    query.answer('')
                                    context.user_data['msgs'].send(which='donation',
                                                                   text='Your free balance is %.8g %s and withdrawing '
                                                                        'fee on %s is %.8g %s. How much do you want to '
                                                                        'donate (excluding fees)' % (
                                                                            balance['free'][args[0]], args[0], exch,
                                                                            ct.exchange.fees['funding']['withdraw'][
                                                                                args[0]],
                                                                            args[0]))
                                    context.user_data['lastFct'].append(
                                        lambda res: self.inline_button_callback(update, context, query, res))
                                    return NUMBER
                                else:
                                    query.answer(
                                        '%s has insufficient free %s. Choose another exchange!' % (exch, args[0]))
                    else:
                        buttons = [[InlineKeyboardButton("Donate BTC", callback_data='1|%s|%s|BTC' % ('xxx', 'xxx')),
                                    InlineKeyboardButton("Donate ETH",
                                                         callback_data='%s|%s|%d|ETH' % ('xxx', 'xxx', 1)),
                                    InlineKeyboardButton("Donate NEO", callback_data='1|%s|%s|NEO' % ('xxx', 'xxx')),
                                    InlineKeyboardButton("Donate XLM", callback_data='1|%s|%s|XLM' % ('xxx', 'xxx')),
                                    InlineKeyboardButton("Donate USDT", callback_data='1|%s|%s|USDT' % ('xxx', 'xxx'))]]
                        query.edit_message_text(
                            'Thank you very much for your intention to donate some crypto! '
                            'Accepted coins are BTC, ETH and NEO.\nYou may either donate by sending coins manually to '
                            'one of the addresses below, or more easily by letting the bot send coins (amount will be '
                            'asked in a later step) from one of your exchanges by clicking the corresponding button '
                            'below.\n\n'
                            '*BTC address:*\nbc1q5wfzxdk3xhujs6589gzdeu6fgqpvqrel5jzzt2\n'
                            '*ETH address:*\n0xE0451300D96090c1F274708Bc00d791017D7a5F3\n'
                            '*NEO address:*\nAaGRMPuwtGrudXR5s7F5n11cxK595hCWUg\n'
                            '*XLM address:*\nGCEAF5KYYUJSYPEDAWTZUBP4TE2LUSAPAFNHFSY54RA4HNLBVYOSFM6K\n'
                            '*USDT address:*\n0x55b1be96e951bfce21973a233970245f728782f1\n',
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
                        query.edit_message_reply_markup(reply_markup=self.buttons_edit_tsh(ct))
                    else:
                        query.answer('Are you sure? This cannot be undone!')
                        query.edit_message_reply_markup(
                            reply_markup=InlineKeyboardMarkup(
                                [[InlineKeyboardButton("Yes",
                                                       callback_data=f'resetTSH|{exch}|XXX|yes'),
                                  InlineKeyboardButton("No",
                                                       callback_data=f'resetTSH|{exch}|XXX|no')]]))

                else:  # trade set commands
                    if exch not in context.user_data['trade'] or \
                            uid_ts not in context.user_data['trade'][exch].tradeSets:
                        query.edit_message_reply_markup()
                        query.edit_message_text('This trade set is not found anymore. Probably it was deleted')
                    else:
                        ct = context.user_data['trade'][exch]
                        ts = context.user_data['trade'][exch].tradeSets[uid_ts]
                        if command == '2':  # edit trade set
                            if 'chosen' in args:
                                try:
                                    query.edit_message_reply_markup(
                                        reply_markup=self.make_ts_inline_keyboard(exch, uid_ts))
                                except Exception:
                                    pass

                            if 'back' in args:
                                query.answer('')

                            elif any(['BLD' in val for val in args]):
                                ts.delete_buy_level(int([re.search(r'(?<=^BLD)\d+', val).group(0) for val in args if
                                                         isinstance(val, str) and 'BLD' in val][0]))
                                self.update_ts_text(context, uid_ts, query)
                                query.answer('Deleted buy level')

                            elif any(['SLD' in val for val in args]):
                                ts.delete_sell_level(int([re.search(r'(?<=^SLD)\d+', val).group(0) for val in args if
                                                          isinstance(val, str) and 'SLD' in val][0]))
                                self.update_ts_text(context, uid_ts, query)
                                query.answer('Deleted sell level')

                            elif 'buyRegAdd' in args:
                                query.answer('Adding new regular buy')
                                return self.ask_pos(context, exch, uid_ts, direction='reg_buy')

                            elif 'buyRegDel' in args:
                                ts.regular_buy = None
                                query.answer('Deleted regular buy')
                                self.update_ts_text(context, uid_ts, query)

                            elif 'buyAdd' in args:
                                query.answer('Adding new buy level')
                                return self.ask_pos(context, exch, uid_ts, direction='buy')

                            elif 'sellAdd' in args:
                                query.answer('Adding new sell level')
                                return self.ask_pos(context, exch, uid_ts, direction='sell')

                            elif any(['buyReAdd' in val for val in args]):
                                logger.info(args)
                                level = int([re.search(r'(?<=^buyReAdd)\d+', val).group(0) for val in args if
                                             isinstance(val, str) and 'buyReAdd' in val][0])
                                trade = ts.in_trades[level]
                                ts.add_buy_level(trade['price'], trade['amount'], trade['candleAbove'])
                                self.update_ts_text(context, uid_ts, query)

                            elif any(['sellReAdd' in val for val in args]):
                                level = int([re.search(r'(?<=^sellReAdd)\d+', val).group(0) for val in args if
                                             isinstance(val, str) and 'sellReAdd' in val][0])
                                trade = ts.out_trades[level]
                                ts.add_sell_level(uid_ts, trade['price'], trade['amount'])
                                self.update_ts_text(context, uid_ts, query)

                            elif 'AIC' in args:
                                query.answer('Adding initial coins')
                                return self.add_init_balance(context.bot, context.user_data, exch, uid_ts,
                                                             input_type=None,
                                                             response=None,
                                                             fct=lambda: self.print_trade_status(None, context,
                                                                                                 uid_ts))

                            elif 'TSgo' in args:
                                ts.activate()
                                self.update_ts_text(context, uid_ts, query)
                                query.answer('Trade set activated')

                            elif 'TSstop' in args:
                                ts.deactivate(cancel_orders=1)
                                self.update_ts_text(context, uid_ts, query)
                                query.answer('Trade set deactivated!')
                            elif 'ETSM' in args:
                                query.answer('Give a new trade set name')
                                return self.edit_trade_set_name(context, exch, uid_ts)

                            elif 'SLM' in args:
                                buttons = self.buttons_sl(ct, uid_ts)
                                query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
                                query.answer('Choose an option')

                            elif 'SLBE' in args:
                                ans = ts.set_sl_break_even()
                                if ans:
                                    query.answer('SL set break even')
                                else:
                                    query.answer('SL break even failed to set')
                                self.update_ts_text(context, uid_ts, query)

                            elif 'DCSL' in args:
                                # set a daily-close SL
                                if response is None:
                                    if 'yes' in args:
                                        query.message.delete()
                                        context.user_data['msgs'].send(which='dialog',
                                                                       text='Type the daily candle close price below, '
                                                                            'which SL would be triggered'
                                                                       )
                                        return NUMBER
                                    else:
                                        context.user_data['lastFct'].append(
                                            lambda res: self.inline_button_callback(update, context, query, res))
                                        context.user_data['msgs'].send(which='dialog',
                                                                       text='Do you want an SL, which is triggered, if '
                                                                            'the daily candle closes < X?',
                                                                       reply_markup=InlineKeyboardMarkup(
                                                                           [[InlineKeyboardButton(
                                                                               "Yes",
                                                                               callback_data='2|%s|%s|DCSL|yes' % (
                                                                                   exch, uid_ts)),
                                                                               InlineKeyboardButton(
                                                                                   "No",
                                                                                   callback_data='2|%s|%s|cancel' % (
                                                                                       exch, uid_ts))], [
                                                                               InlineKeyboardButton(
                                                                                   "Cancel",
                                                                                   callback_data='2|%s|%s|cancel' % (
                                                                                       exch,
                                                                                       uid_ts))]])
                                                                       )
                                else:
                                    ts.set_daily_close_sl(response)
                                    context.user_data['msgs'].delete_msgs(which='dialog')
                                    self.update_ts_text(context, uid_ts, query)

                            elif 'WCSL' in args:
                                # set a daily-close SL
                                if response is None:
                                    if 'yes' in args:
                                        query.message.delete()
                                        context.user_data['msgs'].send(which='dialog',
                                                                       text='Type the weekly candle close price below,'
                                                                            ' which SL would be triggered'
                                                                       )
                                        return NUMBER
                                    else:
                                        context.user_data['lastFct'].append(
                                            lambda res: self.inline_button_callback(update, context, query, res))
                                        context.user_data['msgs'].send(which='dialog',
                                                                       text='Do you want an SL that is triggered, if '
                                                                            'the weekly candle closes < X?',
                                                                       reply_markup=InlineKeyboardMarkup(
                                                                           [[InlineKeyboardButton(
                                                                               "Yes",
                                                                               callback_data='2|%s|%s|WCSL|yes' % (
                                                                                   exch, uid_ts)),
                                                                               InlineKeyboardButton(
                                                                                   "No",
                                                                                   callback_data='2|%s|%s|cancel' % (
                                                                                       exch, uid_ts))],
                                                                               [
                                                                                   InlineKeyboardButton(
                                                                                       "Cancel",
                                                                                       callback_data='2|%s|%s|cancel' % (
                                                                                           exch, uid_ts))]])
                                                                       )
                                else:
                                    ts.set_weekly_close_sl(response)
                                    context.user_data['msgs'].delete_msgs(which='dialog')
                                    self.update_ts_text(context, uid_ts, query)

                            elif 'TSL' in args:
                                # set a trailing stop-loss
                                if response is None:
                                    query.answer()
                                    if 'abs' in args or 'rel' in args:
                                        query.message.delete()
                                        context.user_data['msgs'].send(which='dialog',
                                                                       text='Please enter the trailing SL offset%s' % (
                                                                           '' if 'abs' in args else ' in %')
                                                                       )
                                        context.user_data['lastFct'].append(
                                            lambda res: self.inline_button_callback(update, context, query, res))
                                        return NUMBER
                                    else:
                                        context.user_data['msgs'].send(which='dialog',
                                                                       text="What kind of trailing stop-loss offset do "
                                                                            "you want to set?",
                                                                       reply_markup=InlineKeyboardMarkup(
                                                                           [[InlineKeyboardButton(
                                                                               "Absolute",
                                                                               callback_data='2|%s|%s|TSL|abs' % (
                                                                                   exch, uid_ts)),
                                                                               InlineKeyboardButton(
                                                                                   "Relative",
                                                                                   callback_data='2|%s|%s|TSL|rel' % (
                                                                                       exch, uid_ts))]])
                                                                       )
                                else:
                                    response = float(response)
                                    if 'rel' in args:
                                        response /= 100
                                    ts.set_trailing_sl(response,
                                                       typ=ValueType.ABSOLUTE if 'abs' in args else ValueType.RELATIVE)
                                    context.user_data['msgs'].delete_msgs(which='dialog')
                                    self.update_ts_text(context, uid_ts, query)

                            elif 'SLC' in args:
                                if response is None:
                                    query.answer('Please enter the new SL (0 = no SL)')
                                    context.user_data['lastFct'].append(
                                        lambda res: self.inline_button_callback(update, context, query, res))
                                    return NUMBER
                                else:
                                    response = float(response)
                                    if response == 0:
                                        response = None
                                    ts.set_sl(response)
                                    self.update_ts_text(context, uid_ts, query)
                            elif 'TFO' in args:
                                # toggle filled orders
                                ts.show_filled_orders = (ts.show_filled_orders + 1) % 2
                                self.update_ts_text(context, uid_ts, query)
                            else:
                                buttons = self.buttons_edit_ts(ct, uid_ts, 'full')
                                query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
                                query.answer('Choose an option')
                        elif command == '3':  # init trade set deletion
                            if 'ok' in args:
                                query.message.delete()
                                ct.delete_trade_set(uid_ts, sell_all='yes' in args)
                                query.answer('Trade Set deleted')
                            elif 'yes' in args or 'no' in args:
                                query.answer('Ok, and are you really sure to delete this trade set?')
                                query.edit_message_reply_markup(
                                    reply_markup=InlineKeyboardMarkup(
                                        [[
                                            InlineKeyboardButton(
                                                "Yes",
                                                callback_data=f"3|{exch}|{uid_ts}|ok|{'|'.join(args)}"),
                                            InlineKeyboardButton("Cancel",
                                                                 callback_data='3|%s|%s|cancel' % (exch, uid_ts))
                                        ]]))
                            else:
                                query.answer('Do you want to sell your remaining coins?')
                                query.edit_message_reply_markup(
                                    reply_markup=InlineKeyboardMarkup(
                                        [[InlineKeyboardButton("Yes", callback_data='3|%s|%s|yes' % (exch, uid_ts)),
                                          InlineKeyboardButton("No", callback_data='3|%s|%s|no' % (exch, uid_ts))
                                          ]]))
        return MAINMENU

    def start_bot(self):
        print(
            f'\n\n******** Welcome to EazeBot (v{self.thisVersion}) ********\n'
            'Free python/telegram bot for easy execution & surveillance of crypto trading plans on multiple exchanges'
            '\n\n')

        # %% define the handlers to communicate with user
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start_cmd)],
            states={
                MAINMENU: [MessageHandler(Filters.regex('^Status of Trade Sets$'), self.print_trade_status),
                           MessageHandler(Filters.regex('^New Trade Set$'), self.create_trade_set),
                           MessageHandler(Filters.regex('^Trade History$'), self.print_trade_history),
                           MessageHandler(Filters.regex('^Update exchanges$'), self.add_exchanges_from_context),
                           MessageHandler(Filters.regex('^Bot Info$'), self.bot_info),
                           MessageHandler(Filters.regex('^Check Balance$'), self.check_balance),
                           MessageHandler(Filters.regex('^Settings$'), self.show_settings),
                           CallbackQueryHandler(self.inline_button_callback),
                           MessageHandler(Filters.text, lambda u, c: self.noncomprende(u, c, 'noValueRequested'))],
                SYMBOL_OR_RAW: [MessageHandler(Filters.regex(r'^\w+/\w+$'), self.received_info),
                                MessageHandler(Filters.regex(re.compile(r'^\w+/\w+\n.*TARGETS',
                                                                        re.DOTALL | re.IGNORECASE)),
                                               self.received_info),
                                MessageHandler(Filters.text, lambda u, c: self.noncomprende(u, c, 'wrongSymbolFormat')),
                                CallbackQueryHandler(self.inline_button_callback)],
                NUMBER: [MessageHandler(Filters.regex(r'^[\+,\-]?\d+\.?\d*$'), self.received_float),
                         MessageHandler(Filters.text, lambda u, c: self.noncomprende(u, c, 'noNumber')),
                         CallbackQueryHandler(self.inline_button_callback)],
                DATE: [MessageHandler(DateFilter(), self.received_date),
                       MessageHandler(Filters.text, lambda u, c: self.noncomprende(u, c, 'noDate')),
                       CallbackQueryHandler(self.inline_button_callback)],
                DAILY_CANDLE: [CallbackQueryHandler(self.daily_candle_callback),
                               CallbackQueryHandler(self.inline_button_callback)],
                INFO: [MessageHandler(Filters.regex(r'\w+'), self.received_info)],
                TS_NAME: [MessageHandler(Filters.regex(r'^[\w!#?\s-]{1,15}$'), self.received_short_name),
                          MessageHandler(Filters.text, lambda u, c: self.noncomprende(u, c, 'noShortName')),
                          CallbackQueryHandler(self.inline_button_callback)]
            },
            fallbacks=[CommandHandler('exit', self.exit_cmd)], allow_reentry=True)  # , per_message = True)
        unknown_handler = MessageHandler(Filters.command, lambda u, c: self.noncomprende(u, c, 'unknownCmd'))

        # %% start telegram API, add handlers to dispatcher and start bot
        self.updater.dispatcher.add_handler(conv_handler)
        self.updater.dispatcher.add_handler(CommandHandler('exit', self.ask_stop_bot_message))
        self.updater.dispatcher.add_handler(unknown_handler)
        self.updater.dispatcher.user_data = clean_data(load_data(no_dialog=True), self.__config__['telegramUserId'])

        for user in self.__config__['telegramUserId']:
            if user in self.updater.dispatcher.user_data and len(self.updater.dispatcher.user_data[user]) > 0:
                context = CallbackContext(self.updater.dispatcher)
                self.updater.dispatcher.user_data[user].update({'msgs': MessageContainer(bot=context.bot,
                                                                                         chat_id=user)})
                time.sleep(2)  # wait because of possibility of temporary exchange lockout
                self.add_exchanges(self.updater.dispatcher.user_data[user])

        # start a job updating the trade sets each interval
        self.updater.job_queue.run_repeating(self.update_trade_sets, interval=60 * self.__config__['updateInterval'],
                                             first=5,
                                             context=self.updater)
        # start a job checking for updates once a day
        self.updater.job_queue.run_repeating(self.check_for_updates_and_tax, interval=60 * 60 * 24, first=20,
                                             context=self.updater)
        # start a job checking every day 10 sec after midnight (UTC time)
        self.updater.job_queue.run_daily(lambda cont: self.check_candle(cont, 1),
                                         (dt.datetime(1900, 5, 5, 0, 0, 10) + (
                                                 dt.datetime.now() - dt.datetime.utcnow())).time(),
                                         context=self.updater, name='dailyCheck')
        # start a job saving the user data each 5 minutes
        self.updater.job_queue.run_repeating(lambda con: save_data(con, user_dir=self.user_dir), interval=5 * 60,
                                             context=self.updater)
        # start a job making backup of the user data each x days
        self.updater.job_queue.run_repeating(
            lambda con: backup_data(con, max_count=self.__config__["maxBackupFileCount"]),
            interval=60 * 60 * 24 * self.__config__['extraBackupInterval'],
            context=self.updater, )
        if not self.__config__['debug']:
            for user in self.__config__['telegramUserId']:
                try:
                    self.updater.bot.send_message(user, 'Bot was restarted.\n Please press /start to continue.',
                                                  reply_markup=ReplyKeyboardMarkup([['/start']],
                                                                                   one_time_keyboard=True))
                except Exception:
                    pass
            self.updater.start_polling()
            while True:
                time.sleep(1)
                if self.state in [STATE.INTERRUPTED, STATE.UPDATING]:
                    if self.state == STATE.UPDATING:
                        text = ' for updating itsself. Please be patient'
                    else:
                        text = ''
                    self.updater.stop()
                    for user in self.__config__['telegramUserId']:
                        chat_obj = self.updater.bot.get_chat(user)
                        try:
                            self.updater.bot.send_message(
                                user,
                                f"Bot was stopped{text}! Trades are not surveilled until bot is started again! "
                                f"See you soon {chat_obj.first_name}!")
                        except Exception:
                            pass
                    break

            save_data(self.updater.dispatcher.user_data, user_dir=self.user_dir)  # last data save when finishing
            return
        else:
            return self.updater
