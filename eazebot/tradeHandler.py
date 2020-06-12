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
from enum import Flag, auto


class SLType(Flag):
    DEFAULT = auto()
    TRAILING = auto()
    DAILYCLOSE = auto()
    WEEKLYCLOSE = auto()


class ValueType(Flag):
    ABSOLUTE = auto()
    RELATIVE = auto()


class Price:
    def __init__(self, current: float, price_time: datetime.datetime = None, high: float = None, low: float = None):
        self.current_price = current
        self.high_price = high
        self.low_price = low
        if price_time is None:
            price_time = datetime.datetime.now()
        self.time = price_time

    def set_price(self, current: float, price_time: datetime.datetime = None, high: float = None, low: float = None):
        self.current_price = current
        self.high_price = high
        self.low_price = low
        if price_time is None:
            price_time = datetime.datetime.now()
        self.time = price_time

    def get_current_price(self):
        return self.current_price

    def get_high_price(self):
        return self.high_price

    def get_low_price(self):
        return self.low_price


class BaseSL:
    def __init__(self, value: float):
        self.value = value

    def set_value(self, value: float):
        self.value = value

    def is_below(self, price_obj) -> bool:
        return price_obj.get_current_price() < self.value


class DailyCloseSL(BaseSL):
    def is_below(self, price_obj) -> bool:
        end = datetime.datetime.combine(datetime.date.today(), datetime.time(0, 1, 0))
        begin = end - datetime.timedelta(minutes=2)
        return super().is_below(price_obj) and begin < price_obj.time < end


class WeeklyCloseSL(BaseSL):
    def is_below(self, price_obj) -> bool:
        end = datetime.datetime.combine(datetime.date.today(), datetime.time(0, 1, 0))
        begin = end - datetime.timedelta(minutes=2)
        is_monday = datetime.date.today().weekday() == 0
        return is_monday and super().is_below(price_obj) and begin < price_obj.time < end


class TrailingSL(BaseSL):
    def __init__(self, delta: float, kind: ValueType, price_obj: Union[Price, None] = None):
        self.kind = kind
        self.delta = delta
        super().__init__(value=0)
        if price_obj is not None:
            self.calculate_new_value(price_obj)

    def calculate_new_value(self, price_obj):
        if self.kind == ValueType.ABSOLUTE:
            if self.delta >= price_obj.current_price or self.delta <= 0:
                raise ValueError('Absolute trailing stop-loss offset is not between 0 and current price')
            new_value = price_obj.current_price - self.delta
        else:
            if self.delta >= 1 or self.delta <= 0:
                raise ValueError('Relative trailing stop-loss offset is not between 0 and 1')
            new_value = price_obj.current_price * (1 - self.delta)
        if new_value > self.value:
            self.set_value(new_value)

    def is_below(self, price_obj) -> bool:
        self.calculate_new_value(price_obj)
        return super().is_below(price_obj)


class BaseTradeSet:
    # 'symbol', 'InTrades', 'createdAt', 'OutTrades', 'baseCurrency', 'coinCurrency', 'costIn', 'costOut', 'coinsAvail',
    # 'initCoins', 'initPrice', 'SL', 'trailingSL', 'dailycloseSL', 'weeklycloseSL', 'active', 'virgin', 'updating',
    # 'waiting'
    def __init__(self, symbol: str, uid: str = None):
        if uid is None:
            random.seed()
            uid = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))

        self._uid = uid
        self.InTrades = []
        self.OutTrades = []
        self.createdAt = time.time()

        self.symbol = symbol
        self.baseCurrency = re.search("(?<=/).*", symbol).group(0)
        self.coinCurrency = re.search(".*(?=/)", symbol).group(0)
        self.costIn = 0
        self.costOut = 0
        self.coinsAvail = 0
        self.initCoins = 0
        self.initPrice = None
        self.SL = None
        self.active = False
        self.virgin = True
        self.updating = False
        self.waiting = []

    def get_uid(self):
        return self._uid


