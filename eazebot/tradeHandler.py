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
import logging
import ccxt
from json import JSONDecodeError
from inspect import getsourcefile, getsourcelines
import numpy as np
import time
import datetime
import sys
import os

import requests
from ccxt.base.errors import (AuthenticationError, NetworkError, OrderNotFound, InvalidNonce, ExchangeError,
                              InsufficientFunds)

from eazebot.handling import ValueType, Price, DailyCloseSL, WeeklyCloseSL, TrailingSL, BaseTradeSet, \
    NumberFormatter, ExchContainer, OrderType

logger = logging.getLogger(__name__)


class tradeHandler:
    def __init__(self, exch_name: str, user: str = None, *args):

        self.check_these = ['cancelOrder', 'createLimitOrder', 'fetchBalance', 'fetchTicker']
        self.tradeSets = {}
        self.tradeSetHistory = []
        if exch_name == 'kucoin2':
            exch_name = 'kucoin'
        self.exch_name = exch_name
        self.price_dict = {}
        self.updating = False
        self.waiting = []
        self.down = False
        self.authenticated = False
        self.balance = {}
        self.lastUpdate = time.time() - 10
        self.set_user(user)

    def __reduce__(self):
        # function needes for serializing the object
        if hasattr(self, 'exchange'):
            return (
                self.__class__, (self.exchange.__class__.__name__, ),
                self.__getstate__(),
                None, None)
        else:
            return (
                self.__class__, (self.exch_name,),
                self.__getstate__(),
                None, None)

    def __setstate__(self, state):
        if isinstance(state, tuple):
            state, tshs = state
        else:
            tshs = []
        for i_ts in state:  # temp fix for old trade sets that do not some of the newer fields
            if isinstance(state[i_ts], BaseTradeSet):
                state[i_ts].set_tradehandler(self)
            else:
                state[i_ts]['uid'] = i_ts
                ts = BaseTradeSet.from_dict(state[i_ts], trade_handler=self)
                state[i_ts] = ts
        self.tradeSets = state
        self.tradeSetHistory = tshs

    def __getstate__(self):
        if hasattr(self, 'tradeSetHistory'):
            return self.tradeSets, self.tradeSetHistory
        else:
            return self.tradeSets, []

    @staticmethod
    def check_num(*value):
        return all(
            [(isinstance(val, float) | isinstance(val, int)) if not isinstance(val, list) else
             tradeHandler.check_num(*val) for val in value])

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
            logger.warning('Exchange %s does not provide limits for %s' % (self.exchange.name, typ),
                           extra=self.logger_extras)
            return True

    def set_user(self, user: str):
        """
        Method required for backward compatibility if pickled tradeHandler is loaded which had no user info

        :param user: telegram chat ID of the user as string
        :return:
        """
        self.user = user
        if user is not None:
            self.exchange = ExchContainer(user).get(self.exch_name)
            self.nf = NumberFormatter(exchange=self.exchange)

            if not all([self.exchange.has[x] for x in self.check_these]):
                text = f"Exchange {self.exch_name} does not support all required features {', '.join(self.check_these)}"
                logger.error(text, extra=self.logger_extras)
                raise Exception(text)
            self.check_keys()
            self.logger_extras = {'chatId': user}
        else:
            self.logger_extras = {}

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
                        self.tradeSets[i_ts].unlock_trade_set()
                    if 'Cloudflare' in str(e):
                        if print_error:
                            logger.error('Cloudflare problem with exchange %s. Exchange is treated as down. %s' % (
                                self.exchange.name, '' if i_ts is None else 'TradeSet %d (%s)' % (
                                    list(self.tradeSets.keys()).index(i_ts), self.tradeSets[i_ts].symbol)),
                                         extra=self.logger_extras)
                    elif print_error:
                        logger.error('Network exception occurred 5 times in a row. %s is treated as down. %s' % (
                            self.exchange.name, '' if i_ts is None else 'TradeSet %d (%s)' % (
                                list(self.tradeSets.keys()).index(i_ts), self.tradeSets[i_ts].symbol)),
                                     extra=self.logger_extras)
                    raise e
                else:
                    time.sleep(0.5)
                    continue
            except OrderNotFound as e:
                count += 1
                if count >= 5:
                    if i_ts:
                        self.tradeSets[i_ts].unlock_trade_set()
                    if print_error:
                        logger.error(f"Order not found error 5 times in a row on {self.exchange.name}"
                                     '' if i_ts is None else
                                     f" for tradeSet {list(self.tradeSets.keys()).index(i_ts)} "
                                     f"({self.tradeSets[i_ts].symbol}", extra=self.logger_extras)
                    raise e
                else:
                    time.sleep(0.5)
                    continue
            except AuthenticationError as e:
                count += 1
                if count >= 5:
                    if i_ts:
                        self.tradeSets[i_ts].unlock_trade_set()
                    raise e
                else:
                    time.sleep(0.5)
                    continue
            except JSONDecodeError as e:
                if i_ts:
                    self.tradeSets[i_ts].unlock_trade_set()
                if 'Expecting value' in str(e):
                    self.down = True
                    if print_error:
                        logger.error('%s seems to be down.' % self.exchange.name, extra=self.logger_extras)
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
                        self.tradeSets[i_ts].unlock_trade_set()
                    stri = 'Exchange %s\n' % self.exchange.name
                    if count >= 5:
                        stri += 'Network exception occurred 5 times in a row! Last error was:\n'
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    # fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    lines = getsourcelines(func)
                    stri += '%s in %s from %s at line %d: %s' % (
                        exc_type, lines[0][0], os.path.basename(getsourcefile(func)), lines[1], str(e))

                    if print_error:
                        logger.error(stri, extra=self.logger_extras)
                    raise e
            finally:
                if wasdown and not self.down:
                    logger.info('Exchange %s seems back to work!' % self.exchange.name, extra=self.logger_extras)

    def get_price_obj(self, symbol: str):
        if symbol not in self.price_dict:
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(symbol))
            self.price_dict[symbol] = Price(symbol, current=ticker['last'], high=ticker['high'], low=ticker['low'])
        elif (datetime.datetime.now() - self.price_dict[symbol].time).seconds > 5:
            # update price
            ticker = self.safe_run(lambda: self.exchange.fetchTicker(symbol))
            self.price_dict[symbol].set_price(current=ticker['last'], high=ticker['high'], low=ticker['low'])
        return self.price_dict[symbol]

    def update_balance(self):
        self.update_down_state(True)
        # reloads the exchange market and private balance and, if successful, sets the exchange as authenticated
        self.safe_run(self.exchange.loadMarkets)
        self.balance = self.safe_run(self.exchange.fetch_balance)
        self.authenticated = True

    def get_balance(self, coin, balance_type='free'):
        assert balance_type in ['free', 'total'], f"Unknown balance type {balance_type}"
        if coin in self.balance:
            return self.balance[coin][balance_type]
        else:
            return 0

    def check_keys(self):
        try:  # check if keys work
            self.update_balance()
        except AuthenticationError:  #
            self.authenticated = False
            try:
                logger.error('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                             extra=self.logger_extras)
            except Exception:
                print('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name)
        except getattr(ccxt, 'ExchangeError') as e:
            self.authenticated = False
            if 'key' in str(e).lower():
                try:
                    logger.error('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                                 extra=self.logger_extras)
                except Exception:
                    print('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name)
            else:
                try:
                    logger.error('The following error occured at exchange %s:\n%s' % (self.exchange.name, str(e)),
                                 extra=self.logger_extras)
                except Exception:
                    print('The following error occured at exchange %s:\n%s' % (self.exchange.name, str(e)))

    def init_trade_set(self, symbol, add=True) -> BaseTradeSet:
        self.update_balance()

        ts = BaseTradeSet(symbol=symbol, trade_handler=self)

        while ts.get_uid() in self.tradeSets:
            ts = BaseTradeSet(symbol=symbol, trade_handler=self)
        if add:
            self.tradeSets[ts.get_uid()] = ts
        return ts

    def new_trade_set(self, symbol, buy_levels=None, buy_amounts=None, sell_levels=None, sell_amounts=None, sl=None,
                      sl_close=None,
                      candle_above=None,
                      init_coins=0, init_price=None, force=False) -> BaseTradeSet:
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

        ts = self.init_trade_set(symbol, add=False)

        # truncate values to precision
        sell_levels = [float(self.exchange.priceToPrecision(symbol, val)) for val in sell_levels]
        buy_levels = [float(self.exchange.priceToPrecision(symbol, val)) for val in buy_levels]
        sell_amounts = [float(self.exchange.amountToPrecision(symbol, val)) for val in sell_amounts]
        buy_amounts = [float(self.exchange.amountToPrecision(symbol, val)) for val in buy_amounts]

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
            logger.warning(
                'It seems the buy and sell amount of %s is not the same. Is this correct?' % ts.coinCurrency,
                extra=self.logger_extras)
        if buy_levels.size > 0 and sell_levels.size > 0 and max(buy_levels) > min(sell_levels):
            raise ValueError(
                'It seems at least one of your sell prices is lower than one of your buy, which does not make sense')

        if self.balance[ts.baseCurrency]['free'] < sum(buy_levels * buy_amounts):
            raise ValueError('Free balance of %s not sufficient to initiate trade set' % ts.baseCurrency)

        success = True
        # create the buy orders
        for n, _ in enumerate(buy_levels):
            success &= ts.add_buy_level(buy_levels[n], buy_amounts[n], candle_above[n])

        success &= ts.add_init_coins(init_price, init_coins)
        if sl_close is None:
            success &= ts.set_sl(sl)
        elif sl_close.lower() == 'daily':
            success &= ts.set_daily_close_sl(sl)
        elif sl_close.lower() == 'weekly':
            success &= ts.set_weekly_close_sl(sl)
        else:
            raise ValueError(f"Unknown value for argument sl_close: {sl_close}")
        # create the sell orders
        for n, _ in enumerate(sell_levels):
            success &= ts.add_sell_level(sell_levels[n], sell_amounts[n])

        if success:
            # add to the trade sets
            self.tradeSets[ts.get_uid()] = ts
        else:
            raise Exception('There was an error during trade set creation')
        ts.activate()
        self.update()
        return ts

    def get_trade_set_info(self, i_ts, show_profit_in=None):
        ts = self.tradeSets[i_ts]
        if ts.name is None:
            ts_name = f"Trade set #{list(self.tradeSets.keys()).index(i_ts)}"
        else:
            ts_name = ts.name

        prt_str = '*%s [%s]%s:*\n' % (ts_name, ts.symbol, ' INACTIVE' if not ts.is_active() else '')
        prt_str += f"Exchange: {self.exchange.name}{' (DOWN !!!) ' if self.down else ''}\n"

        filled_buys = []
        filled_sells = []
        if ts.regular_buy is not None:
            rb = ts.regular_buy
            if rb.interval.months:
                interval = 'month'
            elif rb.interval.weeks:
                interval = 'week'
            else:
                interval = 'day'
            prt_str += f"*Regular buy:* {rb.amount} {rb.currency} each {interval} using " \
                f"{rb.order_type.name.lower()} order. Next buy on **{rb.next_time.isoformat()}**\n"

        for iTrade, trade in enumerate(ts.in_trades):
            tmpstr = '*Buy level %d:* Price %s , Amount %s %s   ' % (
                iTrade, self.nf.price2Prec(ts.symbol, trade['price']), self.nf.amount2Prec(ts.symbol, trade['amount']),
                ts.coinCurrency)
            if trade['oid'] is None:
                if trade['candleAbove'] is None:
                    tmpstr = tmpstr + '_Order not initiated_\n'
                else:
                    tmpstr = tmpstr + 'if DC > %s\n' % self.nf.price2Prec(ts.symbol, trade['candleAbove'])
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                if trade['price'] is not None and trade['amount'] is not None:
                    filled_buys.append([trade['actualAmount'], trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            if ts.show_filled_orders or trade['oid'] != 'filled':
                prt_str += tmpstr
        prt_str += '\n'

        for iTrade, trade in enumerate(ts.out_trades):
            tmpstr = '*Sell level %d:* Price %s , Amount %s %s   ' % (
                iTrade, self.nf.price2Prec(ts.symbol, trade['price']), self.nf.amount2Prec(ts.symbol, trade['amount']),
                ts.coinCurrency)
            if trade['oid'] is None:
                tmpstr = tmpstr + '_Order not initiated_\n'
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                if trade['price'] is not None and trade['amount'] is not None:
                    filled_sells.append([trade['amount'], trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            if ts.show_filled_orders or trade['oid'] != 'filled':
                prt_str += tmpstr
        if ts.sl is not None:
            if isinstance(ts.sl, DailyCloseSL):
                prt_str += '\n*Stop-loss* set at daily close < %s\n\n' % (self.nf.price2Prec(ts.symbol, ts.sl.value))
            elif isinstance(ts.sl, WeeklyCloseSL):
                prt_str += '\n*Stop-loss* set at weekly close < %s\n\n' % (
                    self.nf.price2Prec(ts.symbol, ts.sl.value))
            else:
                prt_str += '\n*Stop-loss* set at %s%s\n\n' % (self.nf.price2Prec(ts.symbol, ts.sl.value),
                                                              '' if not isinstance(ts.sl, TrailingSL) else (
                                                                  ' (trailing with offset %.5g)' % ts.sl.delta if
                                                                  ts.sl.kind == ValueType.ABSOLUTE else
                                                                  ' (trailing with offset %.2g %%)' % (
                                                                          ts.sl.delta * 100)))
        else:
            prt_str += '\n*No stop-loss set.*\n\n'
        sum_buys = sum([val[0] for val in filled_buys])
        sum_sells = sum([val[0] for val in filled_sells])
        if ts.init_coins > 0:
            prt_str += '*Initial coins:* %s %s for an average price of %s\n' % (
                self.nf.amount2Prec(ts.symbol, ts.init_coins), ts.coinCurrency,
                self.nf.price2Prec(ts.symbol, ts.init_price) if ts.init_price is not None else 'unknown')
        if sum_buys > 0:
            prt_str += '*Filled buy orders (fee subtracted):* %s %s for an average price of %s\n' % (
                self.nf.amount2Prec(ts.symbol, sum_buys), ts.coinCurrency, self.nf.cost2Prec(ts.symbol, sum(
                    [val[0] * val[1] / sum_buys if sum_buys > 0 else None for val in filled_buys])))
        if sum_sells > 0:
            prt_str += '*Filled sell orders:* %s %s for an average price of %s\n' % (
                self.nf.amount2Prec(ts.symbol, sum_sells), ts.coinCurrency, self.nf.cost2Prec(ts.symbol, sum(
                    [val[0] * val[1] / sum_sells if sum_sells > 0 else None for val in filled_sells])))
        if self.exchange.markets[ts.symbol]['active']:
            price_obj = self.get_price_obj(ts.symbol)
            prt_str += '\n*Current market price *: %s, \t24h-high: %s, \t24h-low: %s\n' % tuple(
                [self.nf.price2Prec(ts.symbol, val) for val in
                 [price_obj.get_current_price(), price_obj.get_high_price(), price_obj.get_low_price()]])
            if (ts.init_coins == 0 or ts.init_price is not None) and ts.cost_in() > 0 and (
                    sum_buys > 0 or ts.init_coins > 0):
                total_amount_to_sell = ts.coins_avail() + ts.sum_sell_amounts('open')
                fee = self.exchange.calculate_fee(ts.symbol, 'market', 'sell', total_amount_to_sell,
                                                  price_obj.get_current_price(), 'taker')
                cost_sells = ts.cost_out() + price_obj.get_current_price() * total_amount_to_sell - (
                    fee['cost'] if fee['currency'] == ts.baseCurrency else 0)
                gain = cost_sells - ts.cost_in()
                gain_orig = gain
                if show_profit_in is not None:
                    gain, this_cur = self.convert_amount(gain, ts.baseCurrency, show_profit_in)
                else:
                    this_cur = ts.baseCurrency
                prt_str += '\n*Estimated gain/loss when selling all now: * %s %s (%+.2f %%)\n' % (
                    self.nf.cost2Prec(ts.symbol, gain), this_cur, gain_orig / ts.cost_in() * 100)
        else:
            prt_str += '\n*Warning: Symbol %s is currently deactivated for trading by the exchange!*\n' % ts.symbol
        return prt_str

    def create_trade_history_entry(self, i_ts):
        self.update_down_state(True)
        # create a trade history entry if the trade set had any filled orders
        ts = self.tradeSets[i_ts]
        if ts.num_buy_levels('filled') > 0 or ts.num_sell_levels('filled') > 0:
            gain = ts.cost_out() - ts.cost_in()
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
                                         'days': (time.time() - ts.createdAt) / 60 / 60 / 24,
                                         'symbol': ts.symbol, 'gain': gain,
                                         'gainRel': gain / ts.cost_in() * 100 if ts.cost_in() > 0 else None,
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
            Avg. relative gain: {np.mean([tsh['gainRel'] for tsh in self.tradeSetHistory if tsh['gainRel'] is not None]):+7.1f}%\n\
            Total profit in BTC: {sum([tsh['gainBTC'] if tsh['gainBTC'] else 0 for tsh in self.tradeSetHistory]):+.5f}\n \
            Total profit in USD: {sum([tsh['gainUSD'] if tsh['gainUSD'] else 0 for tsh in self.tradeSetHistory]):+.2f}\n \
            \nDetailed Set Info:\n*" + string
        else:
            return '*No profit history on %s*' % self.exchange.name

    def reset_trade_history(self):
        self.tradeSetHistory = []
        logger.info('Trade set history on %s cleared' % self.exchange.name, extra=self.logger_extras)
        return 1

    def is_paid_by_exchange_token(self, cost: float, fee_currency: str):
        """
        Method to check if paying trading fees with an exchange token is set and balance is sufficient

        :param cost: cost of the trading fee to be paid
        :param fee_currency: Currency name in which the fees are paid
        :return:
        """
        try:
            if self.exchange.name.lower() == 'binance':
                if self.exchange.request('bnbBurn', api='sapi', method='GET')['spotBNBBurn']:
                    # if paying fees via BNB is active, check current market price of bnb and if there is enough bnb
                    # to pay the fee
                    fee_in_bnb = requests.get('https://min-api.cryptocompare.com/data/price',
                                              params={'fsym': fee_currency, 'tsyms': 'BNB'}).json()['BNB'] * cost
                    # add a factor of 5 to the fee to avoid problems with bnb market fluctuations, and multiple
                    # orders that are set
                    if 5 * fee_in_bnb < self.get_balance('BNB'):
                        return True
            elif self.exchange.name.lower() == 'kucoin':
                # yet it is not possible to check via API if fees are paid via kcs...
                pass
        except Exception as e:
            logger.error(f'Failed to check for fee payment:\n{e}',
                         extra=self.logger_extras)
        return False

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
                amount *= self.get_price_obj(f'{currency}/{this_cur}').get_current_price()
            else:
                amount /= self.get_price_obj(f'{this_cur}/{currency}').get_current_price()
            return amount, this_cur
        else:
            return amount, currency

    def delete_trade_set(self, i_ts, sell_all=False):
        self.update_down_state(True)
        ts = self.tradeSets[i_ts]
        ts.lock_trade_set()
        if sell_all:
            sold = ts.sell_all_now()
        else:
            sold = True
            ts.deactivate(1)
        if sold:
            gain_coins = self.nf.cost2Prec(ts.symbol, ts.cost_out() - ts.cost_in())
            logger.info('Trading set %s on %s completed! Total gain: %s %s and %s leftover %ss' % (
                ts.symbol, self.exchange.name, gain_coins, ts.baseCurrency,
                self.nf.cost2Prec(ts.symbol, ts.coins_avail()), ts.coinCurrency), extra=self.logger_extras)
            self.create_trade_history_entry(i_ts)
            self.tradeSets.pop(i_ts)
        else:
            self.tradeSets[i_ts].unlock_trade_set()

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
                logger.error('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                             extra=self.logger_extras)
                return
            except ccxt.ExchangeError as e:  #
                if 'key' in str(e).lower():
                    logger.error('Failed to authenticate at exchange %s. Please check your keys' % self.exchange.name,
                                 extra=self.logger_extras)
                else:
                    self.down = True
                    logger.error('Some error occured at exchange %s. Maybe it is down.' % self.exchange.name,
                                 extra=self.logger_extras)
                return

        trade_sets_to_delete = []
        try:
            for indTs, i_ts in enumerate(self.tradeSets):
                ts = self.tradeSets[i_ts]
                try:
                    if not ts.is_active():
                        continue
                    ts.lock_trade_set()
                    price_obj = self.get_price_obj(ts.symbol)  # get and update the price
                    # check if stop loss is reached
                    if special_check < 2:
                        if ts.sl is not None:
                            if ts.sl.is_below(price_obj):
                                if isinstance(ts.sl, WeeklyCloseSL):
                                    msg = 'Weekly candle'
                                elif isinstance(ts.sl, DailyCloseSL):
                                    msg = 'Daily candle'
                                else:
                                    msg = 'Price'
                                logger.warning(msg + ' closed below chosen SL of %s for pair %s! Selling now!' % (
                                    self.nf.price2Prec(ts.symbol, ts.sl.value), ts.symbol), extra=self.logger_extras)
                                # cancel all sell orders, create market sell order, save resulting amount of currency
                                sold = ts.sell_all_now(price=price_obj.get_current_price())
                                if sold:
                                    trade_sets_to_delete.append(i_ts)
                                    ts.unlock_trade_set()
                                    continue

                    else:  # tax warning check
                        for iTrade, trade in enumerate(ts.in_trades):
                            if 'time' in trade and (datetime.datetime.now() - trade['time']).days > 358 and (
                                    datetime.datetime.now() - trade['time']).days < 365:
                                logger.warning(
                                    f"Time since buy level #{iTrade} of trade set {ts.name} ({ts.symbol}) on "
                                    f"exchange {self.exchange.name} was filled approaches one year "
                                    f"({(trade['time'] + datetime.timedelta(days=365)).strftime('%Y-%m-%d %H:%M')}) "
                                    f"after which gains/losses are not eligible for reporting in the tax report in most"
                                    f" countries!", extra=self.logger_extras)
                        continue

                    if ts.regular_buy is not None:
                        rb = ts.regular_buy
                        if rb.next_order_due():
                            msg = f"Time due for next regular buy. "
                            if rb.currency == ts.coinCurrency:
                                msg += f"Buying {rb.amount} {rb.currency} from {ts.symbol}"
                            else:
                                msg += f"Using {rb.amount} {rb.currency} to buy {ts.coinCurrency}"

                            if rb.order_type == OrderType.MARKET:
                                logger.info(f"{msg} at market price.", extra=self.logger_extras)
                                ts.do_market_buy(amount=float(self.exchange.amountToPrecision(ts.symbol, rb.amount)),
                                                 currency=rb.currency, lock=False)
                            elif rb.order_type == OrderType.LIMIT:
                                logger.info(f"{msg} with near-to-market-price limit order.", extra=self.logger_extras)
                                # try to buy with a 0.2% discount from current price to avoid maker fee
                                price = price_obj.get_current_price() * 0.998
                                if rb.currency == ts.coinCurrency:
                                    amount = rb.amount
                                else:
                                    amount = rb.amount / price
                                ts.add_buy_level(buy_price=price,
                                                 buy_amount=float(self.exchange.amountToPrecision(ts.symbol, amount)),
                                                 lock=False)
                            else:
                                raise ValueError('Unknown order type')

                    order_executed = 0
                    # go through buy trades 
                    for iTrade, trade in enumerate(ts.in_trades):
                        if trade['oid'] == 'filled':
                            continue
                        elif special_check == 1 and trade['oid'] is None and trade['candleAbove'] is not None:
                            if price_obj.get_current_price() > trade['candleAbove']:
                                response = self.safe_run(
                                    lambda: self.exchange.createLimitBuyOrder(ts.symbol, trade['amount'],
                                                                              trade['price']), i_ts=i_ts)
                                ts.in_trades[iTrade]['oid'] = response['id']
                                logger.info('Daily candle of %s above %s triggering buy level #%d on %s!' % (
                                    ts.symbol, self.nf.price2Prec(ts.symbol, trade['candleAbove']), iTrade,
                                    self.exchange.name), extra=self.logger_extras)
                        elif trade['oid'] is not None:
                            try:
                                order_info = ts.fetch_order(trade['oid'], 'BUY')
                                # fetch trades for all orders because a limit order might also be filled at a lower val
                                if order_info['status'].lower() in ['closed', 'filled', 'canceled'] and \
                                        self.exchange.has['fetchMyTrades'] != False:
                                    trades = self.exchange.fetchMyTrades(ts.symbol)
                                    order_info['cost'] = sum(
                                        [tr['cost'] for tr in trades if tr['order'] == order_info['id']])

                                    if order_info['type'].lower() == 'market':
                                            amount = sum([tr['amount'] for tr in trades if tr['order'] == order_info['id']])
                                            fee = sum(
                                                [tr['fee']['cost'] for tr in trades if tr['order'] ==
                                                 order_info['id'] and tr['fee']['currency'] == ts.coinCurrency])
                                            trade['amount'] = amount
                                            trade['actualAmount'] = amount - fee

                                    if order_info['cost'] == 0:
                                        order_info['price'] = None
                                    else:
                                        order_info['price'] = np.mean(
                                            [tr['price'] for tr in trades if tr['order'] == order_info['id']])
                                else:
                                    trades = None
                                    if order_info['type'].lower() == 'market':
                                        # update the values of the market order as they depended on the market price.
                                        # checking the trades is better but if it is not available, use what is there...
                                        trade['amount'] = order_info['amount']
                                        trade['actualAmount'] = order_info['amount']
                                        if order_info['fee']['currency'] == ts.coinCurrency:
                                            trade['actualAmount'] -= order_info['fee']['cost']
                                        order_info['price'] = order_info['average']

                                if order_info['status'].lower() in ['closed', 'filled']:
                                    order_executed = 1
                                    trade['oid'] = 'filled'
                                    trade['time'] = datetime.datetime.now()
                                    trade['price'] = order_info['price']
                                    logger.info('Buy level of %s %s reached on %s! Bought %s %s for %s %s.' % (
                                        self.nf.price2Prec(ts.symbol, order_info['price']), ts.symbol,
                                        self.exchange.name,
                                        self.nf.amount2Prec(ts.symbol, order_info['amount']), ts.coinCurrency,
                                        self.nf.cost2Prec(ts.symbol, order_info['cost']), ts.baseCurrency),
                                                extra=self.logger_extras)
                                elif order_info['status'] == 'canceled':
                                    if 'reason' in order_info['info']:
                                        reason = order_info['info']['reason']
                                    else:
                                        reason = 'N/A'
                                    cancel_msg = f"Buy order (level {iTrade} of trade set " \
                                        f"{list(self.tradeSets.keys()).index(i_ts)} on {self.exchange.name}) was " \
                                        f"canceled by exchange or someone else (reason: {reason}) "
                                    if order_info['cost'] > 0:
                                        ts.in_trades[iTrade]['oid'] = 'filled'
                                        ts.in_trades[iTrade]['price'] = order_info['price']
                                        if trades is not None:
                                            order_info['amount'] = sum(
                                                [tr['amount'] for tr in trades if tr['order'] == order_info['id']])
                                        logger.error(cancel_msg + 'but already partly filled! Treating '
                                                                  'order as closed and updating trade set info.',
                                                     extra=self.logger_extras)
                                    else:
                                        ts.in_trades[iTrade]['oid'] = None
                                        logger.error(cancel_msg + 'Will be reinitialized during next update.',
                                                     extra=self.logger_extras)

                            except OrderNotFound:
                                ts.lock_trade_set()
                                logger.error(
                                    f"Buy order id {ts.in_trades[iTrade]['oid']} for trade set {ts.symbol} not "
                                    f"found on {self.exchange.name}! Maybe exchange API has changed? Resetting order to"
                                    f" 'not initiated', will be initiated on next trade set update!",
                                    extra=self.logger_extras)
                                ts.in_trades[iTrade]['oid'] = None

                        else:
                            ts.init_buy_orders()
                            time.sleep(1)

                    if not special_check:
                        # go through all selling positions and create those for which the bought coins suffice
                        for iTrade, _ in enumerate(ts.out_trades):
                            if ts.out_trades[iTrade]['oid'] is None and ts.coins_avail() >= \
                                    ts.out_trades[iTrade]['amount']:
                                try:
                                    response = self.safe_run(lambda: self.exchange.createLimitSellOrder(ts.symbol,
                                                                                                        ts.out_trades[
                                                                                                            iTrade][
                                                                                                            'amount'],
                                                                                                        ts.out_trades[
                                                                                                            iTrade][
                                                                                                            'price']),
                                                             i_ts=i_ts)
                                except InsufficientFunds as e:
                                    ts.deactivate()
                                    logger.error(f"Insufficient funds on exchange {self.exchange.name} for trade set "
                                                 f"#{list(self.tradeSets.keys()).index(i_ts)}. Trade set is deactivated"
                                                 f" now and not updated anymore (open orders are still open)! "
                                                 f"Free the missing funds and reactivate. \n {e}.",
                                                 extra=self.logger_extras)

                                    raise e
                                ts.out_trades[iTrade]['oid'] = response['id']
                        # go through sell trades
                        for iTrade, trade in enumerate(ts.out_trades):
                            if trade['oid'] == 'filled':
                                continue
                            elif trade['oid'] is not None:
                                try:
                                    order_info = ts.fetch_order(trade['oid'], 'SELL')
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
                                        ts.out_trades[iTrade]['oid'] = 'filled'
                                        ts.out_trades[iTrade]['time'] = datetime.datetime.now()
                                        ts.out_trades[iTrade]['price'] = order_info['price']
                                        logger.info('Sell level of %s %s reached on %s! Sold %s %s for %s %s.' % (
                                            self.nf.price2Prec(ts.symbol, order_info['price']), ts.symbol,
                                            self.exchange.name, self.nf.amount2Prec(ts.symbol, order_info['amount']),
                                            ts.coinCurrency, self.nf.cost2Prec(ts.symbol, order_info['cost']),
                                            ts.baseCurrency), extra=self.logger_extras)
                                    elif order_info['status'] == 'canceled':
                                        if 'reason' in order_info['info']:
                                            reason = order_info['info']['reason']
                                        else:
                                            reason = 'N/A'
                                        if order_info['cost'] > 0:
                                            ts.out_trades[iTrade]['oid'] = 'filled'
                                            ts.out_trades[iTrade]['price'] = order_info['price']
                                            if trades is not None:
                                                order_info['amount'] = sum(
                                                    [tr['amount'] for tr in trades if tr['order'] == order_info['id']])
                                            ts.out_trades[iTrade]['amount'] = order_info['amount']
                                            logger.error(
                                                f"Sell order (level {iTrade} of trade set "
                                                f"{list(self.tradeSets.keys()).index(i_ts)} on {self.exchange.name}) "
                                                f"was canceled by exchange or someone else (reason: {reason}) but "
                                                f"already partly filled! Treating order as closed and updating trade "
                                                f"set info.", extra=self.logger_extras)
                                        else:
                                            ts.out_trades[iTrade]['oid'] = None
                                            logger.error(
                                                f"Sell order (level {iTrade} of trade set "
                                                f"{list(self.tradeSets.keys()).index(i_ts)} on {self.exchange.name}) "
                                                f"was canceled by exchange or someone else (reason:{reason})! "
                                                f"Will be reinitialized during next update.", extra=self.logger_extras)

                                except OrderNotFound:
                                    ts.lock_trade_set()
                                    logger.error(
                                        f"Sell order id {ts.out_trades[iTrade]['oid']} for trade set {ts.symbol} "
                                        f"not found on {self.exchange.name}! Maybe exchange API has changed? "
                                        f"Resetting order to 'not initiated'! If InsufficientFunds errors pop up, the "
                                        f"order had probably been executed. In this case please delete the trade set.",
                                        extra=self.logger_extras)
                                    ts.out_trades[iTrade]['oid'] = None

                        # delete Tradeset when all orders have been filled (but only if there were any to execute
                        # and if no significant coin amount is left)
                        left_coins = ts.sum_buy_amounts(order='filled') + ts.init_coins - \
                                     ts.sum_sell_amounts(order='filled')
                        if not (ts.num_buy_levels(order='filled') + ts.init_coins):
                            significant_amount = np.inf
                        else:
                            significant_amount = left_coins / (left_coins + ts.sum_sell_amounts(order='filled'))
                        if ts.regular_buy is None and ((ts.sl is None and order_executed > 0) or
                                                       (order_executed == 2 and significant_amount < 0.01)) and \
                                ts.num_sell_levels('notfilled') == 0 and \
                                ts.num_buy_levels('notfilled') == 0:

                            trade_sets_to_delete.append(i_ts)
                finally:
                    ts.unlock_trade_set()
        finally:
            # makes sure that the tradeSet deletion takes place even if some error occurred in another trade
            for i_ts in trade_sets_to_delete:
                self.delete_trade_set(i_ts, sell_all=False)
            self.lastUpdate = time.time()
