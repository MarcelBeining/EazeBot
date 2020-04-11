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
"""This class is used to control trading sets"""
from typing import Union
import ccxt
import re
from json import JSONDecodeError
from inspect import getsourcefile, getsourcelines
import numpy as np
import time
import datetime
import random
import string
import sys
import os
from ccxt.base.errors import (AuthenticationError, NetworkError, OrderNotFound, InvalidNonce, ExchangeError,
                              InsufficientFunds)


class tradeHandler:

    def __init__(self, exch_name, key=None, secret=None, password=None, uid=None, messager_fct=None, logger=None):
        # use either the given messager function or define a simple print messager function which takes a level
        # argument as second optional input
        try:
            self.message = self.update_messager_fct(messager_fct)
        except TypeError:
            self.message = lambda a, b='Info': print(b + ': ' + a)

        self.logger = logger
        checkThese = ['cancelOrder', 'createLimitOrder', 'fetchBalance', 'fetchTicker']
        self.tradeSets = {}
        self.tradeSetHistory = []
        if exch_name == 'kucoin2':
            exch_name = exch_name.replace('kucoin2', 'kucoin')
        self.exchange = getattr(ccxt, exch_name)({'enableRateLimit': True, 'options': {
            'adjustForTimeDifference': True}})  # 'nonce': ccxt.Exchange.milliseconds,
        if key:
            self.exchange.apiKey = key
        if secret:
            self.exchange.secret = secret
        if password:
            self.exchange.password = password
        if uid:
            self.exchange.uid = uid

        self.updating = False
        self.waiting = []
        self.down = False
        self.authenticated = False
        if key:
            self.update_keys(key, secret, password, uid)

        if not all([self.exchange.has[x] for x in checkThese]):
            text = 'Exchange %s does not support all required features (%s)' % (exch_name, ', '.join(checkThese))
            self.message(text, 'error')
            raise Exception(text)
        self.lastUpdate = time.time() - 10
        self.amount2Prec = lambda a, b: self.x_to_prec(a, b, 'amount')
        self.price2Prec = lambda a, b: self.x_to_prec(a, b, 'price')
        self.cost2Prec = lambda a, b: self.x_to_prec(a, b, 'cost')
        self.fee2Prec = lambda a, b: self.x_to_prec(a, b, 'fee')

    def __reduce__(self):
        # function needes for serializing the object
        return (
            self.__class__, (self.exchange.__class__.__name__, None, None, None, None, self.message),
            self.__getstate__(),
            None, None)

    def __setstate__(self, state):
        if isinstance(state, tuple):
            state, tshs = state
        else:
            tshs = []
        for iTs in state:  # temp fix for old trade sets that do not some of the newer fields
            ts = state[iTs]
            # clear updating variables from old state
            ts['waiting'] = []
            ts['updating'] = False
            if 'trailingSL' not in ts:
                ts['trailingSL'] = [None, None]
            if 'dailycloseSL' not in ts:
                ts['dailycloseSL'] = None
            if 'weeklycloseSL' not in ts:
                ts['weeklycloseSL'] = None
            for trade in ts['InTrades']:
                if 'actualAmount' not in trade:
                    fee = self.calculate_fee(ts['symbol'], 'limit', 'buy', trade['amount'], trade['price'], 'maker')
                    if fee['currency'] == ts['coinCurrency']:
                        trade['actualAmount'] = trade['amount']
                        # this is a hack, as fees on binance are deduced from BNB if this is activated and there is
                        # enough BNB, however so far no API chance to see if this is the case. Here I assume that
                        # 0.5 BNB are enough to pay the fee for the trade and thus the fee is not subtracted from the
                        # traded coin
                        if self.exchange.name.lower() != 'binance' or self.get_balance('BNB') < 0.5:
                            trade['actualAmount'] -= fee['cost']
                    else:
                        trade['actualAmount'] = trade['amount']
        self.tradeSets = state
        self.tradeSetHistory = tshs

    def __getstate__(self):
        if hasattr(self, 'tradeSetHistory'):
            return self.tradeSets, self.tradeSetHistory
        else:
            return self.tradeSets, []

    def x_to_prec(self, pair, x, what):
        if x is None:
            return 'N/A'
        if what == 'amount':
            fct = self.exchange.amountToPrecision
        elif what == 'cost':
            fct = self.exchange.costToPrecision
        elif what == 'price':
            fct = self.exchange.priceToPrecision
        elif what == 'fee':
            fct = lambda a, b: str(b)
        else:
            raise ValueError(f"Unknown argument {what}")

        result = fct(pair, x)
        if isinstance(result, str):
            return self.strip_zeros(result)
        else:
            return self.strip_zeros(format(result, '.10f'))

    @staticmethod
    def strip_zeros(string):
        if '.' in string:
            return string.rstrip('0').rstrip('.')
        else:
            return string

    def check_num(self, *value):
        return all(
            [(isinstance(val, float) | isinstance(val, int)) if not isinstance(val, list) else self.check_num(*val) for
             val in value])

    def check_quantity(self, symbol, typ, qty):
        if typ not in ['amount', 'price', 'cost']:
            raise ValueError('Type is not amount, price or cost')
        if typ in self.exchange.markets[symbol]['limits']:
            return (self.exchange.markets[symbol]['limits'][typ]['min'] is None or qty >=
                    self.exchange.markets[symbol]['limits'][typ]['min']) and (
                           self.exchange.markets[symbol]['limits'][typ]['max'] is None or
                           self.exchange.markets[symbol]['limits'][typ]['max'] == 0 or qty <=
                           self.exchange.markets[symbol]['limits'][typ]['max'])
        else:
            if self.logger:
                self.logger.warning('Exchange %s does not provide limits for %s' % (self.exchange.name, typ))
            return True

    def update_messager_fct(self, messager_fct):
        if callable(messager_fct):
            self.message = messager_fct
        else:
            raise TypeError('Messager function is not callable')

    def safe_run(self, func, print_error=True, iTs=None):
        count = 0
        wasdown = self.down
        while True:
            try:
                self.down = False
                return func()
            except InvalidNonce:
                count += 1
                # this tries to resync the system timestamp with the exchange's timestamp
                if hasattr(self.exchange, 'load_time_difference'):
                    self.exchange.load_time_difference()
                time.sleep(0.5)
                continue
            except NetworkError as e:
                count += 1
                if hasattr(self.exchange, 'load_time_difference'):
                    self.exchange.load_time_difference()
                if count >= 5:
                    self.down = True
                    if iTs:
                        self.unlock_trade_set(iTs)
                    if 'Cloudflare' in str(e):
                        if print_error:
                            self.message('Cloudflare problem with exchange %s. Exchange is treated as down. %s' % (
                                self.exchange.name, '' if iTs is None else 'TradeSet %d (%s)' % (
                                    list(self.tradeSets.keys()).index(iTs), self.tradeSets[iTs]['symbol'])), 'Error')
                    elif print_error:
                        self.message('Network exception occurred 5 times in a row. %s is treated as down. %s' % (
                            self.exchange.name, '' if iTs is None else 'TradeSet %d (%s)' % (
                                list(self.tradeSets.keys()).index(iTs), self.tradeSets[iTs]['symbol'])), 'Error')
                    raise (e)
                else:
                    time.sleep(0.5)
                    continue
            except OrderNotFound as e:
                count += 1
                if count >= 5:
                    if iTs:
                        self.unlock_trade_set(iTs)
                    if print_error:
                        self.message(f"Order not found error 5 times in a row on {self.exchange.name}"
                                     '' if iTs is None else
                                     f" for tradeSet {list(self.tradeSets.keys()).index(iTs)} ({self.tradeSets[iTs]['symbol']}",
                                     'Error')
                    raise (e)
                else:
                    time.sleep(0.5)
                    continue
            except AuthenticationError as e:
                count += 1
                if count >= 5:
                    if iTs:
                        self.unlock_trade_set(iTs)
                    raise e
                else:
                    time.sleep(0.5)
                    continue
            except JSONDecodeError as e:
                if iTs:
                    self.unlock_trade_set(iTs)
                if 'Expecting value' in str(e):
                    self.down = True
                    if print_error:
                        self.message('%s seems to be down.' % self.exchange.name)
                raise e
            except Exception as e:
                if count < 4 and isinstance(e, ExchangeError) and "symbol" in str(e).lower():
                    self.safe_run(self.exchange.loadMarkets)
                    count += 1
                    continue
                elif count < 4 and ('unknown error' in str(e).lower() or 'connection' in str(e).lower()):
                    count += 1
                    time.sleep(0.5)
                    continue
                else:
                    if iTs:
                        self.unlock_trade_set(iTs)
                    string = 'Exchange %s\n' % self.exchange.name
                    if count >= 5:
                        string += 'Network exception occurred 5 times in a row! Last error was:\n'
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    # fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    lines = getsourcelines(func)
                    string += '%s in %s from %s at line %d: %s' % (
                        exc_type, lines[0][0], os.path.basename(getsourcefile(func)), lines[1], str(e))

                    if print_error:
                        self.message(string, 'Error')
                    raise e
            finally:
                if wasdown and not self.down:
                    self.message('Exchange %s seems back to work!' % self.exchange.name)

    def lock_trade_set(self, iTs):
        # avoids two processes changing a tradeset at the same time
        count = 0
        mystamp = time.time()
        self.tradeSets[iTs]['waiting'].append(mystamp)
        time.sleep(0.2)
        while self.tradeSets[iTs]['updating'] or self.tradeSets[iTs]['waiting'][0] < mystamp:
            count += 1
            time.sleep(1)
            if count > 60:  # 60 sec max wait
                try:  # cautionary so that no timestamp can stay in the queue due to some messaging error
                    self.message(
                        'Waiting for tradeSet update (%s on %s) to finish timed out after 1 min.. Resetting updating variable now.' % (
                            self.tradeSets[iTs]['symbol'], self.exchange.name), 'error')
                except:
                    pass
                break
        self.tradeSets[iTs]['updating'] = True
        self.tradeSets[iTs]['waiting'].remove(mystamp)

    def unlock_trade_set(self, iTs):
        self.tradeSets[iTs]['updating'] = False

    def update_balance(self):
        self.update_down_state(True)
        # reloads the exchange market and private balance and, if successul, sets the exchange as authenticated
        self.safe_run(self.exchange.loadMarkets)
        self.balance = self.safe_run(self.exchange.fetch_balance)
        self.authenticated = True

    def get_balance(self, coin, balance_type='free'):
        assert balance_type in ['free', 'total'], f"Unknown balance type {balance_type}"
        if coin in self.balance:
            return self.balance[coin][balance_type]
        else:
            return 0

    def update_keys(self, key=None, secret=None, password=None, uid=None):
        if key:
            self.exchange.apiKey = key
        if secret:
            self.exchange.secret = secret
        if password:
            self.exchange.password = password
        if uid:
            self.exchange.uid = uid
        try:  # check if keys work
            self.update_balance()
        except AuthenticationError as e:  #
            self.authenticated = False
            try:
                self.message('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                             'error')
            except:
                print('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name)
        except getattr(ccxt, 'ExchangeError') as e:
            self.authenticated = False
            if 'key' in str(e).lower():
                try:
                    self.message('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                                 'error')
                except:
                    print('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name)
            else:
                try:
                    self.message('The following error occured at exchange %s:\n%s' % (self.exchange.name, str(e)),
                                 'error')
                except:
                    print('The following error occured at exchange %s:\n%s' % (self.exchange.name, str(e)))

    def calculate_fee(self, symbol, typ, direction, amount, price, makerOrTaker):
        return self.exchange.calculate_fee(symbol, typ, direction, amount, price, makerOrTaker)

    def init_trade_set(self, symbol):
        self.update_balance()

        iTs = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
        # redo if uid already reserved
        while iTs in self.tradeSets:
            iTs = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))

        ts = {'symbol': symbol, 'InTrades': [], 'createdAt': time.time(),
              'OutTrades': [], 'baseCurrency': re.search("(?<=/).*", symbol).group(0),
              'coinCurrency': re.search(".*(?=/)", symbol).group(0), 'costIn': 0,
              'costOut': 0, 'coinsAvail': 0, 'initCoins': 0, 'initPrice': None,
              'SL': None, 'trailingSL': [None, None], 'dailycloseSL': None,
              'weeklycloseSL': None, 'active': False, 'virgin': True, 'updating': False,
              'waiting': []}
        self.tradeSets[iTs] = ts
        return ts, iTs

    def activate_trade_set(self, iTs, verbose=True):
        self.update_down_state(True)
        ts = self.tradeSets[iTs]
        wasactive = ts['active']
        # check if symbol is active
        if not self.exchange.markets[ts['symbol']]['active']:
            self.message(
                'Cannot activate trade set because %s was deactivated for trading by the exchange!' % ts['symbol'],
                'error')
            return wasactive
        # sanity check of amounts to buy/sell
        if self.sum_sell_amounts(iTs, 'notinitiated') - (self.sum_buy_amounts(iTs, 'notfilled') + ts['coinsAvail']) > 0:
            self.message(
                f"Cannot activate trade set because the total amount you (still) want to sell "
                f"({self.amount2Prec(ts['symbol'], self.sum_sell_amounts(iTs, 'notinitiated', True))} "
                f"{ts['coinCurrency']}) exceeds the total amount you want to buy "
                f"({self.amount2Prec(ts['symbol'], self.sum_buy_amounts(iTs, 'notfilled', True))} {ts['coinCurrency']} "
                f"after fee subtraction) and the amount you already have in this trade set "
                f"({self.amount2Prec(ts['symbol'], ts['coinsAvail'])} {ts['coinCurrency']}). "
                f"Please adjust the trade set!", 'error')
            return wasactive
        elif self.min_buy_price(iTs, order='notfilled') is not None and ts['SL'] is not None and ts[
            'SL'] >= self.min_buy_price(iTs, order='notfilled'):
            self.message(
                'Cannot activate trade set because the current stop loss price is higher than the lowest non-filled buy'
                ' order price, which means this buy order could never be reached. Please adjust the trade set!',
                'error')
            return wasactive
        self.tradeSets[iTs]['virgin'] = False
        self.tradeSets[iTs]['active'] = True
        if verbose and not wasactive:
            totalBuyCost = ts['costIn'] + self.sum_buy_costs(iTs, 'notfilled')
            self.message('Estimated return if all trades are executed: %s %s' % (
                self.cost2Prec(ts['symbol'], self.sum_sell_costs(iTs) - totalBuyCost), ts['baseCurrency']))
            if ts['SL'] is not None or ts['dailycloseSL'] is not None:
                sl = [val for val in [ts['SL'], ts['dailycloseSL'] if 'dailycloseSL' in ts else None,
                                      ts['weeklycloseSL'] if 'weeklycloseSL' in ts else None, ] if val is not None][0]
                loss = totalBuyCost - ts['costOut'] - (
                        ts['initCoins'] + self.sum_buy_amounts(iTs) - self.sum_sell_amounts(iTs, 'filled')) * sl
                self.message('Estimated %s if buys reach stop-loss before selling: %s %s' % (
                    '*gain*' if loss < 0 else 'loss', self.cost2Prec(ts['symbol'], -loss if loss < 0 else loss),
                    ts['baseCurrency']))
        try:
            self.init_buy_orders(iTs)
        except InsufficientFunds as e:
            self.message('Cannot activate trade set due to insufficient funds!', 'error')
            self.deactivate_trade_set(iTs)
        return wasactive

    def deactivate_trade_set(self, iTs, cancel_orders=0):
        self.update_down_state(True)
        # cancelOrders can be 0 (not), 1 (cancel), 2 (cancel and delete open orders)
        wasactive = self.tradeSets[iTs]['active']
        if cancel_orders:
            self.cancel_buy_orders(iTs, deleteOrders=cancel_orders == 2)
            self.cancel_sell_orders(iTs, delete_orders=cancel_orders == 2)
        self.tradeSets[iTs]['active'] = False
        return wasactive

    def new_trade_set(self, symbol, buy_levels=None, buy_amounts=None, sell_levels=None, sell_amounts=None, sl=None,
                      candle_above=None,
                      init_coins=0, init_price=None, force=False):
        if candle_above is None:
            candle_above = []
        if sell_amounts is None:
            sell_amounts = []
        if sell_levels is None:
            sell_levels = []
        if buy_amounts is None:
            buy_amounts = []
        if buy_levels is None:
            buy_levels = []
        self.update_down_state(True)
        if symbol not in self.exchange.symbols:
            raise NameError('Trading pair %s not found on %s' % (symbol, self.exchange.name))
        if not self.check_num(buy_amounts) or not self.check_num(buy_levels):
            raise TypeError('Buy levels and amounts must be of type float!')
        if not self.check_num(sell_amounts) or not self.check_num(sell_levels):
            raise TypeError('Sell levels and amounts must be of type float!')
        if sl and not self.check_num(sl):
            raise TypeError('Stop-loss must be of type float!')
        if not self.check_num(init_coins):
            raise TypeError('Initial coin amount must be of type float!')
        if len(buy_levels) != len(buy_amounts):
            raise ValueError('The number of buy levels and buy amounts has to be the same')
        if len(sell_levels) != len(sell_amounts):
            raise ValueError('The number of sell levels and sell amounts has to be the same')

        ts, iTs = self.init_trade_set(symbol)

        # truncate values to precision        
        sell_levels = [float(self.exchange.priceToPrecision(ts['symbol'], val)) for val in sell_levels]
        buy_levels = [float(self.exchange.priceToPrecision(ts['symbol'], val)) for val in buy_levels]
        sell_amounts = [float(self.exchange.amountToPrecision(ts['symbol'], val)) for val in sell_amounts]
        buy_amounts = [float(self.exchange.amountToPrecision(ts['symbol'], val)) for val in buy_amounts]

        # sort sell levels and amounts to have lowest level first
        idx = np.argsort(sell_levels)
        sell_levels = np.array(sell_levels)[idx]
        sell_amounts = np.array(sell_amounts)[idx]
        buy_levels = np.array(buy_levels)
        buy_amounts = np.array(buy_amounts)
        if len(buy_amounts) != len(candle_above):
            candle_above = [None] * len(buy_amounts)
        else:
            candle_above = np.array(candle_above)

        if not force and sum(buy_amounts) != sum(sell_amounts):
            if self.logger:
                self.logger.warning(
                    'It seems the buy and sell amount of %s is not the same. Is this correct?' % ts['coinCurrency'])
        if buy_levels.size > 0 and sell_levels.size > 0 and max(buy_levels) > min(sell_levels):
            raise ValueError(
                'It seems at least one of your sell prices is lower than one of your buy, which does not make sense')
        if self.balance[ts['baseCurrency']]['free'] < sum(buy_levels * buy_amounts):
            raise ValueError('Free balance of %s not sufficient to initiate trade set' % ts['baseCurrency'])

        # create the buy orders
        for n, _ in enumerate(buy_levels):
            self.add_buy_level(iTs, buy_levels[n], buy_amounts[n], candle_above[n])

        self.add_init_coins(iTs, init_coins, init_price)
        self.set_sl(iTs, sl)
        self.set_trailing_sl(iTs, None)
        # create the sell orders
        for n, _ in enumerate(sell_levels):
            self.add_sell_level(iTs, sell_levels[n], sell_amounts[n])

        self.activate_trade_set(iTs)
        self.update()
        return iTs

    def get_trade_set_info(self, iTs, show_profit_in=None):
        ts = self.tradeSets[iTs]
        prt_str = '*%srade set #%d on %s%s [%s]:*\n' % ('T' if ts['active'] else 'INACTIVE t',
                                                        list(self.tradeSets.keys()).index(iTs), self.exchange.name,
                                                        ' (DOWN !!!) ' if self.down else '', ts['symbol'])
        filled_buys = []
        filled_sells = []
        for iTrade, trade in enumerate(ts['InTrades']):
            tmpstr = '*Buy level %d:* Price %s , Amount %s %s   ' % (
                iTrade, self.price2Prec(ts['symbol'], trade['price']), self.amount2Prec(ts['symbol'], trade['amount']),
                ts['coinCurrency'])
            if trade['oid'] is None:
                if trade['candleAbove'] is None:
                    tmpstr = tmpstr + '_Order not initiated_\n'
                else:
                    tmpstr = tmpstr + 'if DC > %s\n' % self.price2Prec(ts['symbol'], trade['candleAbove'])
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                filled_buys.append([trade['actualAmount'], trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            prt_str += tmpstr
        prt_str += '\n'
        for iTrade, trade in enumerate(ts['OutTrades']):
            tmpstr = '*Sell level %d:* Price %s , Amount %s %s   ' % (
                iTrade, self.price2Prec(ts['symbol'], trade['price']), self.amount2Prec(ts['symbol'], trade['amount']),
                ts['coinCurrency'])
            if trade['oid'] is None:
                tmpstr = tmpstr + '_Order not initiated_\n'
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                filled_sells.append([trade['amount'], trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            prt_str += tmpstr
        if ts['SL'] is not None:
            prt_str += '\n*Stop-loss* set at %s%s\n\n' % (self.price2Prec(ts['symbol'], ts['SL']),
                                                          '' if ts['trailingSL'][0] is None else (
                                                              ' (trailing with offset %.5g)' % ts['trailingSL'][0] if
                                                              ts['trailingSL'][
                                                                  1] == 'abs' else ' (trailing with offset %.2g %%)' % (
                                                                      ts['trailingSL'][0] * 100)))
        elif ts['dailycloseSL'] is not None:
            prt_str += '\n*Stop-loss* set at daily close < %s\n\n' % (self.price2Prec(ts['symbol'], ts['dailycloseSL']))
        elif ts['weeklycloseSL'] is not None:
            prt_str += '\n*Stop-loss* set at weekly close < %s\n\n' % (
                self.price2Prec(ts['symbol'], ts['weeklycloseSL']))
        else:
            prt_str += '\n*No stop-loss set.*\n\n'
        sumBuys = sum([val[0] for val in filled_buys])
        sumSells = sum([val[0] for val in filled_sells])
        if ts['initCoins'] > 0:
            prt_str += '*Initial coins:* %s %s for an average price of %s\n' % (
                self.amount2Prec(ts['symbol'], ts['initCoins']), ts['coinCurrency'],
                self.price2Prec(ts['symbol'], ts['initPrice']) if ts['initPrice'] is not None else 'unknown')
        if sumBuys > 0:
            prt_str += '*Filled buy orders (fee subtracted):* %s %s for an average price of %s\n' % (
                self.amount2Prec(ts['symbol'], sumBuys), ts['coinCurrency'], self.cost2Prec(ts['symbol'], sum(
                    [val[0] * val[1] / sumBuys if sumBuys > 0 else None for val in filled_buys])))
        if sumSells > 0:
            prt_str += '*Filled sell orders:* %s %s for an average price of %s\n' % (
                self.amount2Prec(ts['symbol'], sumSells), ts['coinCurrency'], self.cost2Prec(ts['symbol'], sum(
                    [val[0] * val[1] / sumSells if sumSells > 0 else None for val in filled_sells])))
        if self.exchange.markets[ts['symbol']]['active']:
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(ts['symbol']))
            prt_str += '\n*Current market price *: %s, \t24h-high: %s, \t24h-low: %s\n' % tuple(
                [self.price2Prec(ts['symbol'], val) for val in [ticker['last'], ticker['high'], ticker['low']]])
            if (ts['initCoins'] == 0 or ts['initPrice'] is not None) and ts['costIn'] > 0 and (
                    sumBuys > 0 or ts['initCoins'] > 0):
                totalAmountToSell = ts['coinsAvail'] + self.sum_sell_amounts(iTs, 'open')
                fee = self.calculate_fee(ts['symbol'], 'market', 'sell', totalAmountToSell, ticker['last'], 'taker')
                costSells = ts['costOut'] + ticker['last'] * totalAmountToSell - (
                    fee['cost'] if fee['currency'] == ts['baseCurrency'] else 0)
                gain = costSells - ts['costIn']
                gainOrig = gain
                if show_profit_in is not None:
                    gain, thisCur = self.convert_amount(gain, ts['baseCurrency'], show_profit_in)
                else:
                    thisCur = ts['baseCurrency']
                prt_str += '\n*Estimated gain/loss when selling all now: * %s %s (%+.2f %%)\n' % (
                    self.cost2Prec(ts['symbol'], gain), thisCur, gainOrig / (ts['costIn']) * 100)
        else:
            prt_str += '\n*Warning: Symbol %s is currently deactivated for trading by the exchange!*\n' % ts['symbol']
        return prt_str

    def create_trade_history_entry(self, iTs):
        self.update_down_state(True)
        # create a trade history entry if the trade set had any filled orders
        ts = self.tradeSets[iTs]
        if self.num_buy_levels(iTs, 'filled') > 0 or self.num_sell_levels(iTs, 'filled') > 0:
            gain = ts['costOut'] - ts['costIn']
            # try to convert gain amount into btc currency
            gainBTC, curr = self.convert_amount(gain, ts['baseCurrency'], 'BTC')
            if curr != 'BTC':
                gainBTC = None
            if gainBTC:
                # try to convert btc gain into usd currency
                gainUSD, curr = self.convert_amount(gainBTC, 'BTC', 'USD')
                if curr != 'USD':
                    gainUSD, curr = self.convert_amount(gainBTC, 'BTC', 'USDT')
                    if curr != 'USDT':
                        gainUSD = None
            else:
                gainUSD = None
            self.tradeSetHistory.append({'time': time.time(),
                                         'days': None if not 'createdAt' in ts
                                         else (time.time() - ts['createdAt']) / 60 / 60 / 24,
                                         'symbol': ts['symbol'], 'gain': gain,
                                         'gainRel': gain / (ts['costIn']) * 100 if ts['costIn'] > 0 else None,
                                         'quote': ts['baseCurrency'], 'gainBTC': gainBTC, 'gainUSD': gainUSD})

    def get_trade_history(self):
        string = ''
        for tsh in self.tradeSetHistory:
            string += '%s:  %s\t%s%% ( %s BTC | %s USD)\n' % (
                datetime.datetime.utcfromtimestamp(tsh['time']).strftime('%Y-%m-%d'), tsh['symbol'],
                '%+7.1f' % tsh['gainRel'] if tsh['gainRel'] else 'N/A',
                '%+.5f' % tsh['gainBTC'] if tsh['gainBTC'] else 'N/A',
                '%+.2f' % tsh['gainUSD'] if tsh['gainUSD'] else 'N/A')
        if len(self.tradeSetHistory) > 0:
            return f"*Profit history on {self.exchange.name}:\n\
            Avg. relative gain: {np.mean([tsh['gainRel'] for tsh in self.tradeSetHistory if tsh['gainRel'] is not None]):+7.1f}%%\n\
            Total profit in BTC: {sum([tsh['gainBTC'] if tsh['gainBTC'] else 0 for tsh in self.tradeSetHistory]):+.5f}\n \
            Total profit in USD: {sum([tsh['gainUSD'] if tsh['gainUSD'] else 0 for tsh in self.tradeSetHistory]):+.2f}\n \
            \nDetailed Set Info:\n*" + string
        else:
            return '*No profit history on %s*' % self.exchange.name

    def reset_trade_history(self):
        self.tradeSetHistory = []
        self.logger.info('Trade set history on %s cleared' % self.exchange.name)
        return 1

    def convert_amount(self, amount, currency, targetCurrency):
        self.update_down_state(True)
        if isinstance(targetCurrency, str):
            targetCurrency = [targetCurrency]

        conversionPairs = [('%s/%s' % (currency, cur) in self.exchange.symbols and
                            self.exchange.markets['%s/%s' % (currency, cur)]['active']) + 2 * (
                                   '%s/%s' % (cur, currency) in self.exchange.symbols and
                                   self.exchange.markets['%s/%s' % (cur, currency)]['active']) for cur in
                           targetCurrency]
        ind = next((i for i, x in enumerate(conversionPairs) if x), None)
        if ind is not None:
            thisCur = targetCurrency[ind]
            if conversionPairs[ind] == 1:
                amount *= self.safe_run(lambda: self.exchange.fetchTicker('%s/%s' % (currency, thisCur)))['last']
            else:
                amount /= self.safe_run(lambda: self.exchange.fetchTicker('%s/%s' % (thisCur, currency)))['last']
            return amount, thisCur
        else:
            return amount, currency

    def delete_trade_set(self, iTs, sellAll=False):
        self.update_down_state(True)
        self.lock_trade_set(iTs)
        if sellAll:
            sold = self.sell_all_now(iTs)
        else:
            sold = True
            self.deactivate_trade_set(iTs, 1)
        if sold:
            self.create_trade_history_entry(iTs)
            self.tradeSets.pop(iTs)
        else:
            self.unlock_trade_set(iTs)

    def add_init_coins(self, iTs, init_coins=0, init_price=None):
        if self.check_num(init_coins, init_price) or (init_price is None and self.check_num(init_coins)):
            if init_price is not None and init_price < 0:
                init_price = None
            ts = self.tradeSets[iTs]
            # check if free balance is indeed sufficient
            bal = self.get_balance(ts['coinCurrency'])
            if bal is None:
                self.message('Free balance could not be determined as exchange does not support this! '
                             'If free balance does not suffice for initial coins there will be an error when trade set '
                             'is activated!',
                             'warning')
            elif bal < init_coins:
                self.message('Adding initial balance failed: %s %s requested but only %s %s are free!' % (
                    self.amount2Prec(ts['symbol'], init_coins), ts['coinCurrency'],
                    self.amount2Prec(ts['symbol'], self.get_balance(ts['coinCurrency'])), ts['coinCurrency']),
                             'error')
                return 0
            self.lock_trade_set(iTs)

            if ts['coinsAvail'] > 0 and ts['initPrice'] is not None:
                # remove old cost again
                ts['costIn'] -= (ts['coinsAvail'] * ts['initPrice'])
            ts['coinsAvail'] = init_coins
            ts['initCoins'] = init_coins

            ts['initPrice'] = init_price
            if init_price is not None:
                ts['costIn'] += (init_coins * init_price)
            self.unlock_trade_set(iTs)
            return 1
        else:
            raise ValueError('Some input was no number')

    def num_buy_levels(self, i_ts, order='all'):
        return self.get_trade_param(i_ts, 'amount', 'num', 'buy', order)

    def num_sell_levels(self, i_ts, order='all'):
        return self.get_trade_param(i_ts, 'amount', 'num', 'sell', order)

    def sum_buy_amounts(self, i_ts, order='all', subtract_fee=True):
        return self.get_trade_param(i_ts, 'amount', 'sum', 'buy', order, subtract_fee)

    def sum_sell_amounts(self, i_ts, order='all', subtract_fee=True):
        return self.get_trade_param(i_ts, 'amount', 'sum', 'sell', order, subtract_fee)

    def sum_buy_costs(self, i_ts, order='all', subtract_fee=True):
        return self.get_trade_param(i_ts, 'cost', 'sum', 'buy', order, subtract_fee)

    def sum_sell_costs(self, i_ts, order='all', subtract_fee=True):
        return self.get_trade_param(i_ts, 'cost', 'sum', 'sell', order, subtract_fee)

    def min_buy_price(self, i_ts, order='all'):
        return self.get_trade_param(i_ts, 'price', 'min', 'buy', order)

    def get_trade_param(self, iTs, what, method, direction, order='all', subtract_fee=True):
        if method == 'sum':
            func = lambda x: sum(x)
        elif method == 'min':
            func = lambda x: None if len(x) == 0 else np.min(x)
        elif method == 'max':
            func = lambda x: None if len(x) == 0 else np.max(x)
        elif method == 'mean':
            func = lambda x: None if len(x) == 0 else np.mean(x)
        elif method == 'num':
            func = lambda x: len(x)
        else:
            raise ValueError(f'Unknown method {method}')

        if direction == 'sell':
            trade = 'OutTrades'
        else:
            trade = 'InTrades'

        if order not in ['all', 'filled', 'open', 'notfilled', 'notinitiated']:
            raise ValueError('order has to be all, filled, notfilled, notinitiated or open')

        if what == 'amount':
            if order == 'all':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     self.tradeSets[iTs][trade]])
            elif order == 'filled':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     self.tradeSets[iTs][trade] if val['oid'] == 'filled'])
            elif order == 'open':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     self.tradeSets[iTs][trade] if val['oid'] != 'filled' and val['oid'] is not None])
            elif order == 'notinitiated':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     self.tradeSets[iTs][trade] if val['oid'] != 'filled' and val['oid'] is None])
            elif order == 'notfilled':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     self.tradeSets[iTs][trade] if val['oid'] != 'filled'])
        elif what == 'price':
            if order == 'all':
                return func([val['price'] for val in self.tradeSets[iTs][trade]])
            elif order == 'filled':
                return func([val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] == 'filled'])
            elif order == 'open':
                return func([val['price'] for val in self.tradeSets[iTs][trade] if
                             val['oid'] != 'filled' and val['oid'] is not None])
            elif order == 'notinitiated':
                return func([val['price'] for val in self.tradeSets[iTs][trade] if
                             val['oid'] != 'filled' and val['oid'] is None])
            elif order == 'notfilled':
                return func([val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled'])
        elif what == 'cost':
            if order == 'all':
                return func([val['amount'] * val['price'] for val in self.tradeSets[iTs][trade]])
            elif order == 'filled':
                return func(
                    [val['amount'] * val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] == 'filled'])
            elif order == 'open':
                return func([val['amount'] * val['price'] for val in self.tradeSets[iTs][trade] if
                             val['oid'] != 'filled' and val['oid'] is not None])
            elif order == 'notinitiated':
                return func([val['amount'] * val['price'] for val in self.tradeSets[iTs][trade] if
                             val['oid'] != 'filled' and val['oid'] is None])
            elif order == 'notfilled':
                return func(
                    [val['amount'] * val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled'])

    def add_buy_level(self, iTs, buyPrice, buyAmount, candleAbove=None):
        self.update_down_state(True)
        ts = self.tradeSets[iTs]
        if self.check_num(buyPrice, buyAmount, candleAbove) or (
                candleAbove is None and self.check_num(buyPrice, buyAmount)):
            fee = self.calculate_fee(ts['symbol'], 'limit', 'buy', buyAmount, buyPrice, 'maker')
            if not self.check_quantity(ts['symbol'], 'amount', buyAmount):
                self.message('Adding buy level failed, amount is not within the range, the exchange accepts', 'error')
                return 0
            elif not self.check_quantity(ts['symbol'], 'price', buyPrice):
                self.message('Adding buy level failed, price is not within the range, the exchange accepts', 'error')
                return 0
            elif not self.check_quantity(ts['symbol'], 'cost', buyPrice * buyAmount):
                self.message('Adding buy level failed, cost is not within the range, the exchange accepts', 'error')
                return 0
            bal = self.get_balance(ts['baseCurrency'])
            if bal is None:
                self.message('Free balance could not be determined as exchange does not support this! '
                             'If free balance does not suffice there will be an error when trade set is activated',
                             'warning')
            elif bal < buyAmount * buyPrice + (fee['cost'] if fee['currency'] == ts['baseCurrency'] else 0):
                self.message('Adding buy level failed, your balance of %s does not suffice to buy this amount%s!' % (
                    ts['baseCurrency'],
                    ' and pay the trading fee (%s %s)' % (
                    self.fee2Prec(ts['symbol'], fee['cost']), ts['baseCurrency']) if
                    fee['currency'] == ts['baseCurrency'] else ''), 'error')
                return 0

            bought_amount = buyAmount
            if fee['currency'] == ts['coinCurrency'] and \
                    (self.exchange.name.lower() != 'binance' or self.get_balance('BNB') < 0.5):
                # this is a hack, as fees on binance are deduced from BNB if this is activated and there is enough BNB,
                # however so far no API chance to see if this is the case. Here I assume that 0.5 BNB are enough to pay
                # the fee for the trade and thus the fee is not subtracted from the traded coin
                bought_amount -= fee['cost']
            self.lock_trade_set(iTs)
            wasactive = self.deactivate_trade_set(iTs)
            ts['InTrades'].append({'oid': None, 'price': buyPrice, 'amount': buyAmount, 'actualAmount': bought_amount,
                                   'candleAbove': candleAbove})
            if wasactive:
                self.activate_trade_set(iTs, False)
            self.unlock_trade_set(iTs)
            return self.num_buy_levels(iTs) - 1
        else:
            raise ValueError('Some input was no number')

    def delete_buy_level(self, iTs, iTrade):
        self.update_down_state(True)
        if self.check_num(iTrade):
            self.lock_trade_set(iTs)
            ts = self.tradeSets[iTs]
            wasactive = self.deactivate_trade_set(iTs)
            if ts['InTrades'][iTrade]['oid'] is not None and ts['InTrades'][iTrade]['oid'] != 'filled':
                self.cancel_buy_orders(iTs, ts['InTrades'][iTrade]['oid'])
            ts['InTrades'].pop(iTrade)
            if wasactive:
                self.activate_trade_set(iTs, False)
            self.unlock_trade_set(iTs)
        else:
            raise ValueError('Some input was no number')

    def set_buy_level(self, iTs, iTrade, price, amount):
        self.update_down_state(True)
        if self.check_num(iTrade, price, amount):
            ts = self.tradeSets[iTs]
            if ts['InTrades'][iTrade]['oid'] == 'filled':
                self.message('This order is already filled! No change possible')
                return 0
            else:
                fee = self.calculate_fee(ts['symbol'], 'limit', 'buy', amount, price, 'maker')
                if not self.check_quantity(ts['symbol'], 'amount', amount):
                    self.message('Changing buy level failed, amount is not within the range, the exchange accepts')
                    return 0
                elif not self.check_quantity(ts['symbol'], 'price', price):
                    self.message('Changing buy level failed, price is not within the range, the exchange accepts')
                    return 0
                elif not self.check_quantity(ts['symbol'], 'cost', price * amount):
                    self.message('Changing buy level failed, cost is not within the range, the exchange accepts')
                    return 0
                bal = self.get_balance(ts['baseCurrency'])
                if bal is None:
                    self.message('Free balance could not be determined as exchange does not support this! '
                                 'If free balance does not suffice there will be an error when trade set is activated',
                                 'warning')
                elif bal + ts['InTrades'][iTrade]['amount'] * ts['InTrades'][iTrade]['price'] < amount * price + \
                        fee['cost'] if fee['currency'] == ts['baseCurrency'] else 0:
                    self.message(
                        'Changing buy level failed, your balance of %s does not suffice to buy this amount%s!' % (
                            ts['baseCurrency'], ' and pay the trading fee (%s %s)' % (
                                self.fee2Prec(ts['symbol'], fee['cost']), ts['baseCurrency']) if fee['currency'] == ts[
                                'baseCurrency'] else ''))
                    return 0
                bought_amount = amount
                # this is a hack, as fees on binance are deduced from BNB if this is activated and there is enough BNB,
                # however so far no API chance to see if this is the case. Here I assume that 0.5 BNB are enough to pay
                # the fee for the trade and thus the fee is not subtracted from the traded coin
                if fee['currency'] == ts['coinCurrency'] and \
                        (self.exchange.name.lower() != 'binance' or self.get_balance('BNB') < 0.5):
                    bought_amount -= fee['cost']

                wasactive = self.deactivate_trade_set(iTs)

                if ts['InTrades'][iTrade]['oid'] is not None and ts['InTrades'][iTrade]['oid'] != 'filled':
                    returnVal = self.cancel_buy_orders(iTs, ts['InTrades'][iTrade]['oid'])
                    ts['InTrades'][iTrade]['oid'] = None
                    if returnVal == 0.5:
                        bal = self.get_balance(ts['baseCurrency'])
                        if bal is None:
                            self.message('Free balance could not be determined as exchange does not support this! If '
                                         'free balance does not suffice there will be an error on trade set activation',
                                         'warning')
                        elif bal + ts['InTrades'][iTrade]['amount'] * ts['InTrades'][iTrade]['price'] < amount * price \
                                + fee['cost'] if fee['currency'] == ts['baseCurrency'] else 0:
                            self.message(f"Changing buy level failed, your balance of {ts['baseCurrency']} does not "
                                         f"suffice to buy this amount%s!" % (
                                            f" and pay the trading fee ({self.fee2Prec(ts['symbol'], fee['cost'])} "
                                            f"{ts['baseCurrency']})" if fee['currency'] == ts['baseCurrency'] else ''))
                            return 0
                ts['InTrades'][iTrade].update({'amount': amount, 'actualAmount': bought_amount, 'price': price})

                if wasactive:
                    self.activate_trade_set(iTs, False)
                return 1
        else:
            raise ValueError('Some input was no number')

    def add_sell_level(self, iTs, sell_price, sell_amount):
        self.update_down_state(True)
        ts = self.tradeSets[iTs]
        if self.check_num(sell_price, sell_amount):
            if not self.check_quantity(ts['symbol'], 'amount', sell_amount):
                self.message('Adding sell level failed, amount is not within the range, the exchange accepts')
                return 0
            elif not self.check_quantity(ts['symbol'], 'price', sell_price):
                self.message('Adding sell level failed, price is not within the range, the exchange accepts')
                return 0
            elif not self.check_quantity(ts['symbol'], 'cost', sell_price * sell_amount):
                self.message('Adding sell level failed, return is not within the range, the exchange accepts')
                return 0
            self.lock_trade_set(iTs)
            wasactive = self.deactivate_trade_set(iTs)
            ts['OutTrades'].append({'oid': None, 'price': sell_price, 'amount': sell_amount})
            if wasactive:
                self.activate_trade_set(iTs, False)
            self.unlock_trade_set(iTs)
            return self.num_sell_levels(iTs) - 1
        else:
            raise ValueError('Some input was no number')

    def delete_sell_level(self, iTs, iTrade):
        self.update_down_state(True)
        if self.check_num(iTrade):
            self.lock_trade_set(iTs)
            ts = self.tradeSets[iTs]
            wasactive = self.deactivate_trade_set(iTs)
            if ts['OutTrades'][iTrade]['oid'] is not None and ts['OutTrades'][iTrade]['oid'] != 'filled':
                self.cancel_sell_orders(iTs, ts['OutTrades'][iTrade]['oid'])
            ts['OutTrades'].pop(iTrade)
            self.unlock_trade_set(iTs)
            if wasactive:
                self.activate_trade_set(iTs, False)
        else:
            raise ValueError('Some input was no number')

    def set_sell_level(self, iTs, iTrade, price, amount):
        self.update_down_state(True)
        if self.check_num(iTrade, price, amount):
            ts = self.tradeSets[iTs]
            if ts['OutTrades'][iTrade]['oid'] == 'filled':
                self.message('This order is already filled! No change possible')
                return 0
            else:
                if not self.check_quantity(ts['symbol'], 'amount', amount):
                    self.message('Changing sell level failed, amount is not within the range, the exchange accepts')
                    return 0
                elif not self.check_quantity(ts['symbol'], 'price', price):
                    self.message('Changing sell level failed, price is not within the range, the exchange accepts')
                    return 0
                elif not self.check_quantity(ts['symbol'], 'cost', price * amount):
                    self.message('Changing sell level failed, return is not within the range, the exchange accepts')
                    return 0
                wasactive = self.deactivate_trade_set(iTs)

                if ts['OutTrades'][iTrade]['oid'] is not None and ts['OutTrades'][iTrade]['oid'] != 'filled':
                    self.cancel_sell_orders(iTs, ts['OutTrades'][iTrade]['oid'])
                    ts['OutTrades'][iTrade]['oid'] = None

                ts['OutTrades'][iTrade]['amount'] = amount
                ts['OutTrades'][iTrade]['price'] = price

                if wasactive:
                    self.activate_trade_set(iTs, False)
                return 1
        else:
            raise ValueError('Some input was no number')

    def set_trailing_sl(self, iTs, value, typ='abs'):
        self.update_down_state(True)
        ts = self.tradeSets[iTs]
        if self.check_num(value):
            if self.num_buy_levels(iTs, 'notfilled') > 0:
                raise Exception('Trailing SL cannot be set as there are non-filled buy orders still')
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(ts['symbol']))
            if typ == 'abs':
                if value >= ticker['last'] or value <= 0:
                    raise ValueError('absolute trailing stop-loss offset is not between 0 and current price')
                newSL = ticker['last'] - value
            else:
                if value >= 1 or value <= 0:
                    raise ValueError('Relative trailing stop-loss offset is not between 0 and 1')
                newSL = ticker['last'] * (1 - value)
            ts['trailingSL'] = [value, typ]
            ts['SL'] = newSL
            self.set_daily_close_sl(iTs, None)
            self.set_weekly_close_sl(iTs, None)
        elif value is None:
            ts['trailingSL'] = [None, None]
        else:
            raise ValueError('Input was no number')

    def set_weekly_close_sl(self, iTs, value):
        ts = self.tradeSets[iTs]
        if self.check_num(value):
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(ts['symbol']))
            if ticker['last'] <= value:
                self.message('Weekly-close SL is set but be aware that it is higher than the current market price!',
                             'Warning')
            ts['weeklycloseSL'] = value
            self.set_daily_close_sl(iTs, None)
            self.set_trailing_sl(iTs, None)  # deactivate trailing SL
            self.set_sl(iTs, None)  # deactivate standard SL
        elif value is None:
            ts['weeklycloseSL'] = None
        else:
            raise ValueError('Input was no number')

    def set_daily_close_sl(self, iTs, value):
        ts = self.tradeSets[iTs]
        if self.check_num(value):
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(ts['symbol']))
            if ticker['last'] <= value:
                self.message('Daily-close SL is set but be aware that it is higher than the current market price!',
                             'Warning')
            ts['dailycloseSL'] = value
            self.set_weekly_close_sl(iTs, None)
            self.set_trailing_sl(iTs, None)  # deactivate trailing SL
            self.set_sl(iTs, None)  # deactivate standard SL
        elif value is None:
            ts['dailycloseSL'] = None
        else:
            raise ValueError('Input was no number')

    def set_sl(self, iTs, value):
        if self.check_num(value):
            ts = self.tradeSets[iTs]
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(ts['symbol']))
            if ticker['last'] <= value:
                self.message('Cannot set new SL as it is higher than the current market price')
                return 0
            self.set_trailing_sl(iTs, None)  # deactivate trailing SL
            self.set_daily_close_sl(iTs, None)  # same for dailyclose SL
            self.set_weekly_close_sl(iTs, None)  # same for weeklycloseSL SL
            self.tradeSets[iTs]['SL'] = value
            return 1
        elif value is None:
            self.tradeSets[iTs]['SL'] = None
            return 1
        else:
            raise ValueError('Input was no number')

    def set_sl_break_even(self, iTs):
        self.update_down_state(True)
        ts = self.tradeSets[iTs]
        if ts['initCoins'] > 0 and ts['initPrice'] is None:
            self.message(f"Break even SL cannot be set as you this trade set contains {ts['coinCurrency']} that you "
                         f"obtained beforehand and no buy price information was given.")
            return 0
        elif ts['costOut'] - ts['costIn'] > 0:
            self.message(
                'Break even SL cannot be set as your sold coins of this trade already outweigh your buy expenses '
                '(congrats!)! You might choose to sell everything immediately if this is what you want.')
            return 0
        elif ts['costOut'] - ts['costIn'] == 0:
            self.message('Break even SL cannot be set as there are no unsold %s coins right now' % ts['coinCurrency'])
            return 0
        else:
            breakEvenPrice = (ts['costIn'] - ts['costOut']) / ((1 - self.exchange.fees['trading']['taker']) * (
                    ts['coinsAvail'] + sum([trade['amount'] for trade in ts['OutTrades'] if
                                            trade['oid'] != 'filled' and trade['oid'] is not None])))
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(ts['symbol']))
            if ticker['last'] < breakEvenPrice:
                self.message('Break even SL of %s cannot be set as the current market price is lower (%s)!' % tuple(
                    [self.price2Prec(ts['symbol'], val) for val in [breakEvenPrice, ticker['last']]]))
                return 0
            else:
                self.set_sl(iTs, breakEvenPrice)
                return 1

    def sell_free_bal(self, ts) -> Union[None, dict]:
        free_bal = self.get_balance(ts['coinCurrency'])
        if free_bal is None:
            self.message(f"When selling {ts['symbol']}, exchange reported insufficient funds and does not allow to "
                         f"determine free balance of {ts['coinCurrency']}, thus nothing could be sold automatically! "
                         f"Please sell manually!", 'error')
            return None
        elif free_bal == 0:
            self.message(f"When selling {ts['symbol']}, exchange reported insufficient funds. Please sell manually!",
                         'error')
            return None
        else:
            try:
                response = self.safe_run(lambda: self.exchange.createMarketSellOrder(ts['symbol'], free_bal), False)
            except Exception:
                self.message('There was an error selling %s! Please sell manually!' % (ts['symbol']), 'warning')
                return None
            self.message('When selling %s, only %s %s was found and sold!' % (
                ts['symbol'], self.amount2Prec(ts['symbol'], free_bal), ts['coinCurrency']), 'warning')
            return response

    def sell_all_now(self, iTs, price=None):
        self.update_down_state(True)
        self.deactivate_trade_set(iTs, 2)
        ts = self.tradeSets[iTs]
        ts['SL'] = None  # necessary to not retrigger SL
        ts['dailycloseSL'] = None  # this one, too
        sold = True
        if ts['coinsAvail'] > 0 and self.check_quantity(ts['symbol'], 'amount', ts['coinsAvail']):
            if self.exchange.has['createMarketOrder']:
                try:
                    response = self.safe_run(
                        lambda: self.exchange.createMarketSellOrder(ts['symbol'], ts['coinsAvail']),
                        False)
                except InsufficientFunds:
                    response = self.sell_free_bal(ts)
                except:
                    params = {'trading_agreement': 'agree'}  # for kraken api...
                    try:
                        response = self.safe_run(
                            lambda: self.exchange.createMarketSellOrder(ts['symbol'], ts['coinsAvail'], params),
                            iTs=iTs)
                    except InsufficientFunds:
                        response = self.sell_free_bal(ts)
            else:
                if price is None:
                    price = self.safe_run(lambda: self.exchange.fetch_ticker(ts['symbol'])['last'], iTs=iTs)
                try:
                    response = self.safe_run(
                        lambda: self.exchange.createLimitSellOrder(ts['symbol'], ts['coinsAvail'], price * 0.995),
                        iTs=iTs)
                except InsufficientFunds:
                    response = self.sell_free_bal(ts)
            if response is not None:
                time.sleep(5)  # give exchange 5 sec for trading the order
                orderInfo = self.fetch_order(response['id'], iTs, 'SELL')

                if orderInfo['status'] == 'FILLED':
                    if orderInfo['type'] == 'market' and self.exchange.has['fetchMyTrades'] is not False:
                        trades = self.exchange.fetchMyTrades(ts['symbol'])
                        orderInfo['cost'] = sum([tr['cost'] for tr in trades if tr['order'] == orderInfo['id']])
                        orderInfo['price'] = np.mean([tr['price'] for tr in trades if tr['order'] == orderInfo['id']])
                    ts['costOut'] += orderInfo['cost']
                    self.message('Sold immediately at a price of %s %s: Sold %s %s for %s %s.' % (
                        self.price2Prec(ts['symbol'], orderInfo['price']), ts['symbol'],
                        self.amount2Prec(ts['symbol'], orderInfo['amount']), ts['coinCurrency'],
                        self.cost2Prec(ts['symbol'], orderInfo['cost']), ts['baseCurrency']))
                else:
                    self.message('Sell order was not traded immediately, updating status soon.')
                    sold = False
                    ts['OutTrades'].append(
                        {'oid': response['id'], 'price': orderInfo['price'], 'amount': orderInfo['amount']})
                    self.activate_trade_set(iTs, False)
            else:
                sold = False
        else:
            self.message('No coins (or too low amount) to sell from this trade set.', 'warning')
        return sold

    def cancel_sell_orders(self, iTs, oid=None, delete_orders=False):
        self.update_down_state(True)
        return_val = 1
        if iTs in self.tradeSets and self.num_sell_levels(iTs) > 0:
            count = 0
            for iTrade, trade in reversed(list(enumerate(self.tradeSets[iTs]['OutTrades']))):
                if oid is None or trade['oid'] == oid:
                    if trade['oid'] is not None and trade['oid'] != 'filled':
                        try:
                            self.cancel_order(trade['oid'], iTs, 'SELL')
                        except OrderNotFound as e:
                            pass
                        except Exception as e:
                            self.unlock_trade_set(iTs)
                            raise (e)
                        time.sleep(1)
                        count += 1
                        orderInfo = self.fetch_order(trade['oid'], iTs, 'SELL')
                        self.tradeSets[iTs]['coinsAvail'] += trade['amount']
                        if orderInfo['filled'] > 0:
                            self.message('(Partly?) filled sell order found during canceling. Updating balance')
                            self.tradeSets[iTs]['costOut'] += orderInfo['price'] * orderInfo['filled']
                            self.tradeSets[iTs]['coinsAvail'] -= orderInfo['filled']
                            trade['oid'] = 'filled'
                            trade['amount'] = orderInfo['filled']
                            return_val = 0.5
                        else:
                            trade['oid'] = None
                    if delete_orders:
                        if trade['oid'] != 'filled':
                            self.tradeSets[iTs]['OutTrades'].pop(iTrade)
            if count > 0:
                self.message('%d sell orders canceled in total for tradeSet %d (%s)' % (
                    count, list(self.tradeSets.keys()).index(iTs), self.tradeSets[iTs]['symbol']))
        return return_val

    def cancel_buy_orders(self, iTs, oid=None, deleteOrders=False):
        self.update_down_state(True)
        return_val = 1
        if iTs in self.tradeSets and self.num_buy_levels(iTs) > 0:
            count = 0
            for iTrade, trade in reversed(list(enumerate(self.tradeSets[iTs]['InTrades']))):
                if oid is None or trade['oid'] == oid:
                    if trade['oid'] is not None and trade['oid'] != 'filled':
                        try:
                            self.cancel_order(trade['oid'], iTs, 'BUY')
                        except OrderNotFound as e:
                            pass

                        time.sleep(1)
                        count += 1
                        orderInfo = self.fetch_order(trade['oid'], iTs, 'BUY')
                        if orderInfo['filled'] > 0:
                            self.message('(Partly?) filled buy order found during canceling. Updating balance')
                            self.tradeSets[iTs]['costIn'] += orderInfo['price'] * orderInfo['filled']
                            self.tradeSets[iTs]['coinsAvail'] += orderInfo['filled']
                            trade['oid'] = 'filled'
                            trade['amount'] = orderInfo['filled']
                            return_val = 0.5
                        else:
                            trade['oid'] = None
                    if deleteOrders:
                        if trade['oid'] != 'filled':
                            self.tradeSets[iTs]['InTrades'].pop(iTrade)
            if count > 0:
                self.message('%d buy orders canceled in total for tradeSet %d (%s)' % (
                    count, list(self.tradeSets.keys()).index(iTs), self.tradeSets[iTs]['symbol']))
        return return_val

    def init_buy_orders(self, iTs):
        self.update_down_state(True)
        if self.tradeSets[iTs]['active']:
            # initialize buy orders
            for iTrade, trade in enumerate(self.tradeSets[iTs]['InTrades']):
                if trade['oid'] is None and trade['candleAbove'] is None:
                    try:
                        response = self.safe_run(
                            lambda: self.exchange.createLimitBuyOrder(self.tradeSets[iTs]['symbol'], trade['amount'],
                                                                      trade['price']))
                    except InsufficientFunds as e:
                        self.deactivate_trade_set(iTs)
                        self.message(f"Insufficient funds on exchange {self.exchange.name} for trade set "
                                     f"#{self.exchange.name}. Trade set is deactivated now and not updated anymore "
                                     f"(open orders are still open)! Free the missing funds and reactivate. \n {e}.",
                                     'error')
                        raise (e)
                    self.tradeSets[iTs]['InTrades'][iTrade]['oid'] = response['id']

    def cancel_order(self, oid, iTs, typ):
        self.update_down_state(True)
        symbol = self.tradeSets[iTs]['symbol']
        try:
            return self.safe_run(lambda: self.exchange.cancel_order(oid, symbol), False)
        except OrderNotFound as e:
            self.unlock_trade_set(iTs)
            raise (e)
        except ccxt.ExchangeError:
            return self.safe_run(lambda: self.exchange.cancel_order(oid, symbol, {'type': typ}), iTs=iTs)

    def fetch_order(self, oid, iTs, typ):
        symbol = self.tradeSets[iTs]['symbol']
        try:
            return self.safe_run(lambda: self.exchange.fetch_order(oid, symbol), False)
        except OrderNotFound as e:
            self.unlock_trade_set(iTs)
            raise (e)
        except ccxt.ExchangeError:
            return self.safe_run(lambda: self.exchange.fetch_order(oid, symbol, {'type': typ}), iTs=iTs)

    def update_down_state(self, raiseError=False):
        if self.down:
            self.safe_run(self.exchange.loadMarkets, print_error=False)
            if raiseError:
                raise ccxt.ExchangeError('Exchange is down!')
            return self.down
        else:
            return False

    def update(self, special_check=0):
        # goes through all trade sets and checks/updates the buy/sell/stop loss orders
        # daily check is for checking if a candle closed above a certain value
        if not special_check:
            # fix for accumulating update jobs if update interval is set too small
            if (time.time() - self.lastUpdate) < 1:
                return None

        if self.update_down_state():
            # check if exchange is still down, if yes, return
            return
        else:
            try:
                self.update_balance()
            except AuthenticationError:  #
                self.message('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                             'error')
                return
            except ccxt.ExchangeError as e:  #
                if 'key' in str(e).lower():
                    self.message('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                                 'error')
                else:
                    self.down = True
                    self.message('Some error occured at exchange %s. Maybe it is down.' % self.exchange.name, 'error')
                return

        trade_sets_to_delete = []
        try:
            if special_check != 2:
                if self.exchange.has['fetchTickers']:
                    tickers = self.safe_run(self.exchange.fetchTickers)
                    func = lambda sym, iTs: tickers[sym] if sym in tickers else self.safe_run(
                        lambda: self.exchange.fetchTicker(sym), iTs=iTs)  # includes a hot fix for some ccxt problems
                else:
                    func = lambda sym, iTs: self.safe_run(lambda: self.exchange.fetchTicker(sym), iTs=iTs)

            for indTs, iTs in enumerate(self.tradeSets):
                try:
                    ts = self.tradeSets[iTs]
                    if not ts['active']:
                        continue
                    self.lock_trade_set(iTs)
                    if special_check != 2:
                        ticker = func(ts['symbol'], iTs=iTs)
                    # check if stop loss is reached
                    if not special_check:
                        if ts['SL'] is not None:
                            if ticker['last'] <= ts['SL']:
                                self.message('Stop loss for pair %s has been triggered!' % ts['symbol'], 'warning')
                                # cancel all sell orders, create market sell order, save resulting amount of currency
                                sold = self.sell_all_now(iTs, price=ticker['last'])
                                if sold:
                                    trade_sets_to_delete.append(iTs)
                                    self.unlock_trade_set(iTs)
                                    continue
                            elif 'trailingSL' in ts and ts['trailingSL'][0] is not None:
                                if ts['trailingSL'][1] == 'abs':
                                    newSL = ticker['last'] - ts['trailingSL'][0]
                                else:
                                    newSL = ticker['last'] * (1 - ts['trailingSL'][0])
                                if newSL > ts['SL']:
                                    ts['SL'] = newSL
                    elif special_check == 1:
                        if 'dailycloseSL' in ts and ts['dailycloseSL'] is not None and ticker['last'] < ts[
                             'dailycloseSL']:
                            self.message('Daily candle closed below chosen SL of %s for pair %s! Selling now!' % (
                                self.price2Prec(ts['symbol'], ts['dailycloseSL']), ts['symbol']), 'warning')
                            # cancel all sell orders, create market sell order & save resulting amount of base currency
                            sold = self.sell_all_now(iTs, price=ticker['last'])
                            if sold:
                                trade_sets_to_delete.append(iTs)
                                self.unlock_trade_set(iTs)
                                continue
                        if datetime.date.today().weekday() == 0 and 'weeklycloseSL' in ts and ts[
                            'weeklycloseSL'] is not None and ticker['last'] < ts['weeklycloseSL']:
                            self.message('Weekly candle closed below chosen SL of %s for pair %s! Selling now!' % (
                                self.price2Prec(ts['symbol'], ts['weeklycloseSL']), ts['symbol']), 'warning')
                            # cancel all sell orders, create market sell order & save resulting amount of base currency
                            sold = self.sell_all_now(iTs, price=ticker['last'])
                            if sold:
                                trade_sets_to_delete.append(iTs)
                                self.unlock_trade_set(iTs)
                                continue
                    elif special_check == 2:  # tax warning check
                        for iTrade, trade in enumerate(ts['InTrades']):
                            if 'time' in trade and (datetime.datetime.now() - trade['time']).days > 358 and (
                                    datetime.datetime.now() - trade['time']).days < 365:
                                self.message(
                                    f"Time since buy level #{iTrade} of trade set {indTs} ({ts['symbol']}) on exchange "
                                    f"{self.exchange.name} was filled approaches one year "
                                    f"({(trade['time'] + datetime.timedelta(days=365)).strftime('%Y-%m-%d %H:%M')}) "
                                    f"after which gains/losses are not eligible for reporting in the tax report in most"
                                    f" countries!", 'warning')
                        continue
                    order_executed = 0
                    # go through buy trades 
                    for iTrade, trade in enumerate(ts['InTrades']):
                        if trade['oid'] == 'filled':
                            continue
                        elif special_check == 1 and trade['oid'] is None and trade['candleAbove'] is not None:
                            if ticker['last'] > trade['candleAbove']:
                                response = self.safe_run(
                                    lambda: self.exchange.createLimitBuyOrder(ts['symbol'], trade['amount'],
                                                                              trade['price']), iTs=iTs)
                                ts['InTrades'][iTrade]['oid'] = response['id']
                                self.message('Daily candle of %s above %s triggering buy level #%d on %s!' % (
                                    ts['symbol'], self.price2Prec(ts['symbol'], trade['candleAbove']), iTrade,
                                    self.exchange.name))
                        elif trade['oid'] is not None:
                            try:
                                orderInfo = self.fetch_order(trade['oid'], iTs, 'BUY')
                                # fetch trades for all orders because a limit order might also be filled at a lower val
                                if orderInfo['status'].lower() in ['closed', 'filled', 'canceled'] and \
                                        self.exchange.has['fetchMyTrades'] != False:
                                    trades = self.exchange.fetchMyTrades(ts['symbol'])
                                    orderInfo['cost'] = sum(
                                        [tr['cost'] for tr in trades if tr['order'] == orderInfo['id']])
                                    if orderInfo['cost'] == 0:
                                        orderInfo['price'] = None
                                    else:
                                        orderInfo['price'] = np.mean(
                                            [tr['price'] for tr in trades if tr['order'] == orderInfo['id']])
                                else:
                                    trades = None
                                if orderInfo['status'].lower() in ['closed', 'filled']:
                                    order_executed = 1
                                    ts['InTrades'][iTrade]['oid'] = 'filled'
                                    ts['InTrades'][iTrade]['time'] = datetime.datetime.now()
                                    ts['InTrades'][iTrade]['price'] = orderInfo['price']
                                    ts['costIn'] += orderInfo['cost']
                                    self.message('Buy level of %s %s reached on %s! Bought %s %s for %s %s.' % (
                                        self.price2Prec(ts['symbol'], orderInfo['price']), ts['symbol'],
                                        self.exchange.name,
                                        self.amount2Prec(ts['symbol'], orderInfo['amount']), ts['coinCurrency'],
                                        self.cost2Prec(ts['symbol'], orderInfo['cost']), ts['baseCurrency']))
                                    ts['coinsAvail'] += trade['actualAmount']
                                elif orderInfo['status'] == 'canceled':
                                    if 'reason' in orderInfo['info']:
                                        reason = orderInfo['info']['reason']
                                    else:
                                        reason = 'N/A'
                                    cancel_msg = f"Buy order (level {iTrade} of trade set " \
                                        f"{list(self.tradeSets.keys()).index(iTs)} on {self.exchange.name}) was " \
                                        f"canceled by exchange or someone else (reason: {reason}) "
                                    if orderInfo['cost'] > 0:
                                        ts['InTrades'][iTrade]['oid'] = 'filled'
                                        ts['InTrades'][iTrade]['price'] = orderInfo['price']
                                        ts['costIn'] += orderInfo['cost']
                                        if trades is not None:
                                            orderInfo['amount'] = sum(
                                                [tr['amount'] for tr in trades if tr['order'] == orderInfo['id']])
                                        ts['coinsAvail'] += orderInfo['amount']
                                        self.message(cancel_msg + 'but already partly filled! Treating '
                                                                  'order as closed and updating trade set info.',
                                                     'error')
                                    else:
                                        ts['InTrades'][iTrade]['oid'] = None
                                        self.message(cancel_msg + 'Will be reinitialized during next update.', 'error')

                            except OrderNotFound as e:
                                self.lock_trade_set(iTs)
                                self.message(
                                    f"Buy order id {ts['InTrades'][iTrade]['oid']} for trade set {ts['symbol']} not "
                                    f"found on {self.exchange.name}! Maybe exchange API has changed? Resetting order to"
                                    f" 'not initiated', will be initiated on next trade set update!", 'error')
                                ts['InTrades'][iTrade]['oid'] = None

                        else:
                            self.init_buy_orders(iTs)
                            time.sleep(1)

                    if not special_check:
                        # go through all selling positions and create those for which the bought coins suffice
                        for iTrade, _ in enumerate(ts['OutTrades']):
                            if ts['OutTrades'][iTrade]['oid'] is None and ts['coinsAvail'] >= \
                                    ts['OutTrades'][iTrade]['amount']:
                                try:
                                    response = self.safe_run(lambda: self.exchange.createLimitSellOrder(ts['symbol'],
                                                                                                        ts['OutTrades'][
                                                                                                            iTrade][
                                                                                                            'amount'],
                                                                                                        ts['OutTrades'][
                                                                                                            iTrade][
                                                                                                            'price']),
                                                             iTs=iTs)
                                except InsufficientFunds as e:
                                    self.deactivate_trade_set(iTs)
                                    self.message(f"Insufficient funds on exchange {self.exchange.name} for trade set "
                                                 f"#{list(self.tradeSets.keys()).index(iTs)}. Trade set is deactivated "
                                                 f"now and not updated anymore (open orders are still open)! "
                                                 f"Free the missing funds and reactivate. \n {e}."
                                                 'error')

                                    raise (e)
                                ts['OutTrades'][iTrade]['oid'] = response['id']
                                ts['coinsAvail'] -= ts['OutTrades'][iTrade]['amount']
                        # go through sell trades 
                        for iTrade, trade in enumerate(ts['OutTrades']):
                            if trade['oid'] == 'filled':
                                continue
                            elif trade['oid'] is not None:
                                try:
                                    orderInfo = self.fetch_order(trade['oid'], iTs, 'SELL')
                                    # fetch trades for all orders as a limit order might also be filled at a higher val
                                    if self.exchange.has['fetchMyTrades'] != False:
                                        trades = self.exchange.fetchMyTrades(ts['symbol'])
                                        orderInfo['cost'] = sum(
                                            [tr['cost'] for tr in trades if tr['order'] == orderInfo['id']])
                                        if orderInfo['cost'] == 0:
                                            orderInfo['price'] = None
                                        else:
                                            orderInfo['price'] = np.mean(
                                                [tr['price'] for tr in trades if tr['order'] == orderInfo['id']])
                                    else:
                                        trades = None
                                    if any([orderInfo['status'].lower() == val for val in ['closed', 'filled']]):
                                        order_executed = 2
                                        ts['OutTrades'][iTrade]['oid'] = 'filled'
                                        ts['OutTrades'][iTrade]['time'] = datetime.datetime.now()
                                        ts['OutTrades'][iTrade]['price'] = orderInfo['price']
                                        ts['costOut'] += orderInfo['cost']
                                        self.message('Sell level of %s %s reached on %s! Sold %s %s for %s %s.' % (
                                            self.price2Prec(ts['symbol'], orderInfo['price']), ts['symbol'],
                                            self.exchange.name, self.amount2Prec(ts['symbol'], orderInfo['amount']),
                                            ts['coinCurrency'], self.cost2Prec(ts['symbol'], orderInfo['cost']),
                                            ts['baseCurrency']))
                                    elif orderInfo['status'] == 'canceled':
                                        if 'reason' in orderInfo['info']:
                                            reason = orderInfo['info']['reason']
                                        else:
                                            reason = 'N/A'
                                        if orderInfo['cost'] > 0:
                                            ts['OutTrades'][iTrade]['oid'] = 'filled'
                                            ts['OutTrades'][iTrade]['price'] = orderInfo['price']
                                            ts['costOut'] += orderInfo['cost']
                                            if trades is not None:
                                                orderInfo['amount'] = sum(
                                                    [tr['amount'] for tr in trades if tr['order'] == orderInfo['id']])
                                            ts['coinsAvail'] += ts['OutTrades'][iTrade]['amount'] - orderInfo['amount']
                                            self.message(
                                                f"Sell order (level {iTrade} of trade set "
                                                f"{list(self.tradeSets.keys()).index(iTs)} on {self.exchange.name}) was"
                                                f" canceled by exchange or someone else (reason: {reason}) but already "
                                                f"partly filled! Treating order as closed and updating trade set info.")
                                        else:
                                            ts['OutTrades'][iTrade]['oid'] = None
                                            ts['coinsAvail'] += ts['OutTrades'][iTrade]['amount']
                                            self.message(
                                                f"Sell order (level {iTrade} of trade set "
                                                f"{list(self.tradeSets.keys()).index(iTs)} on {self.exchange.name}) was"
                                                f" canceled by exchange or someone else (reason:{reason})! "
                                                f"Will be reinitialized during next update.")

                                except OrderNotFound as e:
                                    self.lock_trade_set(iTs)
                                    self.message(
                                        f"Sell order id {ts['OutTrades'][iTrade]['oid']} for trade set {ts['symbol']} "
                                        f"not found on {self.exchange.name}! Maybe exchange API has changed? "
                                        f"Resetting order to 'not initiated'! If InsufficientFunds errors pop up, the "
                                        f"order had probably been executed. In this case please delete the trade set.",
                                        'error')
                                    ts['coinsAvail'] += ts['OutTrades'][iTrade]['amount']
                                    ts['OutTrades'][iTrade]['oid'] = None

                        # delete Tradeset when all orders have been filled (but only if there were any to execute
                        # and if no significant coin amount is left)
                        if not (self.num_buy_levels(iTs, order='filled') + ts['initCoins']):
                            significant_amount = np.inf
                        else:
                            significant_amount = (self.sum_buy_amounts(iTs, order='filled') + ts['initCoins'] -
                                                  self.sum_sell_amounts(iTs, order='filled')) / \
                                                 (ts['initCoins'] + self.sum_buy_amounts(iTs, order='filled'))
                        if ((ts['SL'] is None and order_executed > 0) or (order_executed == 2 and
                            significant_amount < 0.01)) and self.num_sell_levels(
                            iTs, 'notfilled') == 0 and self.num_buy_levels(iTs, 'notfilled') == 0:
                            gain = self.cost2Prec(ts['symbol'], ts['costOut'] - ts['costIn'])
                            self.message('Trading set %s on %s completed! Total gain: %s %s' % (
                                ts['symbol'], self.exchange.name, gain, ts['baseCurrency']))
                            trade_sets_to_delete.append(iTs)
                finally:
                    self.unlock_trade_set(iTs)
        finally:
            # makes sure that the tradeSet deletion takes place even if some error occurred in another trade
            for iTs in trade_sets_to_delete:
                self.create_trade_history_entry(iTs)
                self.tradeSets.pop(iTs)
            self.lastUpdate = time.time()