class tradeHandler:

    def __init__(self, exch_name, key=None, secret=None, password=None, uid=None, messager_fct=None, logger=None):
        # use either the given messager function or define a simple print messager function which takes a level
        # argument as second optional input
        try:
            self.message = self.update_messager_fct(messager_fct)
        except TypeError:
            self.message = lambda a, b='Info': print(b + ': ' + a)

        self.logger = logger
        check_these = ['cancelOrder', 'createLimitOrder', 'fetchBalance', 'fetchTicker']
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

        self.price_dict = {}
        self.updating = False
        self.waiting = []
        self.down = False
        self.authenticated = False
        self.balance = {}
        if key:
            self.update_keys(key, secret, password, uid)

        if not all([self.exchange.has[x] for x in check_these]):
            text = 'Exchange %s does not support all required features (%s)' % (exch_name, ', '.join(check_these))
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
        for i_ts in state:  # temp fix for old trade sets that do not some of the newer fields
            if not isinstance(state[i_ts], BaseTradeSet):
                ts = BaseTradeSet(symbol=state[i_ts]['symbol'], uid=i_ts)
                for key in state[i_ts]:
                    if key == 'SL':
                        if state[i_ts]['trailingSL'] != [None, None]:
                            sl = TrailingSL(state[i_ts]['trailingSL'][0],
                                            ValueType.ABSOLUTE if state[i_ts]['trailingSL'][1] == 'abs'
                                            else ValueType.RELATIVE)
                        elif state[i_ts]['weeklycloseSL'] is not None:
                            sl = WeeklyCloseSL(value=state[i_ts]['dailycloseSL'])
                        elif state[i_ts]['dailycloseSL'] is not None:
                            sl = DailyCloseSL(value=state[i_ts]['dailycloseSL'])
                        elif state[i_ts]['SL'] is not None:
                            sl = BaseSL(value=state[i_ts]['SL'])
                        else:
                            sl = None
                        ts.SL = sl
                    elif key in ['trailingSL', 'dailycloseSL', 'weeklycloseSL', 'waiting', 'updating',
                                 'noUpdateAfterEdit', 'uid']:
                        # SLs are handled above, waiting and updating should not be used from a saved trade set
                        continue
                    elif hasattr(ts, key):
                        setattr(ts, key, state[i_ts][key])
                    else:
                        raise Exception()
                state[i_ts] = ts
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
    def strip_zeros(stri):
        if '.' in stri:
            return stri.rstrip('0').rstrip('.')
        else:
            return stri

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

    def safe_run(self, func, print_error=True, i_ts=None):
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
                    if i_ts:
                        self.unlock_trade_set(i_ts)
                    if 'Cloudflare' in str(e):
                        if print_error:
                            self.message('Cloudflare problem with exchange %s. Exchange is treated as down. %s' % (
                                self.exchange.name, '' if i_ts is None else 'TradeSet %d (%s)' % (
                                    list(self.tradeSets.keys()).index(i_ts), self.tradeSets[i_ts].symbol)), 'Error')
                    elif print_error:
                        self.message('Network exception occurred 5 times in a row. %s is treated as down. %s' % (
                            self.exchange.name, '' if i_ts is None else 'TradeSet %d (%s)' % (
                                list(self.tradeSets.keys()).index(i_ts), self.tradeSets[i_ts].symbol)), 'Error')
                    raise e
                else:
                    time.sleep(0.5)
                    continue
            except OrderNotFound as e:
                count += 1
                if count >= 5:
                    if i_ts:
                        self.unlock_trade_set(i_ts)
                    if print_error:
                        self.message(f"Order not found error 5 times in a row on {self.exchange.name}"
                                     '' if i_ts is None else
                                     f" for tradeSet {list(self.tradeSets.keys()).index(i_ts)} "
                                     f"({self.tradeSets[i_ts].symbol}",
                                     'Error')
                    raise e
                else:
                    time.sleep(0.5)
                    continue
            except AuthenticationError as e:
                count += 1
                if count >= 5:
                    if i_ts:
                        self.unlock_trade_set(i_ts)
                    raise e
                else:
                    time.sleep(0.5)
                    continue
            except JSONDecodeError as e:
                if i_ts:
                    self.unlock_trade_set(i_ts)
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
                    if i_ts:
                        self.unlock_trade_set(i_ts)
                    stri = 'Exchange %s\n' % self.exchange.name
                    if count >= 5:
                        stri += 'Network exception occurred 5 times in a row! Last error was:\n'
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    # fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    lines = getsourcelines(func)
                    stri += '%s in %s from %s at line %d: %s' % (
                        exc_type, lines[0][0], os.path.basename(getsourcefile(func)), lines[1], str(e))

                    if print_error:
                        self.message(stri, 'Error')
                    raise e
            finally:
                if wasdown and not self.down:
                    self.message('Exchange %s seems back to work!' % self.exchange.name)

    def get_price_obj(self, symbol: str):
        if symbol not in self.price_dict:
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(symbol))
            self.price_dict[symbol] = Price(current=ticker['last'], high=ticker['high'], low=ticker['low'])
        elif (datetime.datetime.now() - self.price_dict[symbol].time).seconds > 5:
            # update price
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(symbol))
            self.price_dict[symbol].set_price(current=ticker['last'], high=ticker['high'], low=ticker['low'])
        return self.price_dict[symbol]

    def lock_trade_set(self, i_ts):
        # avoids two processes changing a tradeset at the same time
        count = 0
        mystamp = time.time()
        self.tradeSets[i_ts].waiting.append(mystamp)
        time.sleep(0.2)
        while self.tradeSets[i_ts].updating or self.tradeSets[i_ts].waiting[0] < mystamp:
            count += 1
            time.sleep(1)
            if count > 60:  # 60 sec max wait
                try:  # cautionary so that no timestamp can stay in the queue due to some messaging error
                    self.message(
                        'Waiting for tradeSet update (%s on %s) to finish timed out after 1 min.. '
                        'Resetting updating variable now.' % (
                            self.tradeSets[i_ts].symbol, self.exchange.name), 'error')
                except Exception:
                    pass
                break
        self.tradeSets[i_ts].updating = True
        self.tradeSets[i_ts].waiting.remove(mystamp)

    def unlock_trade_set(self, i_ts):
        self.tradeSets[i_ts].updating = False

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
        except AuthenticationError:  #
            self.authenticated = False
            try:
                self.message('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                             'error')
            except Exception:
                print('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name)
        except getattr(ccxt, 'ExchangeError') as e:
            self.authenticated = False
            if 'key' in str(e).lower():
                try:
                    self.message('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                                 'error')
                except Exception:
                    print('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name)
            else:
                try:
                    self.message('The following error occured at exchange %s:\n%s' % (self.exchange.name, str(e)),
                                 'error')
                except Exception:
                    print('The following error occured at exchange %s:\n%s' % (self.exchange.name, str(e)))

    def calculate_fee(self, symbol, typ, direction, amount, price, maker_or_taker):
        return self.exchange.calculate_fee(symbol, typ, direction, amount, price, maker_or_taker)

    def init_trade_set(self, symbol) -> BaseTradeSet:
        self.update_balance()

        ts = BaseTradeSet(symbol=symbol)
        i_ts = ts.get_uid()
        if i_ts in self.tradeSets:
            raise Exception('uid already exists in trade sets!')
        self.tradeSets[i_ts] = ts
        return ts

    def activate_trade_set(self, i_ts, verbose=True):
        self.update_down_state(True)
        ts = self.tradeSets[i_ts]
        wasactive = ts.active
        # check if symbol is active
        if not self.exchange.markets[ts.symbol]['active']:
            self.message(
                'Cannot activate trade set because %s was deactivated for trading by the exchange!' % ts.symbol,
                'error')
            return wasactive
        # sanity check of amounts to buy/sell
        if self.sum_sell_amounts(i_ts, 'notinitiated') - (self.sum_buy_amounts(i_ts, 'notfilled') + ts.coinsAvail) > 0:
            self.message(
                f"Cannot activate trade set because the total amount you (still) want to sell "
                f"({self.amount2Prec(ts.symbol, self.sum_sell_amounts(i_ts, 'notinitiated', True))} "
                f"{ts.coinCurrency}) exceeds the total amount you want to buy "
                f"({self.amount2Prec(ts.symbol, self.sum_buy_amounts(i_ts, 'notfilled', True))} {ts.coinCurrency} "
                f"after fee subtraction) and the amount you already have in this trade set "
                f"({self.amount2Prec(ts.symbol, ts.coinsAvail)} {ts.coinCurrency}). "
                f"Please adjust the trade set!", 'error')
            return wasactive
        elif self.min_buy_price(i_ts, order='notfilled') is not None and ts.SL is not None and ts.SL.value \
                >= self.min_buy_price(i_ts, order='notfilled'):
            self.message(
                'Cannot activate trade set because the current stop loss price is higher than the lowest non-filled buy'
                ' order price, which means this buy order could never be reached. Please adjust the trade set!',
                'error')
            return wasactive
        self.tradeSets[i_ts].virgin = False
        self.tradeSets[i_ts].active = True
        if verbose and not wasactive:
            total_buy_cost = ts.costIn + self.sum_buy_costs(i_ts, 'notfilled')
            self.message('Estimated return if all trades are executed: %s %s' % (
                self.cost2Prec(ts.symbol, self.sum_sell_costs(i_ts) - total_buy_cost), ts.baseCurrency))
            if ts.SL is not None or isinstance(ts.SL, DailyCloseSL):
                loss = total_buy_cost - ts.costOut - (
                        ts.initCoins + self.sum_buy_amounts(i_ts) - self.sum_sell_amounts(i_ts, 'filled')) * ts.SL.value
                self.message('Estimated %s if buys reach stop-loss before selling: %s %s' % (
                    '*gain*' if loss < 0 else 'loss', self.cost2Prec(ts.symbol, -loss if loss < 0 else loss),
                    ts.baseCurrency))
        try:
            self.init_buy_orders(i_ts)
        except InsufficientFunds:
            self.message('Cannot activate trade set due to insufficient funds!', 'error')
            self.deactivate_trade_set(i_ts)
        return wasactive

    def deactivate_trade_set(self, i_ts, cancel_orders=0):
        self.update_down_state(True)
        # cancelOrders can be 0 (not), 1 (cancel), 2 (cancel and delete open orders)
        wasactive = self.tradeSets[i_ts].active
        if cancel_orders:
            self.cancel_buy_orders(i_ts, delete_orders=cancel_orders == 2)
            self.cancel_sell_orders(i_ts, delete_orders=cancel_orders == 2)
        self.tradeSets[i_ts].active = False
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

        ts = self.init_trade_set(symbol)
        i_ts = ts.get_uid()

        # truncate values to precision
        sell_levels = [float(self.exchange.priceToPrecision(ts.symbol, val)) for val in sell_levels]
        buy_levels = [float(self.exchange.priceToPrecision(ts.symbol, val)) for val in buy_levels]
        sell_amounts = [float(self.exchange.amountToPrecision(ts.symbol, val)) for val in sell_amounts]
        buy_amounts = [float(self.exchange.amountToPrecision(ts.symbol, val)) for val in buy_amounts]

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
                    'It seems the buy and sell amount of %s is not the same. Is this correct?' % ts.coinCurrency)
        if buy_levels.size > 0 and sell_levels.size > 0 and max(buy_levels) > min(sell_levels):
            raise ValueError(
                'It seems at least one of your sell prices is lower than one of your buy, which does not make sense')
        if self.balance[ts.baseCurrency]['free'] < sum(buy_levels * buy_amounts):
            raise ValueError('Free balance of %s not sufficient to initiate trade set' % ts.baseCurrency)

        # create the buy orders
        for n, _ in enumerate(buy_levels):
            self.add_buy_level(i_ts, buy_levels[n], buy_amounts[n], candle_above[n])

        self.add_init_coins(i_ts, init_coins, init_price)
        self.set_sl(i_ts, sl)
        self.set_trailing_sl(i_ts, None)
        # create the sell orders
        for n, _ in enumerate(sell_levels):
            self.add_sell_level(i_ts, sell_levels[n], sell_amounts[n])

        self.activate_trade_set(i_ts)
        self.update()
        return i_ts

    def get_trade_set_info(self, i_ts, show_profit_in=None):
        ts = self.tradeSets[i_ts]
        prt_str = '*%srade set #%d on %s%s [%s]:*\n' % ('T' if ts.active else 'INACTIVE t',
                                                        list(self.tradeSets.keys()).index(i_ts), self.exchange.name,
                                                        ' (DOWN !!!) ' if self.down else '', ts.symbol)
        filled_buys = []
        filled_sells = []
        for iTrade, trade in enumerate(ts.InTrades):
            tmpstr = '*Buy level %d:* Price %s , Amount %s %s   ' % (
                iTrade, self.price2Prec(ts.symbol, trade['price']), self.amount2Prec(ts.symbol, trade['amount']),
                ts.coinCurrency)
            if trade['oid'] is None:
                if trade['candleAbove'] is None:
                    tmpstr = tmpstr + '_Order not initiated_\n'
                else:
                    tmpstr = tmpstr + 'if DC > %s\n' % self.price2Prec(ts.symbol, trade['candleAbove'])
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                filled_buys.append([trade['actualAmount'], trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            prt_str += tmpstr
        prt_str += '\n'
        for iTrade, trade in enumerate(ts.OutTrades):
            tmpstr = '*Sell level %d:* Price %s , Amount %s %s   ' % (
                iTrade, self.price2Prec(ts.symbol, trade['price']), self.amount2Prec(ts.symbol, trade['amount']),
                ts.coinCurrency)
            if trade['oid'] is None:
                tmpstr = tmpstr + '_Order not initiated_\n'
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                filled_sells.append([trade['amount'], trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            prt_str += tmpstr
        if ts.SL is not None:
            prt_str += '\n*Stop-loss* set at %s%s\n\n' % (self.price2Prec(ts.symbol, ts.SL.value),
                                                          '' if not isinstance(ts.SL, TrailingSL) else (
                                                              ' (trailing with offset %.5g)' % ts.SL.delta if
                                                              ts.SL.kind == ValueType.ABSOLUTE else
                                                              ' (trailing with offset %.2g %%)' % (ts.delta * 100)))
        elif isinstance(ts.SL, DailyCloseSL):
            prt_str += '\n*Stop-loss* set at daily close < %s\n\n' % (self.price2Prec(ts.symbol, ts.SL.value))
        elif isinstance(ts.SL, WeeklyCloseSL):
            prt_str += '\n*Stop-loss* set at weekly close < %s\n\n' % (
                self.price2Prec(ts.symbol, ts.SL.value))
        else:
            prt_str += '\n*No stop-loss set.*\n\n'
        sumBuys = sum([val[0] for val in filled_buys])
        sumSells = sum([val[0] for val in filled_sells])
        if ts.initCoins > 0:
            prt_str += '*Initial coins:* %s %s for an average price of %s\n' % (
                self.amount2Prec(ts.symbol, ts.initCoins), ts.coinCurrency,
                self.price2Prec(ts.symbol, ts.initPrice) if ts.initPrice is not None else 'unknown')
        if sumBuys > 0:
            prt_str += '*Filled buy orders (fee subtracted):* %s %s for an average price of %s\n' % (
                self.amount2Prec(ts.symbol, sumBuys), ts.coinCurrency, self.cost2Prec(ts.symbol, sum(
                    [val[0] * val[1] / sumBuys if sumBuys > 0 else None for val in filled_buys])))
        if sumSells > 0:
            prt_str += '*Filled sell orders:* %s %s for an average price of %s\n' % (
                self.amount2Prec(ts.symbol, sumSells), ts.coinCurrency, self.cost2Prec(ts.symbol, sum(
                    [val[0] * val[1] / sumSells if sumSells > 0 else None for val in filled_sells])))
        if self.exchange.markets[ts.symbol]['active']:
            price_obj = self.get_price_obj(ts.symbol)
            prt_str += '\n*Current market price *: %s, \t24h-high: %s, \t24h-low: %s\n' % tuple(
                [self.price2Prec(ts.symbol, val) for val in
                 [price_obj.get_current_price(), price_obj.get_high_price(), price_obj.get_low_price()]])
            if (ts.initCoins == 0 or ts.initPrice is not None) and ts.costIn > 0 and (
                    sumBuys > 0 or ts.initCoins > 0):
                total_amount_to_sell = ts.coinsAvail + self.sum_sell_amounts(i_ts, 'open')
                fee = self.calculate_fee(ts.symbol, 'market', 'sell', total_amount_to_sell,
                                         price_obj.get_current_price(), 'taker')
                cost_sells = ts.costOut + price_obj.get_current_price() * total_amount_to_sell - (
                    fee['cost'] if fee['currency'] == ts.baseCurrency else 0)
                gain = cost_sells - ts.costIn
                gain_orig = gain
                if show_profit_in is not None:
                    gain, this_cur = self.convert_amount(gain, ts.baseCurrency, show_profit_in)
                else:
                    this_cur = ts.baseCurrency
                prt_str += '\n*Estimated gain/loss when selling all now: * %s %s (%+.2f %%)\n' % (
                    self.cost2Prec(ts.symbol, gain), this_cur, gain_orig / ts.costIn * 100)
        else:
            prt_str += '\n*Warning: Symbol %s is currently deactivated for trading by the exchange!*\n' % ts.symbol
        return prt_str

    def create_trade_history_entry(self, i_ts):
        self.update_down_state(True)
        # create a trade history entry if the trade set had any filled orders
        ts = self.tradeSets[i_ts]
        if self.num_buy_levels(i_ts, 'filled') > 0 or self.num_sell_levels(i_ts, 'filled') > 0:
            gain = ts.costOut - ts.costIn
            # try to convert gain amount into btc currency
            gain_btc, curr = self.convert_amount(gain, ts.baseCurrency, 'BTC')
            if curr != 'BTC':
                gain_btc = None
            if gain_btc:
                # try to convert btc gain into usd currency
                gain_usd, curr = self.convert_amount(gain_btc, 'BTC', 'USD')
                if curr != 'USD':
                    gain_usd, curr = self.convert_amount(gain_btc, 'BTC', 'USDT')
                    if curr != 'USDT':
                        gain_usd = None
            else:
                gain_usd = None
            self.tradeSetHistory.append({'time': time.time(),
                                         'days': None if 'createdAt' not in ts
                                         else (time.time() - ts.createdAt) / 60 / 60 / 24,
                                         'symbol': ts.symbol, 'gain': gain,
                                         'gainRel': gain / ts.costIn * 100 if ts.costIn > 0 else None,
                                         'quote': ts.baseCurrency, 'gainBTC': gain_btc, 'gainUSD': gain_usd})

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

    def convert_amount(self, amount, currency, target_currency):
        self.update_down_state(True)
        if isinstance(target_currency, str):
            target_currency = [target_currency]

        conversion_pairs = [('%s/%s' % (currency, cur) in self.exchange.symbols and
                            self.exchange.markets['%s/%s' % (currency, cur)]['active']) + 2 * (
                                   '%s/%s' % (cur, currency) in self.exchange.symbols and
                                   self.exchange.markets['%s/%s' % (cur, currency)]['active']) for cur in
                            target_currency]
        ind = next((i for i, x in enumerate(conversion_pairs) if x), None)
        if ind is not None:
            this_cur = target_currency[ind]
            if conversion_pairs[ind] == 1:
                amount *= self.safe_run(lambda: self.exchange.fetchTicker('%s/%s' % (currency, this_cur)))['last']
            else:
                amount /= self.safe_run(lambda: self.exchange.fetchTicker('%s/%s' % (this_cur, currency)))['last']
            return amount, this_cur
        else:
            return amount, currency

    def delete_trade_set(self, i_ts, sell_all=False):
        self.update_down_state(True)
        self.lock_trade_set(i_ts)
        if sell_all:
            sold = self.sell_all_now(i_ts)
        else:
            sold = True
            self.deactivate_trade_set(i_ts, 1)
        if sold:
            self.create_trade_history_entry(i_ts)
            self.tradeSets.pop(i_ts)
        else:
            self.unlock_trade_set(i_ts)

    def add_init_coins(self, i_ts, init_coins=0, init_price=None):
        if self.check_num(init_coins, init_price) or (init_price is None and self.check_num(init_coins)):
            if init_price is not None and init_price < 0:
                init_price = None
            ts = self.tradeSets[i_ts]
            # check if free balance is indeed sufficient
            bal = self.get_balance(ts.coinCurrency)
            if bal is None:
                self.message('Free balance could not be determined as exchange does not support this! '
                             'If free balance does not suffice for initial coins there will be an error when trade set '
                             'is activated!',
                             'warning')
            elif bal < init_coins:
                self.message('Adding initial balance failed: %s %s requested but only %s %s are free!' % (
                    self.amount2Prec(ts.symbol, init_coins), ts.coinCurrency,
                    self.amount2Prec(ts.symbol, self.get_balance(ts.coinCurrency)), ts.coinCurrency),
                             'error')
                return 0
            self.lock_trade_set(i_ts)

            if ts.coinsAvail > 0 and ts.initPrice is not None:
                # remove old cost again
                ts.costIn -= (ts.coinsAvail * ts.initPrice)
            ts.coinsAvail = init_coins
            ts.initCoins = init_coins

            ts.initPrice = init_price
            if init_price is not None:
                ts.costIn += (init_coins * init_price)
            self.unlock_trade_set(i_ts)
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

    def get_trade_param(self, i_ts, what, method, direction, order='all', subtract_fee=True):
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

        trades = getattr(self.tradeSets[i_ts], trade)

        if what == 'amount':
            if order == 'all':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     trades])
            elif order == 'filled':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     trades if val['oid'] == 'filled'])
            elif order == 'open':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     trades if val['oid'] != 'filled' and val['oid'] is not None])
            elif order == 'notinitiated':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     trades if val['oid'] != 'filled' and val['oid'] is None])
            elif order == 'notfilled':
                return func(
                    [(val['amount'] if direction == 'sell' or subtract_fee is False else val['actualAmount']) for val in
                     trades if val['oid'] != 'filled'])
        elif what == 'price':
            if order == 'all':
                return func([val['price'] for val in trades])
            elif order == 'filled':
                return func([val['price'] for val in trades if val['oid'] == 'filled'])
            elif order == 'open':
                return func([val['price'] for val in trades if
                             val['oid'] != 'filled' and val['oid'] is not None])
            elif order == 'notinitiated':
                return func([val['price'] for val in trades if
                             val['oid'] != 'filled' and val['oid'] is None])
            elif order == 'notfilled':
                return func([val['price'] for val in trades if val['oid'] != 'filled'])
        elif what == 'cost':
            if order == 'all':
                return func([val['amount'] * val['price'] for val in trades])
            elif order == 'filled':
                return func(
                    [val['amount'] * val['price'] for val in trades if val['oid'] == 'filled'])
            elif order == 'open':
                return func([val['amount'] * val['price'] for val in trades if
                             val['oid'] != 'filled' and val['oid'] is not None])
            elif order == 'notinitiated':
                return func([val['amount'] * val['price'] for val in trades if
                             val['oid'] != 'filled' and val['oid'] is None])
            elif order == 'notfilled':
                return func(
                    [val['amount'] * val['price'] for val in trades if val['oid'] != 'filled'])

    def add_buy_level(self, i_ts, buy_price, buy_amount, candle_above=None):
        self.update_down_state(True)
        ts = self.tradeSets[i_ts]
        if self.check_num(buy_price, buy_amount, candle_above) or (
                candle_above is None and self.check_num(buy_price, buy_amount)):
            fee = self.calculate_fee(ts.symbol, 'limit', 'buy', buy_amount, buy_price, 'maker')
            if not self.check_quantity(ts.symbol, 'amount', buy_amount):
                self.message('Adding buy level failed, amount is not within the range, the exchange accepts', 'error')
                return 0
            elif not self.check_quantity(ts.symbol, 'price', buy_price):
                self.message('Adding buy level failed, price is not within the range, the exchange accepts', 'error')
                return 0
            elif not self.check_quantity(ts.symbol, 'cost', buy_price * buy_amount):
                self.message('Adding buy level failed, cost is not within the range, the exchange accepts', 'error')
                return 0
            bal = self.get_balance(ts.baseCurrency)
            if bal is None:
                self.message('Free balance could not be determined as exchange does not support this! '
                             'If free balance does not suffice there will be an error when trade set is activated',
                             'warning')
            elif bal < buy_amount * buy_price + (fee['cost'] if fee['currency'] == ts.baseCurrency else 0):
                self.message('Adding buy level failed, your balance of %s does not suffice to buy this amount%s!' % (
                    ts.baseCurrency,
                    ' and pay the trading fee (%s %s)' % (
                        self.fee2Prec(ts.symbol, fee['cost']), ts.baseCurrency) if
                    fee['currency'] == ts.baseCurrency else ''), 'error')
                return 0

            bought_amount = buy_amount
            if fee['currency'] == ts.coinCurrency and \
                    (self.exchange.name.lower() != 'binance' or self.get_balance('BNB') < 0.5):
                # this is a hack, as fees on binance are deduced from BNB if this is activated and there is enough BNB,
                # however so far no API chance to see if this is the case. Here I assume that 0.5 BNB are enough to pay
                # the fee for the trade and thus the fee is not subtracted from the traded coin
                bought_amount -= fee['cost']
            self.lock_trade_set(i_ts)
            wasactive = self.deactivate_trade_set(i_ts)
            ts.InTrades.append({'oid': None, 'price': buy_price, 'amount': buy_amount, 'actualAmount': bought_amount,
                                'candleAbove': candle_above})
            if wasactive:
                self.activate_trade_set(i_ts, False)
            self.unlock_trade_set(i_ts)
            return self.num_buy_levels(i_ts) - 1
        else:
            raise ValueError('Some input was no number')

    def delete_buy_level(self, i_ts, i_trade):
        self.update_down_state(True)
        if self.check_num(i_trade):
            self.lock_trade_set(i_ts)
            ts = self.tradeSets[i_ts]
            wasactive = self.deactivate_trade_set(i_ts)
            if ts.InTrades[i_trade]['oid'] is not None and ts.InTrades[i_trade]['oid'] != 'filled':
                self.cancel_buy_orders(i_ts, ts.InTrades[i_trade]['oid'])
            ts.InTrades.pop(i_trade)
            if wasactive:
                self.activate_trade_set(i_ts, False)
            self.unlock_trade_set(i_ts)
        else:
            raise ValueError('Some input was no number')

    def set_buy_level(self, i_ts, i_trade, price, amount):
        self.update_down_state(True)
        if self.check_num(i_trade, price, amount):
            ts = self.tradeSets[i_ts]
            if ts.InTrades[i_trade]['oid'] == 'filled':
                self.message('This order is already filled! No change possible')
                return 0
            else:
                fee = self.calculate_fee(ts.symbol, 'limit', 'buy', amount, price, 'maker')
                if not self.check_quantity(ts.symbol, 'amount', amount):
                    self.message('Changing buy level failed, amount is not within the range, the exchange accepts')
                    return 0
                elif not self.check_quantity(ts.symbol, 'price', price):
                    self.message('Changing buy level failed, price is not within the range, the exchange accepts')
                    return 0
                elif not self.check_quantity(ts.symbol, 'cost', price * amount):
                    self.message('Changing buy level failed, cost is not within the range, the exchange accepts')
                    return 0
                bal = self.get_balance(ts.baseCurrency)
                if bal is None:
                    self.message('Free balance could not be determined as exchange does not support this! '
                                 'If free balance does not suffice there will be an error when trade set is activated',
                                 'warning')
                elif bal + ts.InTrades[i_trade]['amount'] * ts.InTrades[i_trade]['price'] < amount * price + \
                        fee['cost'] if fee['currency'] == ts.baseCurrency else 0:
                    self.message(
                        'Changing buy level failed, your balance of %s does not suffice to buy this amount%s!' % (
                            ts.baseCurrency, ' and pay the trading fee (%s %s)' % (
                                self.fee2Prec(ts.symbol, fee['cost']), ts.baseCurrency) if fee['currency'] == ts[
                                'baseCurrency'] else ''))
                    return 0
                bought_amount = amount
                # this is a hack, as fees on binance are deduced from BNB if this is activated and there is enough BNB,
                # however so far no API chance to see if this is the case. Here I assume that 0.5 BNB are enough to pay
                # the fee for the trade and thus the fee is not subtracted from the traded coin
                if fee['currency'] == ts.coinCurrency and \
                        (self.exchange.name.lower() != 'binance' or self.get_balance('BNB') < 0.5):
                    bought_amount -= fee['cost']

                wasactive = self.deactivate_trade_set(i_ts)

                if ts.InTrades[i_trade]['oid'] is not None and ts.InTrades[i_trade]['oid'] != 'filled':
                    return_val = self.cancel_buy_orders(i_ts, ts.InTrades[i_trade]['oid'])
                    ts.InTrades[i_trade]['oid'] = None
                    if return_val == 0.5:
                        bal = self.get_balance(ts.baseCurrency)
                        if bal is None:
                            self.message('Free balance could not be determined as exchange does not support this! If '
                                         'free balance does not suffice there will be an error on trade set activation',
                                         'warning')
                        elif bal + ts.InTrades[i_trade]['amount'] * ts.InTrades[i_trade]['price'] < amount * price \
                                + fee['cost'] if fee['currency'] == ts.baseCurrency else 0:
                            self.message(f"Changing buy level failed, your balance of {ts.baseCurrency} does not "
                                         f"suffice to buy this amount%s!" % (
                                             f" and pay the trading fee ({self.fee2Prec(ts.symbol, fee['cost'])} "
                                             f"{ts.baseCurrency})" if fee['currency'] == ts.baseCurrency else ''))
                            return 0
                ts.InTrades[i_trade].update({'amount': amount, 'actualAmount': bought_amount, 'price': price})

                if wasactive:
                    self.activate_trade_set(i_ts, False)
                return 1
        else:
            raise ValueError('Some input was no number')

    def add_sell_level(self, i_ts, sell_price, sell_amount):
        self.update_down_state(True)
        ts = self.tradeSets[i_ts]
        if self.check_num(sell_price, sell_amount):
            if not self.check_quantity(ts.symbol, 'amount', sell_amount):
                self.message('Adding sell level failed, amount is not within the range, the exchange accepts')
                return 0
            elif not self.check_quantity(ts.symbol, 'price', sell_price):
                self.message('Adding sell level failed, price is not within the range, the exchange accepts')
                return 0
            elif not self.check_quantity(ts.symbol, 'cost', sell_price * sell_amount):
                self.message('Adding sell level failed, return is not within the range, the exchange accepts')
                return 0
            self.lock_trade_set(i_ts)
            wasactive = self.deactivate_trade_set(i_ts)
            ts.OutTrades.append({'oid': None, 'price': sell_price, 'amount': sell_amount})
            if wasactive:
                self.activate_trade_set(i_ts, False)
            self.unlock_trade_set(i_ts)
            return self.num_sell_levels(i_ts) - 1
        else:
            raise ValueError('Some input was no number')

    def delete_sell_level(self, i_ts, i_trade):
        self.update_down_state(True)
        if self.check_num(i_trade):
            self.lock_trade_set(i_ts)
            ts = self.tradeSets[i_ts]
            wasactive = self.deactivate_trade_set(i_ts)
            if ts.OutTrades[i_trade]['oid'] is not None and ts.OutTrades[i_trade]['oid'] != 'filled':
                self.cancel_sell_orders(i_ts, ts.OutTrades[i_trade]['oid'])
            ts.OutTrades.pop(i_trade)
            self.unlock_trade_set(i_ts)
            if wasactive:
                self.activate_trade_set(i_ts, False)
        else:
            raise ValueError('Some input was no number')

    def set_sell_level(self, i_ts, i_trade, price, amount):
        self.update_down_state(True)
        if self.check_num(i_trade, price, amount):
            ts = self.tradeSets[i_ts]
            if ts.OutTrades[i_trade]['oid'] == 'filled':
                self.message('This order is already filled! No change possible')
                return 0
            else:
                if not self.check_quantity(ts.symbol, 'amount', amount):
                    self.message('Changing sell level failed, amount is not within the range, the exchange accepts')
                    return 0
                elif not self.check_quantity(ts.symbol, 'price', price):
                    self.message('Changing sell level failed, price is not within the range, the exchange accepts')
                    return 0
                elif not self.check_quantity(ts.symbol, 'cost', price * amount):
                    self.message('Changing sell level failed, return is not within the range, the exchange accepts')
                    return 0
                wasactive = self.deactivate_trade_set(i_ts)

                if ts.OutTrades[i_trade]['oid'] is not None and ts.OutTrades[i_trade]['oid'] != 'filled':
                    self.cancel_sell_orders(i_ts, ts.OutTrades[i_trade]['oid'])
                    ts.OutTrades[i_trade]['oid'] = None

                ts.OutTrades[i_trade]['amount'] = amount
                ts.OutTrades[i_trade]['price'] = price

                if wasactive:
                    self.activate_trade_set(i_ts, False)
                return 1
        else:
            raise ValueError('Some input was no number')

    def set_trailing_sl(self, i_ts, value, typ: ValueType = ValueType.ABSOLUTE):
        self.update_down_state(True)
        ts = self.tradeSets[i_ts]
        if self.check_num(value):
            if self.num_buy_levels(i_ts, 'notfilled') > 0:
                raise Exception('Trailing SL cannot be set as there are non-filled buy orders still')
            ts.SL = TrailingSL(delta=value, kind=typ, price_obj=self.get_price_obj(ts.symbol))
        elif value is None:
            ts.SL = None
        else:
            raise ValueError('Input was no number')

    def set_weekly_close_sl(self, i_ts, value):
        ts = self.tradeSets[i_ts]
        if self.check_num(value):
            ts.SL = WeeklyCloseSL(value=value)
            if self.get_price_obj(ts.symbol).get_current_price() <= value:
                self.message('Weekly-close SL is set but be aware that it is higher than the current market price!',
                             'Warning')

        elif value is None:
            ts.SL = None
        else:
            raise ValueError('Input was no number')

    def set_daily_close_sl(self, i_ts, value):
        ts = self.tradeSets[i_ts]
        if self.check_num(value):
            ts.SL = DailyCloseSL(value=value)
            if self.get_price_obj(ts.symbol).get_current_price() <= value:
                self.message('Daily-close SL is set but be aware that it is higher than the current market price!',
                             'Warning')
        elif value is None:
            ts.SL = None
        else:
            raise ValueError('Input was no number')

    def set_sl(self, i_ts, value):
        ts = self.tradeSets[i_ts]
        if self.check_num(value):
            try:
                ts.SL = BaseSL(value=value)
            except Exception as e:
                self.message(str(e), 'error')
        elif value is None:
            ts.SL = None
        else:
            raise ValueError('Input was no number')

    def set_sl_break_even(self, i_ts):
        self.update_down_state(True)
        ts = self.tradeSets[i_ts]
        if ts.initCoins > 0 and ts.initPrice is None:
            self.message(f"Break even SL cannot be set as you this trade set contains {ts.coinCurrency} that you "
                         f"obtained beforehand and no buy price information was given.")
            return 0
        elif ts.costOut - ts.costIn > 0:
            self.message(
                'Break even SL cannot be set as your sold coins of this trade already outweigh your buy expenses '
                '(congrats!)! You might choose to sell everything immediately if this is what you want.')
            return 0
        elif ts.costOut - ts.costIn == 0:
            self.message('Break even SL cannot be set as there are no unsold %s coins right now' % ts.coinCurrency)
            return 0
        else:
            break_even_price = (ts.costIn - ts.costOut) / ((1 - self.exchange.fees['trading']['taker']) * (
                    ts.coinsAvail + sum([trade['amount'] for trade in ts.OutTrades if
                                         trade['oid'] != 'filled' and trade['oid'] is not None])))
            price_obj = self.get_price_obj(ts.symbol)
            if price_obj.get_current_price() < break_even_price:
                self.message('Break even SL of %s cannot be set as the current market price is lower (%s)!' % tuple(
                    [self.price2Prec(ts.symbol, val) for val in [break_even_price, price_obj.get_current_price()]]))
                return 0
            else:
                self.set_sl(i_ts, break_even_price)
                return 1

    def sell_free_bal(self, ts) -> Union[None, dict]:
        free_bal = self.get_balance(ts.coinCurrency)
        if free_bal is None:
            self.message(f"When selling {ts.symbol}, exchange reported insufficient funds and does not allow to "
                         f"determine free balance of {ts.coinCurrency}, thus nothing could be sold automatically! "
                         f"Please sell manually!", 'error')
            return None
        elif free_bal == 0:
            self.message(f"When selling {ts.symbol}, exchange reported insufficient funds. Please sell manually!",
                         'error')
            return None
        else:
            try:
                response = self.safe_run(lambda: self.exchange.createMarketSellOrder(ts.symbol, free_bal), False)
            except Exception:
                self.message('There was an error selling %s! Please sell manually!' % ts.symbol, 'warning')
                return None
            self.message('When selling %s, only %s %s was found and sold!' % (
                ts.symbol, self.amount2Prec(ts.symbol, free_bal), ts.coinCurrency), 'warning')
            return response

    def sell_all_now(self, i_ts, price=None):
        self.update_down_state(True)
        self.deactivate_trade_set(i_ts, 2)
        ts = self.tradeSets[i_ts]
        ts.SL = None  # necessary to not retrigger SL
        sold = True
        if ts.coinsAvail > 0 and self.check_quantity(ts.symbol, 'amount', ts.coinsAvail):
            if self.exchange.has['createMarketOrder']:
                try:
                    response = self.safe_run(
                        lambda: self.exchange.createMarketSellOrder(ts.symbol, ts.coinsAvail),
                        False)
                except InsufficientFunds:
                    response = self.sell_free_bal(ts)
                except Exception:
                    params = {'trading_agreement': 'agree'}  # for kraken api...
                    try:
                        response = self.safe_run(
                            lambda: self.exchange.createMarketSellOrder(ts.symbol, ts.coinsAvail, params),
                            i_ts=i_ts)
                    except InsufficientFunds:
                        response = self.sell_free_bal(ts)
            else:
                if price is None:
                    price = self.safe_run(lambda: self.exchange.fetch_ticker(ts.symbol)['last'], i_ts=i_ts)
                try:
                    response = self.safe_run(
                        lambda: self.exchange.createLimitSellOrder(ts.symbol, ts.coinsAvail, price * 0.995),
                        i_ts=i_ts)
                except InsufficientFunds:
                    response = self.sell_free_bal(ts)
            if response is not None:
                time.sleep(5)  # give exchange 5 sec for trading the order
                order_info = self.fetch_order(response['id'], i_ts, 'SELL')

                if order_info['status'] == 'FILLED':
                    if order_info['type'] == 'market' and self.exchange.has['fetchMyTrades'] is not False:
                        trades = self.exchange.fetchMyTrades(ts.symbol)
                        order_info['cost'] = sum([tr['cost'] for tr in trades if tr['order'] == order_info['id']])
                        order_info['price'] = np.mean([tr['price'] for tr in trades if tr['order'] == order_info['id']])
                    ts.costOut += order_info['cost']
                    self.message('Sold immediately at a price of %s %s: Sold %s %s for %s %s.' % (
                        self.price2Prec(ts.symbol, order_info['price']), ts.symbol,
                        self.amount2Prec(ts.symbol, order_info['amount']), ts.coinCurrency,
                        self.cost2Prec(ts.symbol, order_info['cost']), ts.baseCurrency))
                else:
                    self.message('Sell order was not traded immediately, updating status soon.')
                    sold = False
                    ts.OutTrades.append(
                        {'oid': response['id'], 'price': order_info['price'], 'amount': order_info['amount']})
                    self.activate_trade_set(i_ts, False)
            else:
                sold = False
        else:
            self.message('No coins (or too low amount) to sell from this trade set.', 'warning')
        return sold

    def cancel_sell_orders(self, i_ts, oid=None, delete_orders=False):
        self.update_down_state(True)
        return_val = 1
        if i_ts in self.tradeSets and self.num_sell_levels(i_ts) > 0:
            count = 0
            for iTrade, trade in reversed(list(enumerate(self.tradeSets[i_ts].OutTrades))):
                if oid is None or trade['oid'] == oid:
                    if trade['oid'] is not None and trade['oid'] != 'filled':
                        try:
                            self.cancel_order(trade['oid'], i_ts, 'SELL')
                        except OrderNotFound:
                            pass
                        except Exception as e:
                            self.unlock_trade_set(i_ts)
                            raise e
                        time.sleep(1)
                        count += 1
                        order_info = self.fetch_order(trade['oid'], i_ts, 'SELL')
                        self.tradeSets[i_ts].coinsAvail += trade['amount']
                        if order_info['filled'] > 0:
                            self.message('(Partly?) filled sell order found during canceling. Updating balance')
                            self.tradeSets[i_ts].costOut += order_info['price'] * order_info['filled']
                            self.tradeSets[i_ts].coinsAvail -= order_info['filled']
                            trade['oid'] = 'filled'
                            trade['amount'] = order_info['filled']
                            return_val = 0.5
                        else:
                            trade['oid'] = None
                    if delete_orders:
                        if trade['oid'] != 'filled':
                            self.tradeSets[i_ts].OutTrades.pop(iTrade)
            if count > 0:
                self.message('%d sell orders canceled in total for tradeSet %d (%s)' % (
                    count, list(self.tradeSets.keys()).index(i_ts), self.tradeSets[i_ts].symbol))
        return return_val

    def cancel_buy_orders(self, i_ts, oid=None, delete_orders=False):
        self.update_down_state(True)
        return_val = 1
        if i_ts in self.tradeSets and self.num_buy_levels(i_ts) > 0:
            count = 0
            for iTrade, trade in reversed(list(enumerate(self.tradeSets[i_ts].InTrades))):
                if oid is None or trade['oid'] == oid:
                    if trade['oid'] is not None and trade['oid'] != 'filled':
                        try:
                            self.cancel_order(trade['oid'], i_ts, 'BUY')
                        except OrderNotFound:
                            pass

                        time.sleep(1)
                        count += 1
                        order_info = self.fetch_order(trade['oid'], i_ts, 'BUY')
                        if order_info['filled'] > 0:
                            self.message('(Partly?) filled buy order found during canceling. Updating balance')
                            self.tradeSets[i_ts].costIn += order_info['price'] * order_info['filled']
                            self.tradeSets[i_ts].coinsAvail += order_info['filled']
                            trade['oid'] = 'filled'
                            trade['amount'] = order_info['filled']
                            return_val = 0.5
                        else:
                            trade['oid'] = None
                    if delete_orders:
                        if trade['oid'] != 'filled':
                            self.tradeSets[i_ts].InTrades.pop(iTrade)
            if count > 0:
                self.message('%d buy orders canceled in total for tradeSet %d (%s)' % (
                    count, list(self.tradeSets.keys()).index(i_ts), self.tradeSets[i_ts].symbol))
        return return_val

    def init_buy_orders(self, i_ts):
        self.update_down_state(True)
        if self.tradeSets[i_ts].active:
            # initialize buy orders
            for iTrade, trade in enumerate(self.tradeSets[i_ts].InTrades):
                if trade['oid'] is None and trade['candleAbove'] is None:
                    try:
                        response = self.safe_run(
                            lambda: self.exchange.createLimitBuyOrder(self.tradeSets[i_ts].symbol, trade['amount'],
                                                                      trade['price']))
                    except InsufficientFunds as e:
                        self.deactivate_trade_set(i_ts)
                        self.message(f"Insufficient funds on exchange {self.exchange.name} for trade set "
                                     f"#{self.exchange.name}. Trade set is deactivated now and not updated anymore "
                                     f"(open orders are still open)! Free the missing funds and reactivate. \n {e}.",
                                     'error')
                        raise e
                    self.tradeSets[i_ts].InTrades[iTrade]['oid'] = response['id']

    def cancel_order(self, oid, i_ts, typ):
        self.update_down_state(True)
        symbol = self.tradeSets[i_ts].symbol
        try:
            return self.safe_run(lambda: self.exchange.cancel_order(oid, symbol), False)
        except OrderNotFound as e:
            self.unlock_trade_set(i_ts)
            raise e
        except ccxt.ExchangeError:
            return self.safe_run(lambda: self.exchange.cancel_order(oid, symbol, {'type': typ}), i_ts=i_ts)

    def fetch_order(self, oid, i_ts, typ):
        symbol = self.tradeSets[i_ts].symbol
        try:
            return self.safe_run(lambda: self.exchange.fetch_order(oid, symbol), False)
        except OrderNotFound as e:
            self.unlock_trade_set(i_ts)
            raise e
        except ccxt.ExchangeError:
            return self.safe_run(lambda: self.exchange.fetch_order(oid, symbol, {'type': typ}), i_ts=i_ts)

    def update_down_state(self, raise_error=False):
        if self.down:
            self.safe_run(self.exchange.loadMarkets, print_error=False)
            if raise_error:
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
            for indTs, i_ts in enumerate(self.tradeSets):
                try:
                    ts = self.tradeSets[i_ts]
                    if not ts.active:
                        continue
                    self.lock_trade_set(i_ts)
                    price_obj = self.get_price_obj(ts.symbol)  # get and update the price
                    # check if stop loss is reached
                    if special_check < 2:
                        if ts.SL is not None:
                            if ts.SL.is_below(price_obj):
                                if isinstance(ts.SL, WeeklyCloseSL):
                                    msg = 'Weekly candle'
                                elif isinstance(ts.SL, DailyCloseSL):
                                    msg = 'Daily candle'
                                else:
                                    msg = 'Price'
                                self.message(msg + ' closed below chosen SL of %s for pair %s! Selling now!' % (
                                    self.price2Prec(ts.symbol, ts.SL.value), ts.symbol), 'warning')
                                # cancel all sell orders, create market sell order, save resulting amount of currency
                                sold = self.sell_all_now(i_ts, price=price_obj.get_current_price())
                                if sold:
                                    trade_sets_to_delete.append(i_ts)
                                    self.unlock_trade_set(i_ts)
                                    continue

                    else:  # tax warning check
                        for iTrade, trade in enumerate(ts.InTrades):
                            if 'time' in trade and (datetime.datetime.now() - trade['time']).days > 358 and (
                                    datetime.datetime.now() - trade['time']).days < 365:
                                self.message(
                                    f"Time since buy level #{iTrade} of trade set {indTs} ({ts.symbol}) on exchange "
                                    f"{self.exchange.name} was filled approaches one year "
                                    f"({(trade['time'] + datetime.timedelta(days=365)).strftime('%Y-%m-%d %H:%M')}) "
                                    f"after which gains/losses are not eligible for reporting in the tax report in most"
                                    f" countries!", 'warning')
                        continue
                    order_executed = 0
                    # go through buy trades 
                    for iTrade, trade in enumerate(ts.InTrades):
                        if trade['oid'] == 'filled':
                            continue
                        elif special_check == 1 and trade['oid'] is None and trade['candleAbove'] is not None:
                            if price_obj.get_current_price() > trade['candleAbove']:
                                response = self.safe_run(
                                    lambda: self.exchange.createLimitBuyOrder(ts.symbol, trade['amount'],
                                                                              trade['price']), i_ts=i_ts)
                                ts.InTrades[iTrade]['oid'] = response['id']
                                self.message('Daily candle of %s above %s triggering buy level #%d on %s!' % (
                                    ts.symbol, self.price2Prec(ts.symbol, trade['candleAbove']), iTrade,
                                    self.exchange.name))
                        elif trade['oid'] is not None:
                            try:
                                order_info = self.fetch_order(trade['oid'], i_ts, 'BUY')
                                # fetch trades for all orders because a limit order might also be filled at a lower val
                                if order_info['status'].lower() in ['closed', 'filled', 'canceled'] and \
                                        self.exchange.has['fetchMyTrades'] != False:
                                    trades = self.exchange.fetchMyTrades(ts.symbol)
                                    order_info['cost'] = sum(
                                        [tr['cost'] for tr in trades if tr['order'] == order_info['id']])
                                    if order_info['cost'] == 0:
                                        order_info['price'] = None
                                    else:
                                        order_info['price'] = np.mean(
                                            [tr['price'] for tr in trades if tr['order'] == order_info['id']])
                                else:
                                    trades = None
                                if order_info['status'].lower() in ['closed', 'filled']:
                                    order_executed = 1
                                    ts.InTrades[iTrade]['oid'] = 'filled'
                                    ts.InTrades[iTrade]['time'] = datetime.datetime.now()
                                    ts.InTrades[iTrade]['price'] = order_info['price']
                                    ts.costIn += order_info['cost']
                                    self.message('Buy level of %s %s reached on %s! Bought %s %s for %s %s.' % (
                                        self.price2Prec(ts.symbol, order_info['price']), ts.symbol,
                                        self.exchange.name,
                                        self.amount2Prec(ts.symbol, order_info['amount']), ts.coinCurrency,
                                        self.cost2Prec(ts.symbol, order_info['cost']), ts.baseCurrency))
                                    ts.coinsAvail += trade['actualAmount']
                                elif order_info['status'] == 'canceled':
                                    if 'reason' in order_info['info']:
                                        reason = order_info['info']['reason']
                                    else:
                                        reason = 'N/A'
                                    cancel_msg = f"Buy order (level {iTrade} of trade set " \
                                        f"{list(self.tradeSets.keys()).index(i_ts)} on {self.exchange.name}) was " \
                                        f"canceled by exchange or someone else (reason: {reason}) "
                                    if order_info['cost'] > 0:
                                        ts.InTrades[iTrade]['oid'] = 'filled'
                                        ts.InTrades[iTrade]['price'] = order_info['price']
                                        ts.costIn += order_info['cost']
                                        if trades is not None:
                                            order_info['amount'] = sum(
                                                [tr['amount'] for tr in trades if tr['order'] == order_info['id']])
                                        ts.coinsAvail += order_info['amount']
                                        self.message(cancel_msg + 'but already partly filled! Treating '
                                                                  'order as closed and updating trade set info.',
                                                     'error')
                                    else:
                                        ts.InTrades[iTrade]['oid'] = None
                                        self.message(cancel_msg + 'Will be reinitialized during next update.', 'error')

                            except OrderNotFound:
                                self.lock_trade_set(i_ts)
                                self.message(
                                    f"Buy order id {ts.InTrades[iTrade]['oid']} for trade set {ts.symbol} not "
                                    f"found on {self.exchange.name}! Maybe exchange API has changed? Resetting order to"
                                    f" 'not initiated', will be initiated on next trade set update!", 'error')
                                ts.InTrades[iTrade]['oid'] = None

                        else:
                            self.init_buy_orders(i_ts)
                            time.sleep(1)

                    if not special_check:
                        # go through all selling positions and create those for which the bought coins suffice
                        for iTrade, _ in enumerate(ts.OutTrades):
                            if ts.OutTrades[iTrade]['oid'] is None and ts.coinsAvail >= \
                                    ts.OutTrades[iTrade]['amount']:
                                try:
                                    response = self.safe_run(lambda: self.exchange.createLimitSellOrder(ts.symbol,
                                                                                                        ts.OutTrades[
                                                                                                            iTrade][
                                                                                                            'amount'],
                                                                                                        ts.OutTrades[
                                                                                                            iTrade][
                                                                                                            'price']),
                                                             i_ts=i_ts)
                                except InsufficientFunds as e:
                                    self.deactivate_trade_set(i_ts)
                                    self.message(f"Insufficient funds on exchange {self.exchange.name} for trade set "
                                                 f"#{list(self.tradeSets.keys()).index(i_ts)}. Trade set is deactivated"
                                                 f" now and not updated anymore (open orders are still open)! "
                                                 f"Free the missing funds and reactivate. \n {e}."
                                                 'error')

                                    raise e
                                ts.OutTrades[iTrade]['oid'] = response['id']
                                ts.coinsAvail -= ts.OutTrades[iTrade]['amount']
                        # go through sell trades 
                        for iTrade, trade in enumerate(ts.OutTrades):
                            if trade['oid'] == 'filled':
                                continue
                            elif trade['oid'] is not None:
                                try:
                                    order_info = self.fetch_order(trade['oid'], i_ts, 'SELL')
                                    # fetch trades for all orders as a limit order might also be filled at a higher val
                                    if self.exchange.has['fetchMyTrades'] != False:
                                        trades = self.exchange.fetchMyTrades(ts.symbol)
                                        order_info['cost'] = sum(
                                            [tr['cost'] for tr in trades if tr['order'] == order_info['id']])
                                        if order_info['cost'] == 0:
                                            order_info['price'] = None
                                        else:
                                            order_info['price'] = np.mean(
                                                [tr['price'] for tr in trades if tr['order'] == order_info['id']])
                                    else:
                                        trades = None
                                    if any([order_info['status'].lower() == val for val in ['closed', 'filled']]):
                                        order_executed = 2
                                        ts.OutTrades[iTrade]['oid'] = 'filled'
                                        ts.OutTrades[iTrade]['time'] = datetime.datetime.now()
                                        ts.OutTrades[iTrade]['price'] = order_info['price']
                                        ts.costOut += order_info['cost']
                                        self.message('Sell level of %s %s reached on %s! Sold %s %s for %s %s.' % (
                                            self.price2Prec(ts.symbol, order_info['price']), ts.symbol,
                                            self.exchange.name, self.amount2Prec(ts.symbol, order_info['amount']),
                                            ts.coinCurrency, self.cost2Prec(ts.symbol, order_info['cost']),
                                            ts.baseCurrency))
                                    elif order_info['status'] == 'canceled':
                                        if 'reason' in order_info['info']:
                                            reason = order_info['info']['reason']
                                        else:
                                            reason = 'N/A'
                                        if order_info['cost'] > 0:
                                            ts.OutTrades[iTrade]['oid'] = 'filled'
                                            ts.OutTrades[iTrade]['price'] = order_info['price']
                                            ts.costOut += order_info['cost']
                                            if trades is not None:
                                                order_info['amount'] = sum(
                                                    [tr['amount'] for tr in trades if tr['order'] == order_info['id']])
                                            ts.coinsAvail += ts.OutTrades[iTrade]['amount'] - order_info['amount']
                                            self.message(
                                                f"Sell order (level {iTrade} of trade set "
                                                f"{list(self.tradeSets.keys()).index(i_ts)} on {self.exchange.name}) "
                                                f"was canceled by exchange or someone else (reason: {reason}) but "
                                                f"already partly filled! Treating order as closed and updating trade "
                                                f"set info.")
                                        else:
                                            ts.OutTrades[iTrade]['oid'] = None
                                            ts.coinsAvail += ts.OutTrades[iTrade]['amount']
                                            self.message(
                                                f"Sell order (level {iTrade} of trade set "
                                                f"{list(self.tradeSets.keys()).index(i_ts)} on {self.exchange.name}) "
                                                f"was canceled by exchange or someone else (reason:{reason})! "
                                                f"Will be reinitialized during next update.")

                                except OrderNotFound:
                                    self.lock_trade_set(i_ts)
                                    self.message(
                                        f"Sell order id {ts.OutTrades[iTrade]['oid']} for trade set {ts.symbol} "
                                        f"not found on {self.exchange.name}! Maybe exchange API has changed? "
                                        f"Resetting order to 'not initiated'! If InsufficientFunds errors pop up, the "
                                        f"order had probably been executed. In this case please delete the trade set.",
                                        'error')
                                    ts.coinsAvail += ts.OutTrades[iTrade]['amount']
                                    ts.OutTrades[iTrade]['oid'] = None

                        # delete Tradeset when all orders have been filled (but only if there were any to execute
                        # and if no significant coin amount is left)
                        if not (self.num_buy_levels(i_ts, order='filled') + ts.initCoins):
                            significant_amount = np.inf
                        else:
                            significant_amount = (self.sum_buy_amounts(i_ts, order='filled') + ts.initCoins -
                                                  self.sum_sell_amounts(i_ts, order='filled')) / \
                                                 (ts.initCoins + self.sum_buy_amounts(i_ts, order='filled'))
                        if ((ts.SL is None and order_executed > 0) or (order_executed == 2 and
                                                                       significant_amount < 0.01)) and \
                                self.num_sell_levels(i_ts, 'notfilled') == 0 and \
                                self.num_buy_levels(i_ts, 'notfilled') == 0:
                            gain = self.cost2Prec(ts.symbol, ts.costOut - ts.costIn)
                            self.message('Trading set %s on %s completed! Total gain: %s %s' % (
                                ts.symbol, self.exchange.name, gain, ts.baseCurrency))
                            trade_sets_to_delete.append(i_ts)
                finally:
                    self.unlock_trade_set(i_ts)
        finally:
            # makes sure that the tradeSet deletion takes place even if some error occurred in another trade
            for i_ts in trade_sets_to_delete:
                self.create_trade_history_entry(i_ts)
                self.tradeSets.pop(i_ts)
            self.lastUpdate = time.time()
