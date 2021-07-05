import datetime
import random

import ccxt
from dateparser import parse as dateparse
from ccxt import InsufficientFunds, OrderNotFound, ExchangeError
import numpy as np
import re
import string
import time
from enum import Flag, auto
from typing import Union, Dict, Optional
import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext.filters import MessageFilter

if TYPE_CHECKING:
    from .tradeHandler import tradeHandler

logger = logging.getLogger(__name__)


class ExchContainer:
    _saved_instances = {}

    def __new__(cls, user=None):
        if not user in cls._saved_instances:
            cls._saved_instances[user] = super().__new__(cls)
        return cls._saved_instances[user]

    def __init__(self, user=None):
        if not hasattr(self, 'exchanges'):
            self.exchanges = {}
            self.logger_extras = {'chatId': user}

    def add(self, exch_name, key, secret=None, password=None, uid=None):
        self.exchanges[exch_name] = getattr(ccxt, exch_name)({'enableRateLimit': True, 'options': {
                'adjustForTimeDifference': True}})  # 'nonce': ccxt.Exchange.milliseconds,
        exchange = self.exchanges[exch_name]
        if key:
            exchange.apiKey = key
        if secret:
            exchange.secret = secret
        if password:
            exchange.password = password
        if uid:
            exchange.uid = uid

    def get(self, exch_name: str) -> ccxt.Exchange:
        if exch_name in self.exchanges:
            return self.exchanges[exch_name]
        else:
            raise ValueError(f"Exchange {exch_name} has not been initialized yet. Missing api credentials?")


class TempTradeSet:
    def __init__(self):
        self.amount = None
        self.coin_or_base = 0
        self.__price = None
        self.__reg_buy = False
        self.add_params = {}

    @property
    def reg_buy(self):
        return self.__reg_buy

    @reg_buy.setter
    def reg_buy(self, reg_buy):
        if self.price is None or reg_buy is False:
            self.__reg_buy = reg_buy
        else:
            raise ValueError('Regular buy cannot be set, if price is already set')

    @property
    def price(self):
        return self.__price

    @price.setter
    def price(self, price):
        if self.reg_buy is False or price is None:
            self.__price = price
        else:
            raise ValueError('Price cannot be set, if regular buy is True')


class DateFilter(MessageFilter):
    """
    Filters updates by checking if message can be parsed into a date.

    """

    def __call__(self, update: Update) -> Optional[Union[bool, Dict]]:
        pass

    name = 'Filters.date'

    def filter(self, message):
        try:
            parsed = dateparse(message.text)
        except Exception:
            return False
        if parsed is None:
            return False
        return True


class SLType(Flag):
    DEFAULT = auto()
    TRAILING = auto()
    DAILYCLOSE = auto()
    WEEKLYCLOSE = auto()


class ValueType(Flag):
    ABSOLUTE = auto()
    RELATIVE = auto()


class OrderType(Flag):
    MARKET = auto()
    LIMIT = auto()


class NumberFormatter:
    def __init__(self, exchange):
        self.exchange = exchange
        self.amount2Prec = lambda a, b: self.x_to_prec(a, b, 'amount')
        self.price2Prec = lambda a, b: self.x_to_prec(a, b, 'price')
        self.cost2Prec = lambda a, b: self.x_to_prec(a, b, 'cost')
        self.fee2Prec = lambda a, b: self.x_to_prec(a, b, 'fee')

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


class Price:
    def __init__(self, currency, current: float, price_time: datetime.datetime = None, high: float = None,
                 low: float = None):
        self.current_price = current
        self.high_price = high
        self.low_price = low
        if price_time is None:
            price_time = datetime.datetime.now()
        self.time = price_time
        self.currency = currency

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


class Question:
    def __init__(self, name, question, answer_type):
        self.name = name
        self.question = question
        self.answer_type = answer_type
        self.answer = None


class OrderDialog:
    def __init__(self):
        self.dialog = [
            Question('amount', 'bla', 'number')
        ]
        self.currency = None


class BuyDialog(OrderDialog):
    def __init__(self):
        super().__init__()
        self.dialog.append(Question('candle_above', 'bla', 'bool'))
        self.dialog.append(Question('price', 'bla', 'number'))


class SellDialog(OrderDialog):
    def __init__(self):
        super().__init__()
        self.dialog.append(Question('price', 'bla', 'number'))


class RegularBuyDialog(OrderDialog):
    def __init__(self):
        super().__init__()
        self.dialog.append(Question('start_date', 'bla', 'date'))
        self.dialog.append(Question('interval', 'bla', 'str'))
        self.dialog.append(Question('order_type', 'bla', 'str'))


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


class RegularBuy:
    def __init__(self, amount: float, currency: str, order_type: OrderType,
                 interval: datetime.timedelta, start: datetime.datetime):
        self.amount = amount
        self.currency = currency
        self.order_type = order_type
        self.interval = interval
        self.next_time = start

    def next_order_due(self) -> bool:
        """

        :param price: current price object
        :return: amount to buy or None if no buy is due
        """
        now = datetime.datetime.now()
        if self.next_time <= now:
            # loop to avoid arbitrary number of buys if e.g. app was stopped for a while, and to calculate the next time
            while True:
                # this also sets the next time
                self.next_time += self.interval
                if self.next_time > now:
                    break
            return True
        return False


