import datetime
import random

from ccxt import InsufficientFunds, OrderNotFound, ExchangeError
import numpy as np
import re
import string
import time
from enum import Flag, auto
from typing import Union
import logging
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .tradeHandler import tradeHandler

logger = logging.getLogger(__name__)


class SLType(Flag):
    DEFAULT = auto()
    TRAILING = auto()
    DAILYCLOSE = auto()
    WEEKLYCLOSE = auto()


class ValueType(Flag):
    ABSOLUTE = auto()
    RELATIVE = auto()


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
    def __init__(self, symbol: str, exchange, trade_handler: 'tradeHandler', uid: str = None, safe_run_func=None):
        if uid is None:
            random.seed()
            uid = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))

        self.exchange = exchange
        self.trade_handler = trade_handler
        self.nf = NumberFormatter(exchange)
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
        self.__active = False
        self.__virgin = True
        self.updating = False
        self.waiting = []
        if safe_run_func is None:
            def safe_run_func(x, print_error=None, i_ts=None):
                return x()
        self.safe_run = safe_run_func

    def __init__(self, ts_dict: Dict):
        pass
    
    def is_virgin(self):
        return self.__virgin

    def get_uid(self):
        return self._uid

    def _set_active(self):
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
                        self.symbol, self.exchange.name))
                break
        self.updating = True
        self.waiting.remove(mystamp)

    def unlock_trade_set(self):
        self.updating = False

    def is_active(self):
        return self.__active

    def activate(self, verbose=True) -> bool:
        self.trade_handler.update_down_state(True)
        wasactive = self.__active
        # check if symbol is active
        if not self.exchange.markets[self.symbol]['active']:
            logger.error(
                'Cannot activate trade set because %s was deactivated for trading by the exchange!' % self.symbol,
                extra=self.trade_handler.logger_extras)
            return wasactive
        # sanity check of amounts to buy/sell
        if self.sum_sell_amounts('notinitiated') - (self.sum_buy_amounts('notfilled') + self.coinsAvail) > 0:
            logger.error(
                f"Cannot activate trade set because the total amount you (still) want to sell "
                f"({self.nf.amount2Prec(self.symbol, self.sum_sell_amounts('notinitiated', True))} "
                f"{self.coinCurrency}) exceeds the total amount you want to buy "
                f"({self.nf.amount2Prec(self.symbol, self.sum_buy_amounts('notfilled', True))} {self.coinCurrency} "
                f"after fee subtraction) and the amount you already have in this trade set "
                f"({self.nf.amount2Prec(self.symbol, self.coinsAvail)} {self.coinCurrency}). "
                f"Please adjust the trade set!", extra=self.trade_handler.logger_extras)
            return wasactive
        elif self.min_buy_price(order='notfilled') is not None and self.SL is not None and self.SL.value \
                >= self.min_buy_price(order='notfilled'):
            logger.error(
                'Cannot activate trade set because the current stop loss price is higher than the lowest non-filled buy'
                ' order price, which means this buy order could never be reached. Please adjust the trade set!',
                extra=self.trade_handler.logger_extras)
            return wasactive
        self.__virgin = False
        self.__active = True
        if verbose and not wasactive:
            total_buy_cost = self.costIn + self.sum_buy_costs('notfilled')
            logger.info('Estimated return if all trades are executed: %s %s' % (
                self.nf.cost2Prec(self.symbol, self.sum_sell_costs() - total_buy_cost), self.baseCurrency),
                        extra=self.trade_handler.logger_extras)
            if self.SL is not None or isinstance(self.SL, DailyCloseSL):
                loss = total_buy_cost - self.costOut - (
                        self.initCoins + self.sum_buy_amounts() - self.sum_sell_amounts('filled')) * self.SL.value
                logger.info('Estimated %s if buys reach stop-loss before selling: %s %s' % (
                    '*gain*' if loss < 0 else 'loss', self.nf.cost2Prec(self.symbol, -loss if loss < 0 else loss),
                    self.baseCurrency), extra=self.trade_handler.logger_extras)
        try:
            self.init_buy_orders()
        except InsufficientFunds:
            logger.error('Cannot activate trade set due to insufficient funds!',
                         extra=self.trade_handler.logger_extras)
            self.deactivate()
        return wasactive

    def deactivate(self, cancel_orders=0):
        self.trade_handler.update_down_state(True)
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

    def sum_sell_amounts(self, order='all', subtract_fee=True):
        return self.get_trade_param('amount', 'sum', 'sell', order, subtract_fee)

    def sum_buy_costs(self, order='all', subtract_fee=True):
        return self.get_trade_param('cost', 'sum', 'buy', order, subtract_fee)

    def sum_sell_costs(self, order='all', subtract_fee=True):
        return self.get_trade_param('cost', 'sum', 'sell', order, subtract_fee)

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
            trades = self.OutTrades
        else:
            trades = self.InTrades

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
        self.trade_handler.update_down_state(True)
        self.deactivate(2)
        self.SL = None  # necessary to not retrigger SL
        sold = True
        if self.coinsAvail > 0 and self.trade_handler.check_quantity(self.symbol, 'amount', self.coinsAvail):
            if self.exchange.has['createMarketOrder']:
                try:
                    response = self.safe_run(
                        lambda: self.exchange.createMarketSellOrder(self.symbol, self.coinsAvail),
                        False)
                except InsufficientFunds:
                    response = self.sell_free_bal()
                except Exception:
                    params = {'trading_agreement': 'agree'}  # for kraken api...
                    try:
                        response = self.safe_run(
                            lambda: self.exchange.createMarketSellOrder(self.symbol, self.coinsAvail, params),
                            i_ts=self.get_uid())
                    except InsufficientFunds:
                        response = self.sell_free_bal()
            else:
                if price is None:
                    price = self.safe_run(lambda: self.exchange.fetch_ticker(self.symbol)['last'], i_ts=self.get_uid())
                try:
                    response = self.safe_run(
                        lambda: self.exchange.createLimitSellOrder(self.symbol, self.coinsAvail, price * 0.995),
                        i_ts=self.get_uid())
                except InsufficientFunds:
                    response = self.sell_free_bal()
            if response is not None:
                time.sleep(5)  # give exchange 5 sec for trading the order
                order_info = self.fetch_order(response['id'], 'SELL')

                if order_info['status'] == 'FILLED':
                    if order_info['type'] == 'market' and self.exchange.has['fetchMyTrades'] is not False:
                        trades = self.exchange.fetchMyTrades(self.symbol)
                        order_info['cost'] = sum([tr['cost'] for tr in trades if tr['order'] == order_info['id']])
                        order_info['price'] = np.mean([tr['price'] for tr in trades if tr['order'] == order_info['id']])
                    self.costOut += order_info['cost']
                    logger.info('Sold immediately at a price of %s %s: Sold %s %s for %s %s.' % (
                        self.nf.price2Prec(self.symbol, order_info['price']), self.symbol,
                        self.nf.amount2Prec(self.symbol, order_info['amount']), self.coinCurrency,
                        self.nf.cost2Prec(self.symbol, order_info['cost']), self.baseCurrency),
                                extra=self.trade_handler.logger_extras)
                else:
                    logger.info('Sell order was not traded immediately, updating status soon.',
                                extra=self.trade_handler.logger_extras)
                    sold = False
                    self.OutTrades.append(
                        {'oid': response['id'], 'price': order_info['price'], 'amount': order_info['amount']})
                    self.activate(False)
            else:
                sold = False
        else:
            logger.warning('No coins (or too low amount) to sell from this trade set.',
                           extra=self.trade_handler.logger_extras)
        return sold

    def cancel_sell_orders(self, oid=None, delete_orders=False):
        self.trade_handler.update_down_state(True)
        return_val = 1
        if self.num_sell_levels() > 0:
            count = 0
            for iTrade, trade in reversed(list(enumerate(self.OutTrades))):
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
                        self.coinsAvail += trade['amount']
                        if order_info['filled'] > 0:
                            logger.warning('(Partly?) filled sell order found during canceling. Updating balance',
                                           extra=self.trade_handler.logger_extras)
                            self.costOut += order_info['price'] * order_info['filled']
                            self.coinsAvail -= order_info['filled']
                            trade['oid'] = 'filled'
                            trade['amount'] = order_info['filled']
                            return_val = 0.5
                        else:
                            trade['oid'] = None
                    if delete_orders:
                        if trade['oid'] != 'filled':
                            self.OutTrades.pop(iTrade)
            if count > 0:
                logger.info('%d sell orders canceled in total for tradeSet %d (%s)' % (
                    count, list(self.trade_handler.tradeSets.keys()).index(self._uid), self.symbol),
                            extra=self.trade_handler.logger_extras)
        return return_val

    def cancel_buy_orders(self, oid=None, delete_orders=False):
        self.trade_handler.update_down_state(True)
        return_val = 1
        if self.num_buy_levels() > 0:
            count = 0
            for iTrade, trade in reversed(list(enumerate(self.InTrades))):
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
                                           extra=self.trade_handler.logger_extras)
                            self.costIn += order_info['price'] * order_info['filled']
                            self.coinsAvail += order_info['filled']
                            trade['oid'] = 'filled'
                            trade['amount'] = order_info['filled']
                            return_val = 0.5
                        else:
                            trade['oid'] = None
                    if delete_orders:
                        if trade['oid'] != 'filled':
                            self.InTrades.pop(iTrade)
            if count > 0:
                logger.info('%d buy orders canceled in total for tradeSet %d (%s)' % (
                    count, list(self.trade_handler.tradeSets.keys()).index(self._uid), self.symbol),
                            extra=self.trade_handler.logger_extras)
        return return_val

    def init_buy_orders(self):
        self.trade_handler.update_down_state(True)
        if self.__active:
            # initialize buy orders
            for iTrade, trade in enumerate(self.InTrades):
                if trade['oid'] is None and trade['candleAbove'] is None:
                    try:
                        response = self.safe_run(
                            lambda: self.exchange.createLimitBuyOrder(self.symbol, trade['amount'],
                                                                      trade['price']))
                    except InsufficientFunds as e:
                        self.deactivate()
                        logger.error(f"Insufficient funds on exchange {self.exchange.name} for trade set "
                                     f"#{self.exchange.name}. Trade set is deactivated now and not updated anymore "
                                     f"(open orders are still open)! Free the missing funds and reactivate. \n {e}.",
                                     extra=self.trade_handler.logger_extras)
                        raise e
                    self.InTrades[iTrade]['oid'] = response['id']

    def cancel_order(self, oid, typ):
        self.trade_handler.update_down_state(True)
        symbol = self.symbol
        try:
            return self.safe_run(lambda: self.exchange.cancel_order(oid, symbol), False)
        except OrderNotFound as e:
            self.unlock_trade_set()
            raise e
        except ExchangeError:
            return self.safe_run(lambda: self.exchange.cancel_order(oid, symbol, {'type': typ}), i_ts=self.get_uid())

    def fetch_order(self, oid, typ):
        symbol = self.symbol
        try:
            return self.safe_run(lambda: self.exchange.fetch_order(oid, symbol), False)
        except OrderNotFound as e:
            self.unlock_trade_set()
            raise e
        except ExchangeError:
            return self.safe_run(lambda: self.exchange.fetch_order(oid, symbol, {'type': typ}), i_ts=self.get_uid())


    def add_init_coins(self, init_coins=0, init_price=None):
        if self.trade_handler.check_num(init_coins, init_price) or (init_price is None and self.trade_handler.check_num(init_coins)):
            if init_price is not None and init_price < 0:
                init_price = None
            # check if free balance is indeed sufficient
            bal = self.trade_handler.get_balance(self.coinCurrency)
            if bal is None:
                logger.warning('Free balance could not be determined as exchange does not support this! '
                               'If free balance does not suffice for initial coins there will be an error when trade set '
                               'is activated!', extra=self.trade_handler.logger_extras)
            elif bal < init_coins:
                logger.error('Adding initial balance failed: %s %s requested but only %s %s are free!' % (
                    self.nf.amount2Prec(self.symbol, init_coins), self.coinCurrency,
                    self.nf.amount2Prec(self.symbol, self.trade_handler.get_balance(self.coinCurrency)),
                    self.coinCurrency),
                             extra=self.trade_handler.logger_extras)
                return 0
            self.lock_trade_set()

            if self.coinsAvail > 0 and self.initPrice is not None:
                # remove old cost again
                self.costIn -= (self.coinsAvail * self.initPrice)
            self.coinsAvail = init_coins
            self.initCoins = init_coins

            self.initPrice = init_price
            if init_price is not None:
                self.costIn += (init_coins * init_price)
            self.unlock_trade_set()
            return 1
        else:
            raise ValueError('Some input was no number')

    def add_buy_level(self, buy_price, buy_amount, candle_above=None):
        self.trade_handler.update_down_state(True)
        if self.trade_handler.check_num(buy_price, buy_amount, candle_above) or (
                candle_above is None and self.trade_handler.check_num(buy_price, buy_amount)):
            fee = self.exchange.calculate_fee(self.symbol, 'limit', 'buy', buy_amount, buy_price, 'maker')
            if not self.trade_handler.check_quantity(self.symbol, 'amount', buy_amount):
                logger.error('Adding buy level failed, amount is not within the range, the exchange accepts',
                             extra=self.trade_handler.logger_extras)
                return 0
            elif not self.trade_handler.check_quantity(self.symbol, 'price', buy_price):
                logger.error('Adding buy level failed, price is not within the range, the exchange accepts',
                             extra=self.trade_handler.logger_extras)
                return 0
            elif not self.trade_handler.check_quantity(self.symbol, 'cost', buy_price * buy_amount):
                logger.error('Adding buy level failed, cost is not within the range, the exchange accepts',
                             extra=self.trade_handler.logger_extras)
                return 0
            bal = self.trade_handler.get_balance(self.baseCurrency)
            if bal is None:
                logger.error('Free balance could not be determined as exchange does not support this! '
                             'If free balance does not suffice there will be an error when trade set is activated',
                             'warning', extra=self.trade_handler.logger_extras)
            elif bal < buy_amount * buy_price + (fee['cost'] if fee['currency'] == self.baseCurrency else 0):
                logger.error('Adding buy level failed, your balance of %s does not suffice to buy this amount%s!' % (
                    self.baseCurrency,
                    ' and pay the trading fee (%s %s)' % (
                        self.nf.fee2Prec(self.symbol, fee['cost']), self.baseCurrency) if
                    fee['currency'] == self.baseCurrency else ''), extra=self.trade_handler.logger_extras)
                return 0

            bought_amount = buy_amount
            if fee['currency'] == self.coinCurrency and \
                    (self.exchange.name.lower() != 'binance' or self.trade_handler.get_balance('BNB') < 0.5):
                # this is a hack, as fees on binance are deduced from BNB if this is activated and there is enough BNB,
                # however so far no API chance to see if this is the case. Here I assume that 0.5 BNB are enough to pay
                # the fee for the trade and thus the fee is not subtracted from the traded coin
                bought_amount -= fee['cost']
            self.lock_trade_set()
            wasactive = self.deactivate()
            self.InTrades.append({'oid': None, 'price': buy_price, 'amount': buy_amount, 'actualAmount': bought_amount,
                                'candleAbove': candle_above})
            if wasactive:
                self.activate(False)
            self.unlock_trade_set()
            return self.num_buy_levels() - 1
        else:
            raise ValueError('Some input was no number')

    def delete_buy_level(self, i_trade):
        self.trade_handler.update_down_state(True)
        if self.trade_handler.check_num(i_trade):
            self.lock_trade_set()
            wasactive = self.deactivate()
            if self.InTrades[i_trade]['oid'] is not None and self.InTrades[i_trade]['oid'] != 'filled':
                self.cancel_buy_orders(self.InTrades[i_trade]['oid'])
            self.InTrades.pop(i_trade)
            if wasactive:
                self.activate(False)
            self.unlock_trade_set()
        else:
            raise ValueError('Some input was no number')

    def set_buy_level(self, i_trade, price, amount):
        self.trade_handler.update_down_state(True)
        if self.trade_handler.check_num(i_trade, price, amount):
            if self.InTrades[i_trade]['oid'] == 'filled':
                logger.error('This order is already filled! No change possible', extra=self.trade_handler.logger_extras)
                return 0
            else:
                fee = self.exchange.calculate_fee(self.symbol, 'limit', 'buy', amount, price, 'maker')
                if not self.trade_handler.check_quantity(self.symbol, 'amount', amount):
                    logger.error('Changing buy level failed, amount is not within the range, the exchange accepts',
                                 extra=self.trade_handler.logger_extras)
                    return 0
                elif not self.trade_handler.check_quantity(self.symbol, 'price', price):
                    logger.error('Changing buy level failed, price is not within the range, the exchange accepts',
                                 extra=self.trade_handler.logger_extras)
                    return 0
                elif not self.trade_handler.check_quantity(self.symbol, 'cost', price * amount):
                    logger.error('Changing buy level failed, cost is not within the range, the exchange accepts',
                                 extra=self.trade_handler.logger_extras)
                    return 0
                bal = self.trade_handler.get_balance(self.baseCurrency)
                if bal is None:
                    logger.warning('Free balance could not be determined as exchange does not support this! '
                                   'If free balance does not suffice there will be an error when tradeset is activated',
                                   extra=self.trade_handler.logger_extras)
                elif bal + self.InTrades[i_trade]['amount'] * self.InTrades[i_trade]['price'] < amount * price + \
                        fee['cost'] if fee['currency'] == self.baseCurrency else 0:
                    logger.error(
                        'Changing buy level failed, your balance of %s does not suffice to buy this amount%s!' % (
                            self.baseCurrency, ' and pay the trading fee (%s %s)' % (
                                self.nf.fee2Prec(self.symbol, fee['cost']), self.baseCurrency)
                            if fee['currency'] == self.baseCurrency else ''), extra=self.trade_handler.logger_extras)
                    return 0
                bought_amount = amount
                # this is a hack, as fees on binance are deduced from BNB if this is activated and there is enough BNB,
                # however so far no API chance to see if this is the case. Here I assume that 0.5 BNB are enough to pay
                # the fee for the trade and thus the fee is not subtracted from the traded coin
                if fee['currency'] == self.coinCurrency and \
                        (self.exchange.name.lower() != 'binance' or self.trade_handler.get_balance('BNB') < 0.5):
                    bought_amount -= fee['cost']

                wasactive = self.deactivate()

                if self.InTrades[i_trade]['oid'] is not None and self.InTrades[i_trade]['oid'] != 'filled':
                    return_val = self.cancel_buy_orders(self.InTrades[i_trade]['oid'])
                    self.InTrades[i_trade]['oid'] = None
                    if return_val == 0.5:
                        bal = self.trade_handler.get_balance(self.baseCurrency)
                        if bal is None:
                            logger.warning('Free balance could not be determined as exchange does not support this! If '
                                           'free balance doesnt suffice there will be an error on trade set activation',
                                           extra=self.trade_handler.logger_extras)
                        elif bal + self.InTrades[i_trade]['amount'] * self.InTrades[i_trade]['price'] < amount * price \
                                + fee['cost'] if fee['currency'] == self.baseCurrency else 0:
                            logger.error(f"Changing buy level failed, your balance of {self.baseCurrency} does not "
                                         f"suffice to buy this amount%s!" % (
                                             f" and pay the trading fee ({self.nf.fee2Prec(self.symbol, fee['cost'])} "
                                             f"{self.baseCurrency})" if fee['currency'] == self.baseCurrency else ''),
                                         extra=self.trade_handler.logger_extras)
                            return 0
                self.InTrades[i_trade].update({'amount': amount, 'actualAmount': bought_amount, 'price': price})

                if wasactive:
                    self.activate(False)
                return 1
        else:
            raise ValueError('Some input was no number')

    def add_sell_level(self, sell_price, sell_amount):
        self.trade_handler.update_down_state(True)
        if self.trade_handler.check_num(sell_price, sell_amount):
            if not self.trade_handler.check_quantity(self.symbol, 'amount', sell_amount):
                logger.error('Adding sell level failed, amount is not within the range, the exchange accepts',
                             extra=self.trade_handler.logger_extras)
                return 0
            elif not self.trade_handler.check_quantity(self.symbol, 'price', sell_price):
                logger.error('Adding sell level failed, price is not within the range, the exchange accepts',
                             extra=self.trade_handler.logger_extras)
                return 0
            elif not self.trade_handler.check_quantity(self.symbol, 'cost', sell_price * sell_amount):
                logger.error('Adding sell level failed, return is not within the range, the exchange accepts',
                             extra=self.trade_handler.logger_extras)
                return 0
            self.lock_trade_set()
            wasactive = self.deactivate()
            self.OutTrades.append({'oid': None, 'price': sell_price, 'amount': sell_amount})
            if wasactive:
                self.activate(False)
            self.unlock_trade_set()
            return self.num_sell_levels() - 1
        else:
            raise ValueError('Some input was no number')

    def delete_sell_level(self, i_trade):
        self.trade_handler.update_down_state(True)
        if self.trade_handler.check_num(i_trade):
            self.lock_trade_set()
            wasactive = self.deactivate()
            if self.OutTrades[i_trade]['oid'] is not None and self.OutTrades[i_trade]['oid'] != 'filled':
                self.cancel_sell_orders(self.OutTrades[i_trade]['oid'])
            self.OutTrades.pop(i_trade)
            self.unlock_trade_set()
            if wasactive:
                self.activate(False)
        else:
            raise ValueError('Some input was no number')

    def set_sell_level(self, i_trade, price, amount):
        self.trade_handler.update_down_state(True)
        if self.trade_handler.check_num(i_trade, price, amount):
            if self.OutTrades[i_trade]['oid'] == 'filled':
                logger.error('This order is already filled! No change possible', extra=self.trade_handler.logger_extras)
                return 0
            else:
                if not self.trade_handler.check_quantity(self.symbol, 'amount', amount):
                    logger.error('Changing sell level failed, amount is not within the range, the exchange accepts',
                                 extra=self.trade_handler.logger_extras)
                    return 0
                elif not self.trade_handler.check_quantity(self.symbol, 'price', price):
                    logger.error('Changing sell level failed, price is not within the range, the exchange accepts',
                                 extra=self.trade_handler.logger_extras)
                    return 0
                elif not self.trade_handler.check_quantity(self.symbol, 'cost', price * amount):
                    logger.error('Changing sell level failed, return is not within the range, the exchange accepts',
                                 extra=self.trade_handler.logger_extras)
                    return 0
                wasactive = self.deactivate()

                if self.OutTrades[i_trade]['oid'] is not None and self.OutTrades[i_trade]['oid'] != 'filled':
                    self.cancel_sell_orders(self.OutTrades[i_trade]['oid'])
                    self.OutTrades[i_trade]['oid'] = None

                self.OutTrades[i_trade]['amount'] = amount
                self.OutTrades[i_trade]['price'] = price

                if wasactive:
                    self.activate(False)
                return 1
        else:
            raise ValueError('Some input was no number')

    def sell_free_bal(self) -> Union[None, dict]:
        free_bal = self.trade_handler.get_balance(self.coinCurrency)
        if free_bal is None:
            logger.error(f"When selling {self.symbol}, exchange reported insufficient funds and does not allow to "
                         f"determine free balance of {self.coinCurrency}, thus nothing could be sold automatically! "
                         f"Please sell manually!", extra=self.trade_handler.logger_extras)
            return None
        elif free_bal == 0:
            logger.error(f"When selling {self.symbol}, exchange reported insufficient funds. Please sell manually!",
                         extra=self.trade_handler.logger_extras)
            return None
        else:
            try:
                response = self.safe_run(lambda: self.exchange.createMarketSellOrder(self.symbol, free_bal), False)
            except Exception:
                logger.warning('There was an error selling %s! Please sell manually!' % self.symbol,
                               extra=self.trade_handler.logger_extras)
                return None
            logger.warning('When selling %s, only %s %s was found and sold!' % (
                self.symbol, self.nf.amount2Prec(self.symbol, free_bal), self.coinCurrency),
                           extra=self.trade_handler.logger_extras)
            return response