class BaseTradeSet:

    attributes_to_save = ('__active', '__virgin', 'in_trades', 'out_trades', 'createdAt', 'init_coins', 'init_price',
                          'sl', 'show_filled_orders', 'regular_buy')

    def __init__(self, symbol: str,
                 trade_handler: 'tradeHandler' = None,
                 uid: str = None,
                 name: str = None):
        """

        Base class for trade sets.

        :param symbol: String in the form 'XXX/YYY' defining the trading pair of the trade set
        :param trade_handler: TradeHandler class for accessing exchange etc
        :param uid: Optional unique id of the trade set. Will be created if not given
        :param name: Optional name of the trade set
        """

        if uid is None:
            random.seed()
            uid = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))

        self.name = name
        self._uid = uid
        self.in_trades = []
        self.out_trades = []
        self.regular_buy = None
        self.show_filled_orders = True
        self.createdAt = time.time()

        self.symbol = symbol
        self.baseCurrency = re.search("(?<=/).*", symbol).group(0)
        self.coinCurrency = re.search(".*(?=/)", symbol).group(0)
        self.init_coins = 0
        self.init_price = None
        self.sl = None
        self.__active = False
        self.__virgin = True
        self.updating = False
        self.waiting = []
        self.th = trade_handler

        if self.th is None or self.th.safe_run is None:
            def safe_run_func(x, print_error=None, i_ts=None):
                return x()
            self.safe_run = safe_run_func
        else:
            self.safe_run = self.th.safe_run

    @classmethod
    def from_dict(cls, ts_dict: Dict, trade_handler: 'tradeHandler'):

        ts = cls(symbol=ts_dict['symbol'], trade_handler=trade_handler, uid=ts_dict['uid'])
        for key in ts_dict:
            if key == 'SL':
                if ts_dict['trailingSL'] != [None, None]:
                    sl = TrailingSL(ts_dict['trailingSL'][0],
                                    ValueType.ABSOLUTE if ts_dict['trailingSL'][1] == 'abs'
                                    else ValueType.RELATIVE)
                elif ts_dict['weeklycloseSL'] is not None:
                    sl = WeeklyCloseSL(value=ts_dict['dailycloseSL'])
                elif ts_dict['dailycloseSL'] is not None:
                    sl = DailyCloseSL(value=ts_dict['dailycloseSL'])
                elif ts_dict['SL'] is not None:
                    sl = BaseSL(value=ts_dict['SL'])
                else:
                    sl = None
                ts.sl = sl
            elif key in ['trailingSL', 'dailycloseSL', 'weeklycloseSL', 'waiting', 'updating',
                         'noUpdateAfterEdit', 'uid']:
                # SLs are handled above, waiting and updating should not be used from a saved trade set
                continue
            elif key == 'active':
                ts.__active = ts_dict[key]
            elif key == 'virgin':
                ts.__virgin = ts_dict[key]
            elif hasattr(ts, key):
                setattr(ts, key, ts_dict[key])
            else:
                raise Exception()
        return ts

    def __reduce__(self):
        # function needed for serializing the object
        return (
            self.__class__, (self.symbol, None, self.get_uid(), self.name),
            self.__getstate__(),
            None, None)

    def __setstate__(self, state):

        # assign states
        if isinstance(state, tuple):
            # backward compatibility
            # supplement with default values
            defaults = (False, False, [], [], time.time(), 0, 0, 0, 0, None, None, True, None)
            state = state + defaults[len(state):]
            self.__active, self.__virgin, self.in_trades, self.out_trades, self.createdAt, _, _, \
            _, self.init_coins, self.init_price, self.sl, self.show_filled_orders, self.regular_buy = state
        elif isinstance(state, dict):
            for key in self.attributes_to_save:
                setattr(self, key if not key.startswith('__') else f'_BaseTradeSet{key}', state[key])
        else:
            raise TypeError(f'Unknown state type {type(state)}')

    def __getstate__(self):
        state = {}
        for key in self.attributes_to_save:
            state[key] = getattr(self, key if not key.startswith('__') else f'_BaseTradeSet{key}')
        return state

    def set_tradehandler(self, trade_handler: 'tradeHandler'):
        self.th = trade_handler
        if self.th is None or self.th.safe_run is None:
            def safe_run_func(x, print_error=None, i_ts=None):
                return x()
            self.safe_run = safe_run_func
        else:
            self.safe_run = self.th.safe_run

    def is_virgin(self):
        return self.__virgin

    def get_uid(self):
        return self._uid

    def lock_trade_set(self):
        # avoids two processes changing a tradeset at the same time
        count = 0
        mystamp = time.time()
        self.waiting.append(mystamp)
        time.sleep(0.2)
        while self.updating or self.waiting[0] < mystamp:
            count += 1
            time.sleep(1)
            if count > 60:  # 60 sec max wait
                logger.warning(
                    'Waiting for tradeSet update (%s on %s) to finish timed out after 1 min.. '
                    'Resetting updating variable now.' % (
                        self.symbol, self.th.exchange.name))
                break
        self.updating = True
        self.waiting.remove(mystamp)

    def unlock_trade_set(self):
        self.updating = False

    def is_active(self):
        return self.__active

    def activate(self, verbose=True) -> bool:
        self.th.update_down_state(True)
        wasactive = self.__active
        # check if symbol is active
        if not self.th.exchange.markets[self.symbol]['active']:
            logger.error(
                'Cannot activate trade set because %s was deactivated for trading by the exchange!' % self.symbol,
                extra=self.th.logger_extras)
            return wasactive
        # sanity check of amounts to buy/sell
        if self.sum_sell_amounts('notinitiated') - (self.sum_buy_amounts('notfilled') + self.coins_avail()) > 0:
            logger.error(
                f"Cannot activate trade set because the total amount you (still) want to sell "
                f"({self.th.nf.amount2Prec(self.symbol, self.sum_sell_amounts('notinitiated', True))} "
                f"{self.coinCurrency}) exceeds the total amount you want to buy "
                f"({self.th.nf.amount2Prec(self.symbol, self.sum_buy_amounts('notfilled', True))} {self.coinCurrency} "
                f"after fee subtraction) and the amount you already have in this trade set "
                f"({self.th.nf.amount2Prec(self.symbol, self.coins_avail())} {self.coinCurrency}). "
                f"Please adjust the trade set!", extra=self.th.logger_extras)
            return wasactive
        elif self.min_buy_price(order='notfilled') is not None and self.sl is not None and self.sl.value \
                >= self.min_buy_price(order='notfilled'):
            logger.error(
                'Cannot activate trade set because the current stop loss price is higher than the lowest non-filled buy'
                ' order price, which means this buy order could never be reached. Please adjust the trade set!',
                extra=self.th.logger_extras)
            return wasactive
        self.__virgin = False
        self.__active = True
        if verbose and not wasactive:
            total_buy_cost = self.cost_in() + self.sum_buy_costs('notfilled')
            prt_str = 'Estimated return if all trades are executed: %s %s' % (
                self.th.nf.cost2Prec(self.symbol, self.sum_sell_costs() - total_buy_cost), self.baseCurrency)
            left_coins = self.th.nf.amount2Prec(self.symbol, self.sum_buy_amounts() + self.init_coins -
                                                self.sum_sell_amounts())
            if float(left_coins):
                prt_str += ', and %s of leftover %ss' % (left_coins, self.coinCurrency)
            prt_str += '\n'
            logger.info(prt_str, extra = self.th.logger_extras)

            if self.sl is not None or isinstance(self.sl, DailyCloseSL):
                loss = total_buy_cost - self.cost_out() - (
                        self.init_coins + self.sum_buy_amounts() - self.sum_sell_amounts('filled')) * self.sl.value
                logger.info('Estimated %s if stop-loss is reached: %s %s' % (
                    '*gain*' if loss < 0 else 'loss', self.th.nf.cost2Prec(self.symbol, -loss if loss < 0 else loss),
                    self.baseCurrency), extra=self.th.logger_extras)
        try:
            self.init_buy_orders()
        except InsufficientFunds:
            logger.error('Cannot activate trade set due to insufficient funds!',
                         extra=self.th.logger_extras)
            self.deactivate()
        return wasactive

    def deactivate(self, cancel_orders=0):
        self.th.update_down_state(True)
        # cancelOrders can be 0 (not), 1 (cancel), 2 (cancel and delete open orders)
        wasactive = self.__active
        if cancel_orders:
            self.cancel_buy_orders(delete_orders=cancel_orders == 2)
            self.cancel_sell_orders(delete_orders=cancel_orders == 2)
        self.__active = False
        return wasactive

    def num_buy_levels(self, order='all'):
        return self.get_trade_param('amount', 'num', 'buy', order)

    def num_sell_levels(self, order='all'):
        return self.get_trade_param('amount', 'num', 'sell', order)

    def sum_buy_amounts(self, order='all', subtract_fee=True):
        return self.get_trade_param('amount', 'sum', 'buy', order, subtract_fee)

    def coins_avail(self):
        return self.sum_buy_amounts(order='filled', subtract_fee=True) + self.init_coins - \
               self.sum_sell_amounts(order='open', subtract_fee=False)

    def sum_sell_amounts(self, order='all', subtract_fee=True):
        return self.get_trade_param('amount', 'sum', 'sell', order, subtract_fee)

    def sum_buy_costs(self, order='all', subtract_fee=True):
        return self.get_trade_param('cost', 'sum', 'buy', order, subtract_fee)

    def cost_in(self):
        return self.sum_buy_costs(order='filled', subtract_fee=True) + \
               ((self.init_coins * self.init_price) if self.init_price is not None else 0)

    def sum_sell_costs(self, order='all', subtract_fee=True):
        return self.get_trade_param('cost', 'sum', 'sell', order, subtract_fee)

    def cost_out(self):
        return self.sum_sell_costs(order='filled', subtract_fee=True)

    def min_buy_price(self, order='all'):
        return self.get_trade_param('price', 'min', 'buy', order)

    def get_trade_param(self, what, method, direction, order='all', subtract_fee=True):
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
            trades = self.out_trades
        else:
            trades = self.in_trades

        if order not in ['all', 'filled', 'open', 'notfilled', 'notinitiated']:
            raise ValueError('order has to be all, filled, notfilled, notinitiated or open')

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
            
    def sell_all_now(self, price=None):
        self.th.update_down_state(True)
        self.deactivate(2)
        self.sl = None  # necessary to not retrigger SL
        sold = True
        if self.coins_avail() > 0 and self.th.check_quantity(self.symbol, 'amount', self.coins_avail()):
            if self.th.exchange.has['createMarketOrder']:
                params = {}
                if self.th.exchange.name == 'Kraken':
                    params['trading_agreement'] = 'agree'

                try:
                    response = self.safe_run(
                        lambda: self.th.exchange.createMarketSellOrder(self.symbol, self.coins_avail(), params),
                        i_ts=self.get_uid())
                except InsufficientFunds:
                    response = self.sell_free_bal()
            else:
                if price is None:
                    price = self.safe_run(
                        lambda: self.th.exchange.fetch_ticker(self.symbol)['last'], i_ts=self.get_uid())
                try:
                    response = self.safe_run(
                        lambda: self.th.exchange.createLimitSellOrder(self.symbol, self.coins_avail(), price * 0.995),
                        i_ts=self.get_uid())
                except InsufficientFunds:
                    response = self.sell_free_bal()
            if response is not None:
                time.sleep(5)  # give exchange 5 sec for trading the order
                order_info = self.fetch_order(response['id'], 'SELL')

                if order_info['status'].lower() in ['closed', 'filled', 'canceled']:
                    if order_info['type'] == 'market' and self.th.exchange.has['fetchMyTrades'] is not False:
                        trades = self.th.exchange.fetchMyTrades(self.symbol)
                        order_info['cost'] = sum([tr['cost'] for tr in trades if tr['order'] == order_info['id']])
                        order_info['price'] = np.mean([tr['price'] for tr in trades if tr['order'] == order_info['id']])
                    self.out_trades.append(
                        {'oid': 'filled', 'price': order_info['price'], 'amount': order_info['amount']})
                    logger.info('Sold immediately at a price of %s %s: Sold %s %s for %s %s.' % (
                        self.th.nf.price2Prec(self.symbol, order_info['price']), self.symbol,
                        self.th.nf.amount2Prec(self.symbol, order_info['amount']), self.coinCurrency,
                        self.th.nf.cost2Prec(self.symbol, order_info['cost']), self.baseCurrency),
                                extra=self.th.logger_extras)
                else:
                    logger.info('Sell order was not traded immediately, updating status soon.',
                                extra=self.th.logger_extras)
                    sold = False
                    self.out_trades.append(
                        {'oid': response['id'], 'price': order_info['price'], 'amount': order_info['amount']})
                    self.activate(False)
            else:
                sold = False
        else:
            logger.warning('No coins (or too low amount) to sell from this trade set.',
                           extra=self.th.logger_extras)
        return sold

    def cancel_sell_orders(self, oid=None, delete_orders=False):
        self.th.update_down_state(True)
        return_val = 1
        if self.num_sell_levels() > 0:
            count = 0
            for iTrade, trade in reversed(list(enumerate(self.out_trades))):
                if oid is None or trade['oid'] == oid:
                    if trade['oid'] is not None and trade['oid'] != 'filled':
                        try:
                            self.cancel_order(trade['oid'], 'SELL')
                        except OrderNotFound:
                            pass
                        except Exception as e:
                            self.unlock_trade_set()
                            raise e
                        time.sleep(1)
                        count += 1
                        order_info = self.fetch_order(trade['oid'], 'SELL')
                        if order_info['filled'] > 0:
                            logger.warning('(Partly?) filled sell order found during canceling. Updating balance',
                                           extra=self.th.logger_extras)
                            trade['oid'] = 'filled'
                            trade['amount'] = order_info['filled']
                            if order_info['price'] is not None:
                                trade['price'] = order_info['price']
                            return_val = 0.5
                        else:
                            trade['oid'] = None
                    if delete_orders:
                        if trade['oid'] != 'filled':
                            self.out_trades.pop(iTrade)
            if count > 0:
                logger.info('%d sell orders canceled in total for tradeSet %d (%s)' % (
                    count, list(self.th.tradeSets.keys()).index(self._uid), self.symbol),
                            extra=self.th.logger_extras)
        return return_val

    def cancel_buy_orders(self, oid=None, delete_orders=False):
        self.th.update_down_state(True)
        return_val = 1
        if self.num_buy_levels() > 0:
            count = 0
            for iTrade, trade in reversed(list(enumerate(self.in_trades))):
                if oid is None or trade['oid'] == oid:
                    if trade['oid'] is not None and trade['oid'] != 'filled':
                        try:
                            self.cancel_order(trade['oid'], 'BUY')
                        except OrderNotFound:
                            pass

                        time.sleep(1)
                        count += 1
                        order_info = self.fetch_order(trade['oid'], 'BUY')
                        if order_info['filled'] > 0:
                            logger.warning('(Partly?) filled buy order found during canceling. Updating balance',
                                           extra=self.th.logger_extras)
                            trade['oid'] = 'filled'
                            trade['amount'] = order_info['filled']
                            if order_info['price'] is not None:
                                trade['price'] = order_info['price']
                            return_val = 0.5
                        else:
                            trade['oid'] = None
                    if delete_orders:
                        if trade['oid'] != 'filled':
                            self.in_trades.pop(iTrade)
            if count > 0:
                logger.info('%d buy orders canceled in total for tradeSet %d (%s)' % (
                    count, list(self.th.tradeSets.keys()).index(self._uid), self.symbol),
                            extra=self.th.logger_extras)
        return return_val

    def init_buy_orders(self):
        self.th.update_down_state(True)
        if self.__active:
            # initialize buy orders
            for iTrade, trade in enumerate(self.in_trades):
                if trade['oid'] is None and trade['candleAbove'] is None:
                    try:
                        response = self.safe_run(
                            lambda: self.th.exchange.createLimitBuyOrder(self.symbol, trade['amount'],
                                                                         trade['price']))
                    except InsufficientFunds as e:
                        self.deactivate()
                        logger.error(f"Insufficient funds on exchange {self.th.exchange.name} for trade set "
                                     f"{self.name}. Trade set is deactivated now and not updated anymore "
                                     f"(open orders are still open)! Free the missing funds and reactivate. \n {e}.",
                                     extra=self.th.logger_extras)
                        raise e
                    self.in_trades[iTrade]['oid'] = response['id']

    def cancel_order(self, oid, typ):
        self.th.update_down_state(True)
        symbol = self.symbol
        try:
            return self.safe_run(lambda: self.th.exchange.cancel_order(oid, symbol), False)
        except OrderNotFound as e:
            self.unlock_trade_set()
            raise e
        except ExchangeError:
            return self.safe_run(lambda: self.th.exchange.cancel_order(oid, symbol, {'type': typ}), i_ts=self.get_uid())

    def fetch_order(self, oid, typ):
        symbol = self.symbol
        try:
            return self.safe_run(lambda: self.th.exchange.fetch_order(oid, symbol), False)
        except OrderNotFound as e:
            self.unlock_trade_set()
            raise e
        except ExchangeError:
            return self.safe_run(lambda: self.th.exchange.fetch_order(oid, symbol, {'type': typ}), i_ts=self.get_uid())

    def add_init_coins(self, init_price=None, init_coins=0):
        if self.th.check_num(init_coins, init_price) or (init_price is None and self.th.check_num(init_coins)):
            if init_price is not None and init_price < 0:
                init_price = None
            # check if free balance is indeed sufficient
            bal = self.th.get_balance(self.coinCurrency)
            if bal is None:
                logger.warning('Free balance could not be determined as exchange does not support this! '
                               'If free balance does not suffice for initial coins there will be an error when trade '
                               'set is activated!', extra=self.th.logger_extras)
            elif bal < init_coins:
                logger.error('Adding initial balance failed: %s %s requested but only %s %s are free!' % (
                    self.th.nf.amount2Prec(self.symbol, init_coins), self.coinCurrency,
                    self.th.nf.amount2Prec(self.symbol, self.th.get_balance(self.coinCurrency)),
                    self.coinCurrency),
                             extra=self.th.logger_extras)
                return 0
            self.lock_trade_set()
            self.init_coins = init_coins
            self.init_price = init_price
            self.unlock_trade_set()
            return 1
        else:
            raise ValueError('Some input was no number')

    def do_market_buy(self, amount, currency: str, lock=True):
        if self.th.check_num(amount):
            self.th.update_down_state(True)
            price = self.th.get_price_obj(self.symbol).get_current_price()
            est_fee = self.th.exchange.calculate_fee(self.symbol, 'market', 'buy', amount, price, 'taker')
            do_cost_buy = False
            if currency == self.coinCurrency:
                cost = amount * price
                if not self.th.check_quantity(self.symbol, 'amount', amount):
                    logger.error('Executing buy failed, amount is not within the range, the exchange accepts',
                                 extra=self.th.logger_extras)
                    return 0

            elif currency == self.baseCurrency:
                do_cost_buy = True
                cost = amount
                amount = cost / price
                if not self.th.check_quantity(self.symbol, 'cost', cost):
                    logger.error('Executing buy failed, cost is not within the range, the exchange accepts',
                                 extra=self.th.logger_extras)
                    return 0
            else:
                ValueError(f"Wrong currency {currency}!")

            bal = self.th.get_balance(self.baseCurrency)
            if bal is not None and bal < amount * price + \
                    (est_fee['cost'] if est_fee['currency'] == self.baseCurrency else 0):
                logger.error('Executing buy failed, your balance of %s does not suffice to buy this amount%s!' % (
                    self.baseCurrency,
                    ' and pay the trading fee (%s %s)' % (
                        self.th.nf.fee2Prec(self.symbol, est_fee['cost']), self.baseCurrency) if
                    est_fee['currency'] == self.baseCurrency else ''), extra=self.th.logger_extras)
                return 0
            if lock:
                self.lock_trade_set()
            params = {}
            if self.th.exchange.name == 'Kraken':
                params['trading_agreement'] = 'agree'

            try:
                if 'createMarketBuyOrderRequiresPrice' in self.th.exchange.options:
                    # this means the exchange assumes costs as input
                    old_val = self.th.exchange.options['createMarketBuyOrderRequiresPrice']
                    if do_cost_buy:
                        self.th.exchange.options['createMarketBuyOrderRequiresPrice'] = False
                        response = self.safe_run(lambda: self.th.exchange.createMarketBuyOrder(self.symbol, cost,
                                                                                               params=params), False)
                    else:
                        self.th.exchange.options['createMarketBuyOrderRequiresPrice'] = True
                        response = self.safe_run(
                            lambda: self.th.exchange.createOrder(self.symbol, 'market', 'buy', amount, price,
                                                                 params=params), False)
                    self.th.exchange.options['createMarketBuyOrderRequiresPrice'] = old_val
                else:
                    # this means the exchange assumes amount as input
                    response = self.safe_run(lambda: self.th.exchange.createMarketBuyOrder(self.symbol, amount,
                                                                                           params=params), False)

                bought_amount = amount - (est_fee['cost'] if est_fee['currency'] == self.coinCurrency else 0)
                self.in_trades.append({'oid': response['id'], 'price': price,
                                      'amount': amount,
                                      'actualAmount': bought_amount,
                                      'candleAbove': None})

            except InsufficientFunds as e:
                self.deactivate()
                logger.error(f"Insufficient funds on exchange {self.th.exchange.name} for trade set "
                             f"#{self.th.exchange.name}. Trade set is deactivated now and not updated anymore "
                             f"(open orders are still open)! Free the missing funds and reactivate. \n {e}.",
                             extra=self.th.logger_extras)
                raise e
            finally:
                if lock:
                    self.unlock_trade_set()
        else:
            raise ValueError('Some input was no number')

    def add_buy_level(self, buy_price: float, buy_amount, candle_above=None, lock=True) -> bool:
        """

        :param buy_price:
        :param buy_amount: If buy price is None, this is the cost (quote currency), else the amount of the coin currency
        :param candle_above:
        :param lock: Boolean if trade set should be locked
        :return: Boolean if buy level add succeeded
        """
        self.th.update_down_state(True)
        if self.th.check_num(buy_price, buy_amount, candle_above) or (
                candle_above is None and self.th.check_num(buy_price, buy_amount)):

            fee = self.th.exchange.calculate_fee(self.symbol, 'limit', 'buy', buy_amount, buy_price, 'maker')
            if not self.th.check_quantity(self.symbol, 'amount', buy_amount):
                logger.error('Adding buy level failed, amount is not within the range, the exchange accepts',
                             extra=self.th.logger_extras)
                return False
            elif not self.th.check_quantity(self.symbol, 'price', buy_price):
                logger.error('Adding buy level failed, price is not within the range, the exchange accepts',
                             extra=self.th.logger_extras)
                return False
            elif not self.th.check_quantity(self.symbol, 'cost', buy_price * buy_amount):
                logger.error('Adding buy level failed, cost is not within the range, the exchange accepts',
                             extra=self.th.logger_extras)
                return False
            bal = self.th.get_balance(self.baseCurrency)
            if bal is None:
                logger.warning('Free balance could not be determined as exchange does not support this! '
                               'If free balance does not suffice there will be an error when trade set is activated',
                               extra=self.th.logger_extras)
            elif bal < buy_amount * buy_price + (fee['cost'] if fee['currency'] == self.baseCurrency else 0):
                logger.error('Adding buy level failed, your balance of %s does not suffice to buy this amount%s!' % (
                    self.baseCurrency,
                    ' and pay the trading fee (%s %s)' % (
                        self.th.nf.fee2Prec(self.symbol, fee['cost']), self.baseCurrency) if
                    fee['currency'] == self.baseCurrency else ''), extra=self.th.logger_extras)
                return False
            if lock:
                self.lock_trade_set()
            wasactive = self.deactivate()

            bought_amount = buy_amount
            # subtract the fee cost if they are paid from the bought amount
            if fee['currency'] == self.coinCurrency and not self.th.is_paid_by_exchange_token(fee['cost'],
                                                                                              self.coinCurrency):
                bought_amount -= fee['cost']

            self.in_trades.append({'oid': None, 'price': buy_price, 'amount': buy_amount, 'actualAmount': bought_amount,
                                  'candleAbove': candle_above})

            if wasactive:
                self.activate(False)
            if lock:
                self.unlock_trade_set()
            return True
        else:
            raise ValueError('Some input was no number')

    def delete_buy_level(self, i_trade):
        self.th.update_down_state(True)
        if self.th.check_num(i_trade):
            self.lock_trade_set()
            wasactive = self.deactivate()
            if self.in_trades[i_trade]['oid'] is not None and self.in_trades[i_trade]['oid'] != 'filled':
                self.cancel_buy_orders(self.in_trades[i_trade]['oid'])
            self.in_trades.pop(i_trade)
            if wasactive:
                self.activate(False)
            self.unlock_trade_set()
        else:
            raise ValueError('Some input was no number')

    def set_buy_level(self, i_trade, price, amount):
        self.th.update_down_state(True)
        if self.th.check_num(i_trade, price, amount):
            if self.in_trades[i_trade]['oid'] == 'filled':
                logger.error('This order is already filled! No change possible', extra=self.th.logger_extras)
                return 0
            else:
                fee = self.th.exchange.calculate_fee(self.symbol, 'limit', 'buy', amount, price, 'maker')
                if not self.th.check_quantity(self.symbol, 'amount', amount):
                    logger.error('Changing buy level failed, amount is not within the range, the exchange accepts',
                                 extra=self.th.logger_extras)
                    return 0
                elif not self.th.check_quantity(self.symbol, 'price', price):
                    logger.error('Changing buy level failed, price is not within the range, the exchange accepts',
                                 extra=self.th.logger_extras)
                    return 0
                elif not self.th.check_quantity(self.symbol, 'cost', price * amount):
                    logger.error('Changing buy level failed, cost is not within the range, the exchange accepts',
                                 extra=self.th.logger_extras)
                    return 0
                bal = self.th.get_balance(self.baseCurrency)
                if bal is None:
                    logger.warning('Free balance could not be determined as exchange does not support this! '
                                   'If free balance does not suffice there will be an error when tradeset is activated',
                                   extra=self.th.logger_extras)
                elif bal + self.in_trades[i_trade]['amount'] * self.in_trades[i_trade]['price'] < amount * price + \
                     fee['cost'] if fee['currency'] == self.baseCurrency else 0:
                    logger.error(
                        'Changing buy level failed, your balance of %s does not suffice to buy this amount%s!' % (
                            self.baseCurrency, ' and pay the trading fee (%s %s)' % (
                                self.th.nf.fee2Prec(self.symbol, fee['cost']), self.baseCurrency)
                            if fee['currency'] == self.baseCurrency else ''), extra=self.th.logger_extras)
                    return 0
                bought_amount = amount
                # subtract the fee cost if they are paid from the bought amount
                if fee['currency'] == self.coinCurrency and not self.th.is_paid_by_exchange_token(fee['cost'],
                                                                                                  self.coinCurrency):
                    bought_amount -= fee['cost']

                wasactive = self.deactivate()

                if self.in_trades[i_trade]['oid'] is not None and self.in_trades[i_trade]['oid'] != 'filled':
                    return_val = self.cancel_buy_orders(self.in_trades[i_trade]['oid'])
                    self.in_trades[i_trade]['oid'] = None
                    if return_val == 0.5:
                        bal = self.th.get_balance(self.baseCurrency)
                        if bal is None:
                            logger.warning('Free balance could not be determined as exchange does not support this! If '
                                           'free balance doesnt suffice there will be an error on trade set activation',
                                           extra=self.th.logger_extras)
                        elif bal + self.in_trades[i_trade]['amount'] * self.in_trades[i_trade]['price'] < amount * price \
                             + fee['cost'] if fee['currency'] == self.baseCurrency else 0:
                            logger.error(f"Changing buy level failed, your balance of {self.baseCurrency} does not "
                                         f"suffice to buy this amount %s!" % (
                                             f"and pay the trading fee ({self.th.nf.fee2Prec(self.symbol, fee['cost'])}"
                                             f" {self.baseCurrency})" if fee['currency'] == self.baseCurrency else ''),
                                         extra=self.th.logger_extras)
                            return 0
                self.in_trades[i_trade].update({'amount': amount, 'actualAmount': bought_amount, 'price': price})

                if wasactive:
                    self.activate(False)
                return 1
        else:
            raise ValueError('Some input was no number')

    def add_sell_level(self, sell_price, sell_amount) -> bool:
        self.th.update_down_state(True)
        if self.th.check_num(sell_price, sell_amount):
            if not self.th.check_quantity(self.symbol, 'amount', sell_amount):
                logger.error('Adding sell level failed, amount is not within the range, the exchange accepts',
                             extra=self.th.logger_extras)
                return False
            elif not self.th.check_quantity(self.symbol, 'price', sell_price):
                logger.error('Adding sell level failed, price is not within the range, the exchange accepts',
                             extra=self.th.logger_extras)
                return False
            elif not self.th.check_quantity(self.symbol, 'cost', sell_price * sell_amount):
                logger.error('Adding sell level failed, return is not within the range, the exchange accepts',
                             extra=self.th.logger_extras)
                return False
            self.lock_trade_set()
            wasactive = self.deactivate()
            self.out_trades.append({'oid': None, 'price': sell_price, 'amount': sell_amount})
            if wasactive:
                self.activate(False)
            self.unlock_trade_set()
            return True
        else:
            raise ValueError('Some input was no number')

    def delete_sell_level(self, i_trade):
        self.th.update_down_state(True)
        if self.th.check_num(i_trade):
            self.lock_trade_set()
            wasactive = self.deactivate()
            if self.out_trades[i_trade]['oid'] is not None and self.out_trades[i_trade]['oid'] != 'filled':
                self.cancel_sell_orders(self.out_trades[i_trade]['oid'])
            self.out_trades.pop(i_trade)
            self.unlock_trade_set()
            if wasactive:
                self.activate(False)
        else:
            raise ValueError('Some input was no number')

    def set_sell_level(self, i_trade, price, amount):
        self.th.update_down_state(True)
        if self.th.check_num(i_trade, price, amount):
            if self.out_trades[i_trade]['oid'] == 'filled':
                logger.error('This order is already filled! No change possible', extra=self.th.logger_extras)
                return 0
            else:
                if not self.th.check_quantity(self.symbol, 'amount', amount):
                    logger.error('Changing sell level failed, amount is not within the range, the exchange accepts',
                                 extra=self.th.logger_extras)
                    return 0
                elif not self.th.check_quantity(self.symbol, 'price', price):
                    logger.error('Changing sell level failed, price is not within the range, the exchange accepts',
                                 extra=self.th.logger_extras)
                    return 0
                elif not self.th.check_quantity(self.symbol, 'cost', price * amount):
                    logger.error('Changing sell level failed, return is not within the range, the exchange accepts',
                                 extra=self.th.logger_extras)
                    return 0
                wasactive = self.deactivate()

                if self.out_trades[i_trade]['oid'] is not None and self.out_trades[i_trade]['oid'] != 'filled':
                    self.cancel_sell_orders(self.out_trades[i_trade]['oid'])
                    self.out_trades[i_trade]['oid'] = None

                self.out_trades[i_trade]['amount'] = amount
                self.out_trades[i_trade]['price'] = price

                if wasactive:
                    self.activate(False)
                return 1
        else:
            raise ValueError('Some input was no number')

    def sell_free_bal(self) -> Union[None, dict]:
        free_bal = self.th.get_balance(self.coinCurrency)
        if free_bal is None:
            logger.error(f"When selling {self.symbol}, exchange reported insufficient funds and does not allow to "
                         f"determine free balance of {self.coinCurrency}, thus nothing could be sold automatically! "
                         f"Please sell manually!", extra=self.th.logger_extras)
            return None
        elif free_bal == 0:
            logger.error(f"When selling {self.symbol}, exchange reported insufficient funds. Please sell manually!",
                         extra=self.th.logger_extras)
            return None
        else:
            try:
                response = self.safe_run(lambda: self.th.exchange.createMarketSellOrder(self.symbol, free_bal), False)
            except Exception:
                logger.warning('There was an error selling %s! Please sell manually!' % self.symbol,
                               extra=self.th.logger_extras)
                return None
            logger.warning('When selling %s, only %s %s was found and sold!' % (
                self.symbol, self.th.nf.amount2Prec(self.symbol, free_bal), self.coinCurrency),
                           extra=self.th.logger_extras)
            return response

    def set_trailing_sl(self, value, typ: ValueType = ValueType.ABSOLUTE):
        self.th.update_down_state(True)
        if self.th.check_num(value):
            if self.num_buy_levels('notfilled') > 0:
                raise Exception('Trailing SL cannot be set as there are non-filled buy orders still')
            self.sl = TrailingSL(delta=value, kind=typ, price_obj=self.th.get_price_obj(self.symbol))
        elif value is None:
            self.sl = None
        else:
            raise ValueError('Input was no number')

    def set_weekly_close_sl(self, value) -> bool:
        if self.th.check_num(value):
            self.sl = WeeklyCloseSL(value=value)
            if self.th.get_price_obj(self.symbol).get_current_price() <= value:
                logger.warning('Weekly-close SL is set but be aware that it is higher than the current market price!',
                               extra=self.th.logger_extras)
            return True

        elif value is None:
            self.sl = None
            return True
        else:
            raise ValueError('Input was no number')

    def set_daily_close_sl(self, value) -> bool:
        if self.th.check_num(value):
            self.sl = DailyCloseSL(value=value)
            if self.th.get_price_obj(self.symbol).get_current_price() <= value:
                logger.warning('Daily-close SL is set but be aware that it is higher than the current market price!',
                               extra=self.th.logger_extras)
            return True
        elif value is None:
            self.sl = None
            return True
        else:
            raise ValueError('Input was no number')

    def set_sl(self, value) -> bool:
        if self.th.check_num(value):
            try:
                self.sl = BaseSL(value=value)
                return True
            except Exception as e:
                logger.error(str(e), extra=self.th.logger_extras)
        elif value is None:
            self.sl = None
            return True
        else:
            raise ValueError('Input was no number')
        return False

    def set_sl_break_even(self):
        self.th.update_down_state(True)
        if self.init_coins > 0 and self.init_price is None:
            logger.error(f"Break even SL cannot be set as you this trade set contains {self.coinCurrency} that you "
                         f"obtained beforehand and no buy price information was given.", extra=self.th.logger_extras)
            return 0
        elif self.cost_out() - self.cost_in() > 0:
            logger.error(
                'Break even SL cannot be set as your sold coins of this trade already outweigh your buy expenses '
                '(congrats!)! You might choose to sell everything immediately if this is what you want.',
                extra=self.th.logger_extras)
            return 0
        elif self.cost_out() - self.cost_in() == 0:
            logger.error('Break even SL cannot be set as there are no unsold %s coins right now' % self.coinCurrency,
                         extra=self.th.logger_extras)
            return 0
        else:
            break_even_price = (self.cost_in() - self.cost_out()) / ((1 - self.th.exchange.fees['trading']['taker']) * (
                    self.coins_avail() + self.sum_sell_amounts(order='open', subtract_fee=False)))
            price_obj = self.th.get_price_obj(self.symbol)
            if price_obj.get_current_price() < break_even_price:
                logger.error(f'Break even SL of {self.th.nf.price2Prec(self.symbol, break_even_price)} cannot be set as'
                             f' the current market price is lower '
                             f'({self.th.nf.price2Prec(self.symbol, price_obj.get_current_price())})!',
                             extra=self.th.logger_extras)
                return 0
            else:
                self.set_sl(break_even_price)
                return 1
