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

import ccxt
import re
from json import JSONDecodeError
from inspect import getsourcefile, getsourcelines
import numpy as np
import time
import datetime
import random
import string
import sys, os
from ccxt.base.errors import (AuthenticationError,NetworkError,OrderNotFound,InvalidNonce,ExchangeError,InsufficientFunds)

class tradeHandler:
    
    def __init__(self,exchName,key=None,secret=None,password=None,uid=None,messagerFct=None,logger=None):
        # use either the given messager function or define a simple print messager function which takes a level argument as second optional input
        if messagerFct:
            self.message = messagerFct
        else:
            self.message = lambda a,b='Info': print(b + ': ' + a)
        
        self.logger = logger
        checkThese = ['cancelOrder','createLimitOrder','fetchBalance','fetchTicker']
        self.tradeSets = {}
        self.tradeSetHistory = []
        if exchName == 'kucoin':
            exchName = exchName.replace('kucoin','kucoin2')
        self.exchange = getattr (ccxt, exchName) ({'enableRateLimit': True,'options': { 'adjustForTimeDifference': True }}) # 'nonce': ccxt.Exchange.milliseconds,
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
            self.updateKeys(key,secret,password,uid)
                        
        if not all([self.exchange.has[x] for x in checkThese]):
            text = 'Exchange %s does not support all required features (%s)'%(exchName,', '.join(checkThese))
            self.message(text,'error')
            raise Exception(text)
        self.lastUpdate = time.time()-10
        self.amount2Prec = lambda a,b: self.stripZeros(self.exchange.amountToPrecision(a,b)) if isinstance(self.exchange.amountToPrecision(a,b),str) else self.stripZeros(format(self.exchange.amountToPrecision(a,b),'.10f'))
        self.price2Prec = lambda a,b: self.stripZeros(self.exchange.priceToPrecision(a,b)) if isinstance(self.exchange.priceToPrecision(a,b),str) else self.stripZeros(format(self.exchange.priceToPrecision(a,b),'.10f'))
        self.cost2Prec = lambda a,b: self.stripZeros(self.exchange.costToPrecision(a,b)) if isinstance(self.exchange.costToPrecision(a,b),str) else self.stripZeros(format(self.exchange.costToPrecision(a,b),'.10f'))
        self.fee2Prec = lambda a,b: self.stripZeros(str(b))
        
        
          
    def __reduce__(self):
        # function needes for serializing the object
        return (self.__class__, (self.exchange.__class__.__name__,None,None,None,None,self.message),self.__getstate__(),None,None)
    
    def __setstate__(self,state):
        if isinstance(state,tuple):
            state,tshs = state
        else:
            tshs = []
        for iTs in state: # temp fix for old trade sets that do not some of the newer fields
            ts = state[iTs]
            # clear updating variables from old state
            ts['waiting'] = []
            ts['updating'] = False
            if 'trailingSL' not in ts:
                ts['trailingSL'] = [None,None]
            if 'dailycloseSL' not in ts:
                ts['dailycloseSL'] = None  
            if 'weeklycloseSL' not in ts:
                ts['weeklycloseSL'] = None 
            for trade in ts['InTrades']:
                if 'actualAmount' not in trade:
                    fee = self.calculateFee(ts['symbol'],'limit','buy',trade['amount'],trade['price'],'maker')
                    if fee['currency'] == ts['coinCurrency']:
                        trade['actualAmount'] = trade['amount'] - (fee['cost'] if self.exchange.name.lower() != 'binance' or self.getFreeBalance('BNB') < 0.5 else 0) # this is a hack, as fees on binance are deduced from BNB if this is activated and there is enough BNB, however so far no API chance to see if this is the case. Here I assume that 0.5 BNB are enough to pay the fee for the trade and thus the fee is not subtracted from the traded coin
                    else:
                        trade['actualAmount'] = trade['amount']
        self.tradeSets = state
        self.tradeSetHistory = tshs
        
    def __getstate__(self):
        if hasattr(self,'tradeSetHistory'):
            return (self.tradeSets,self.tradeSetHistory)
        else:
            return (self.tradeSets,[])
    
    @staticmethod
    def stripZeros(string):
        if '.' in string:
            return string.rstrip('0').rstrip('.')
        else:
            return string
        
    def checkNum(self,*value):
        return all([(isinstance(val,float) | isinstance(val,int)) if not isinstance(val,list) else self.checkNum(*val) for val in value])
    
    def checkQuantity(self,symbol,typ,qty):
        if typ not in ['amount','price','cost']:
            raise ValueError('Type is not amount, price or cost')
        if typ in self.exchange.markets[symbol]['limits']:
            return (self.exchange.markets[symbol]['limits'][typ]['min'] is None or qty >= self.exchange.markets[symbol]['limits'][typ]['min']) and (self.exchange.markets[symbol]['limits'][typ]['max'] is None or self.exchange.markets[symbol]['limits'][typ]['max'] == 0 or qty <= self.exchange.markets[symbol]['limits'][typ]['max'])
        else:
            if self.logger:
                self.logger.warning('Exchange %s does not provide limits for %s'%(self.exchange.name,typ))
            return True
        
    def safeRun(self,func,printError=True,iTs=None):
        count = 0
        wasdown = self.down
        while True:
            try:
                self.down = False
                return func()
            except NetworkError as e:
                count += 1
                if hasattr(self.exchange, 'load_time_difference'):
                    self.exchange.load_time_difference()
                if count >= 5:
                    if iTs:
                        self.unlockTradeSet(iTs)
                    if 'Cloudflare' in str(e):
                        self.down = True
                        if printError:
                             self.message('Cloudflare problem with exchange %s. Exchange is treated as down.'%(self.exchange.name,'' if iTs is None else ' for tradeSet %d (%s)'%(list(self.tradeSets.keys()).index(iTs))),'Error')   
                    elif printError:
                        self.message('Network exception occurred 5 times in a row on %s%s'%(self.exchange.name,'' if iTs is None else ' for tradeSet %d (%s)'%(list(self.tradeSets.keys()).index(iTs),self.tradeSets[iTs]['symbol'])),'Error')
                    raise(e)
                else:
                    time.sleep(0.5)
                    continue
            except OrderNotFound as e:
                count += 1
                if count >= 5:
                    if iTs:
                        self.unlockTradeSet(iTs)
                    if printError:
                        self.message('Order not found error 5 times in a row on %s%s'%(self.exchange.name,'' if iTs is None else ' for tradeSet %d (%s)'%(list(self.tradeSets.keys()).index(iTs),self.tradeSets[iTs]['symbol'])),'Error')
                    raise(e)
                else:
                    time.sleep(0.5)
                    continue
            except AuthenticationError as e:
                count += 1
                if count >= 5:
                    if iTs:
                        self.unlockTradeSet(iTs)
                    raise(e)
                else:
                    time.sleep(0.5)
                    continue
            except InvalidNonce as e:
                count += 1
                # this tries to resync the system timestamp with the exchange's timestamp
                if hasattr(self.exchange, 'load_time_difference'):
                    self.exchange.load_time_difference()
                time.sleep(0.5)
                continue
            except JSONDecodeError as e:
                if iTs:
                    self.unlockTradeSet(iTs)
                if 'Expecting value' in str(e):
                    self.down = True
                    if printError:
                        self.message('%s seems to be down.'%self.exchange.name)   
                raise(e)
            except Exception as e:
                if count < 4 and isinstance(e,ExchangeError) and "symbol" in str(e).lower():
                    self.safeRun(self.exchange.loadMarkets)
                    count += 1
                    continue
                elif count < 4 and ('unknown error' in str(e).lower() or 'connection' in str(e).lower()):
                    count += 1
                    time.sleep(0.5)
                    continue
                else:
                    if iTs:
                        self.unlockTradeSet(iTs)
                    string = 'Exchange %s\n'%self.exchange.name
                    if count >= 5:
                        string += 'Network exception occurred 5 times in a row! Last error was:\n'
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    #fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    lines = getsourcelines(func)
                    string += '%s in %s from %s at line %d: %s'%(exc_type, lines[0][0],os.path.basename(getsourcefile(func)),lines[1],str(e))

                    if printError:
                        self.message(string,'Error')
                    raise(e)
            finally:
                if wasdown and not self.down:
                    self.message('Exchange %s seems back to work!'%self.exchange.name)
        

    def lockTradeSet(self,iTs):
        # avoids two processes changing a tradeset at the same time
        count = 0
        mystamp = time.time()
        self.tradeSets[iTs]['waiting'].append(mystamp)
        time.sleep(0.2)
        while self.tradeSets[iTs]['updating'] or self.tradeSets[iTs]['waiting'][0] < mystamp:
            count += 1
            time.sleep(1)		
            if count > 60: # 60 sec max wait
                try:  # cautionary so that no timestamp can stay in the queue due to some messaging error
                    self.message('Waiting for tradeSet update (%s on %s) to finish timed out after 1 min.. Resetting updating variable now.'%(self.tradeSets[iTs]['symbol'],self.exchange.name),'error')
                except:
                    pass
                break
        self.tradeSets[iTs]['updating'] = True
        self.tradeSets[iTs]['waiting'].remove(mystamp)
    
    def unlockTradeSet(self,iTs):
        self.tradeSets[iTs]['updating'] = False
        
    def updateBalance(self):
        self.updateDownState(True)
        # reloads the exchange market and private balance and, if successul, sets the exchange as authenticated
        self.safeRun(self.exchange.loadMarkets) 
        self.balance = self.safeRun(self.exchange.fetch_balance)
        self.authenticated = True
        
    def getFreeBalance(self,coin):
        if coin in self.balance:
            return self.balance[coin]['free']
        else:
            return 0

    def updateKeys(self,key=None,secret=None,password=None,uid=None):
        if key:
            self.exchange.apiKey = key
        if secret:
            self.exchange.secret = secret
        if password:
            self.exchange.password = password
        if uid:
            self.exchange.uid = uid
        try: # check if keys work
            self.updateBalance()
        except AuthenticationError as e:#
            self.authenticated = False
            try:
                self.message('Failed to authenticate at exchange %s. Please check your keys'%self.exchange.name,'error')
            except:
                print('Failed to authenticate at exchange %s. Please check your keys'%self.exchange.name)
        except getattr(ccxt,'ExchangeError') as e:
            self.authenticated = False
            if 'key' in str(e).lower():
                try:
                    self.message('Failed to authenticate at exchange %s. Please check your keys'%self.exchange.name,'error')
                except:
                    print('Failed to authenticate at exchange %s. Please check your keys'%self.exchange.name)
            else:
                try:
                    self.message('The following error occured at exchange %s:\n%s'%(self.exchange.name,str(e)),'error')
                except:
                    print('The following error occured at exchange %s:\n%s'%(self.exchange.name,str(e)))
          
    def calculateFee(self,symbol, typ, direction, amount, price, makerOrTaker):
        return self.exchange.calculateFee(symbol, typ, direction, amount, price, makerOrTaker)
        
    def initTradeSet(self,symbol):
        self.updateBalance()
        
        iTs = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
        # redo if uid already reserved
        while iTs in self.tradeSets:
            iTs = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
        
        ts = {'symbol': symbol,'InTrades': [],'createdAt': time.time(), \
              'OutTrades': [], 'baseCurrency': re.search("(?<=/).*", symbol).group(0), \
              'coinCurrency': re.search(".*(?=/)", symbol).group(0), 'costIn': 0, \
              'costOut': 0, 'coinsAvail': 0, 'initCoins': 0, 'initPrice': None, \
              'SL': None, 'trailingSL': [None, None], 'dailycloseSL': None, \
              'weeklycloseSL': None, 'active': False, 'virgin': True, 'updating': False, \
              'waiting':  []}
        self.tradeSets[iTs] = ts
        return ts, iTs
        
    def activateTradeSet(self,iTs,verbose=True):
        self.updateDownState(True)
        ts = self.tradeSets[iTs]
        wasactive = ts['active']
        # check if symbol is active
        if not self.exchange.markets[ts['symbol']]['active']:
            self.message('Cannot activate trade set because %s was deactivated for trading by the exchange!'%ts['symbol'],'error')
            return wasactive
        # sanity check of amounts to buy/sell
        if self.sumSellAmounts(iTs,'notinitiated') - (self.sumBuyAmounts(iTs,'notfilled')+ ts['coinsAvail']) > 0:
            self.message('Cannot activate trade set because the total amount you (still) want to sell (%s %s) exceeds the total amount you want to buy (%s %s after fee subtraction) and the amount you already have in this trade set (%s %s). Please adjust the trade set!'%(self.amount2Prec(ts['symbol'],self.sumSellAmounts(iTs,'notinitiated',1)),ts['coinCurrency'],self.amount2Prec(ts['symbol'],self.sumBuyAmounts(iTs,'notfilled',1)),ts['coinCurrency'],self.amount2Prec(ts['symbol'],ts['coinsAvail']),ts['coinCurrency']), 'error')
            return wasactive
        elif self.minBuyPrice(iTs,order='notfilled') is not None and ts['SL'] is not None and ts['SL'] >= self.minBuyPrice(iTs,order='notfilled'):
            self.message('Cannot activate trade set because the current stop loss price is higher than the lowest non-filled buy order price, which means this buy order could never be reached. Please adjust the trade set!','error')
            return wasactive
        self.tradeSets[iTs]['virgin'] = False
        self.tradeSets[iTs]['active'] = True
        if verbose and not wasactive:
            totalBuyCost = ts['costIn'] + self.sumBuyCosts(iTs,'notfilled')
            self.message('Estimated return if all trades are executed: %s %s'%(self.cost2Prec(ts['symbol'],self.sumSellCosts(iTs)-totalBuyCost),ts['baseCurrency']))
            if ts['SL'] is not None or ts['dailycloseSL'] is not None:
                sl = [val for val in [ts['SL'] ,ts['dailycloseSL'] if 'dailycloseSL' in ts else None,ts['weeklycloseSL'] if 'weeklycloseSL' in ts else None,] if val is not None][0]
                loss = totalBuyCost - ts['costOut'] - (ts['initCoins']+self.sumBuyAmounts(iTs)-self.sumSellAmounts(iTs,'filled'))*sl
                self.message('Estimated %s if buys reach stop-loss before selling: %s %s'%('*gain*' if loss<0 else 'loss',self.cost2Prec(ts['symbol'],-loss if loss<0 else loss),ts['baseCurrency']))        
        try:
            self.initBuyOrders(iTs)
        except InsufficientFunds as e:
            self.message('Cannot activate trade set due to insufficient funds!','error')
            self.deactivateTradeSet(iTs)
        return wasactive
    
    def deactivateTradeSet(self,iTs,cancelOrders=0):
        self.updateDownState(True)
        # cancelOrders can be 0 (not), 1 (cancel), 2 (cancel and delete open orders)
        wasactive = self.tradeSets[iTs]['active']
        if cancelOrders:
            self.cancelBuyOrders(iTs,deleteOrders=cancelOrders==2)
            self.cancelSellOrders(iTs,deleteOrders=cancelOrders==2)
        self.tradeSets[iTs]['active'] = False
        return wasactive
        
    def newTradeSet(self,symbol,buyLevels=[],buyAmounts=[],sellLevels=[],sellAmounts=[],sl=None,candleAbove=[],initCoins=0,initPrice=None,force=False):
        self.updateDownState(True)
        if symbol not in self.exchange.symbols:
            raise NameError('Trading pair %s not found on %s'%(symbol,self.exchange.name))
        if not self.checkNum(buyAmounts) or not self.checkNum(buyLevels):
            raise TypeError('Buy levels and amounts must be of type float!')
        if not self.checkNum(sellAmounts) or not self.checkNum(sellLevels):
            raise TypeError('Sell levels and amounts must be of type float!')
        if sl and not self.checkNum(sl):
            raise TypeError('Stop-loss must be of type float!')
        if not self.checkNum(initCoins): 
            raise TypeError('Initial coin amount must be of type float!')
        if len(buyLevels)!=len(buyAmounts):
            raise ValueError('The number of buy levels and buy amounts has to be the same')
        if len(sellLevels)!=len(sellAmounts):
            raise ValueError('The number of sell levels and sell amounts has to be the same')
          
        ts, iTs = self.initTradeSet(symbol)

        # truncate values to precision        
        sellLevels = [float(self.exchange.priceToPrecision(ts['symbol'],val)) for val in sellLevels]
        buyLevels = [float(self.exchange.priceToPrecision(ts['symbol'],val)) for val in buyLevels]
        sellAmounts = [float(self.exchange.amountToPrecision(ts['symbol'],val)) for val in sellAmounts]
        buyAmounts = [float(self.exchange.amountToPrecision(ts['symbol'],val)) for val in buyAmounts]

        # sort sell levels and amounts to have lowest level first
        idx = np.argsort(sellLevels)
        sellLevels = np.array(sellLevels)[idx]
        sellAmounts = np.array(sellAmounts)[idx]
        buyLevels = np.array(buyLevels)
        buyAmounts = np.array(buyAmounts)
        if len(buyAmounts) != len(candleAbove):
            candleAbove = np.repeat(None,len(buyAmounts))
        else:
            candleAbove = np.array(candleAbove)

        if not force and sum(buyAmounts) != sum(sellAmounts):
            if self.logger:
                self.logger.warning('It seems the buy and sell amount of %s is not the same. Is this correct?'%ts['coinCurrency'])
        if buyLevels.size > 0 and sellLevels.size > 0 and max(buyLevels) > min(sellLevels):
            raise ValueError('It seems at least one of your sell prices is lower than one of your buy, which does not make sense')
        if self.balance[ts['baseCurrency']]['free'] < sum(buyLevels*buyAmounts):
            raise ValueError('Free balance of %s not sufficient to initiate trade set'%ts['baseCurrency'])
        
        # create the buy orders
        for n,_ in enumerate(buyLevels):
            self.addBuyLevel(iTs,buyLevels[n],buyAmounts[n],candleAbove[n])
        
        self.addInitCoins(iTs,initCoins,initPrice)
        self.setSL(iTs,sl)
        self.setTrailingSL(iTs,None)
        # create the sell orders
        for n,_ in enumerate(sellLevels):
            self.addSellLevel(iTs,sellLevels[n],sellAmounts[n])

        self.activateTradeSet(iTs)
        self.update()
        return iTs
        
    def getTradeSetInfo(self,iTs,showProfitIn=None):
        ts = self.tradeSets[iTs]
        string = '*%srade set #%d on %s%s [%s]:*\n'%('T' if ts['active'] else 'INACTIVE t',list(self.tradeSets.keys()).index(iTs),self.exchange.name,' (DOWN !!!) ' if self.down else '',ts['symbol'])
        filledBuys = []
        filledSells = []
        for iTrade,trade in enumerate(ts['InTrades']):
            tmpstr = '*Buy level %d:* Price %s , Amount %s %s   '%(iTrade,self.price2Prec(ts['symbol'],trade['price']),self.amount2Prec(ts['symbol'],trade['amount']),ts['coinCurrency'])
            if trade['oid'] is None:
                if trade['candleAbove'] is None:
                    tmpstr = tmpstr + '_Order not initiated_\n'
                else:
                    tmpstr = tmpstr + 'if DC > %s\n'%self.price2Prec(ts['symbol'],trade['candleAbove'])
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                filledBuys.append([trade['actualAmount'],trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            string += tmpstr
        string+= '\n'
        for iTrade,trade in enumerate(ts['OutTrades']):
            tmpstr = '*Sell level %d:* Price %s , Amount %s %s   '%(iTrade,self.price2Prec(ts['symbol'],trade['price']),self.amount2Prec(ts['symbol'],trade['amount']),ts['coinCurrency'])
            if trade['oid'] is None:
                tmpstr = tmpstr + '_Order not initiated_\n'
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                filledSells.append([trade['amount'],trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            string += tmpstr
        if ts['SL'] is not None:
            string += '\n*Stop-loss* set at %s%s\n\n'%(self.price2Prec(ts['symbol'],ts['SL']),'' if ts['trailingSL'][0] is None else (' (trailing with offset %.5g)'%ts['trailingSL'][0] if ts['trailingSL'][1] == 'abs' else ' (trailing with offset %.2g %%)'%(ts['trailingSL'][0]*100) ))
        elif ts['dailycloseSL'] is not None:
            string += '\n*Stop-loss* set at daily close < %s\n\n'%(self.price2Prec(ts['symbol'],ts['dailycloseSL']))
        elif ts['weeklycloseSL'] is not None:
            string += '\n*Stop-loss* set at weekly close < %s\n\n'%(self.price2Prec(ts['symbol'],ts['weeklycloseSL']))
        else:
            string += '\n*No stop-loss set.*\n\n'
        sumBuys = sum([val[0] for val in filledBuys])
        sumSells = sum([val[0] for val in filledSells])
        if ts['initCoins']>0:
            string += '*Initial coins:* %s %s for an average price of %s\n'%(self.amount2Prec(ts['symbol'],ts['initCoins']),ts['coinCurrency'],self.price2Prec(ts['symbol'],ts['initPrice']) if ts['initPrice'] is not None else 'unknown')
        if sumBuys>0:
            string += '*Filled buy orders (fee subtracted):* %s %s for an average price of %s\n'%(self.amount2Prec(ts['symbol'],sumBuys),ts['coinCurrency'],self.cost2Prec(ts['symbol'],sum([val[0]*val[1]/sumBuys if sumBuys > 0 else None for val in filledBuys])))
        if sumSells>0:
            string += '*Filled sell orders:* %s %s for an average price of %s\n'%(self.amount2Prec(ts['symbol'],sumSells),ts['coinCurrency'],self.cost2Prec(ts['symbol'],sum([val[0]*val[1]/sumSells if sumSells > 0 else None for val in filledSells])))
        if self.exchange.markets[ts['symbol']]['active']:
            ticker = self.safeRun(lambda: self.exchange.fetchTicker(ts['symbol']))
            string += '\n*Current market price *: %s, \t24h-high: %s, \t24h-low: %s\n'%tuple([self.price2Prec(ts['symbol'],val) for val in [ticker['last'],ticker['high'],ticker['low']]])
            if (ts['initCoins'] == 0 or ts['initPrice'] is not None) and ts['costIn'] > 0 and (sumBuys>0 or ts['initCoins'] > 0):
                totalAmountToSell = ts['coinsAvail'] + self.sumSellAmounts(iTs,'open')
                fee = self.calculateFee(ts['symbol'],'market','sell',totalAmountToSell,ticker['last'] ,'taker')
                costSells = ts['costOut'] +   ticker['last'] * totalAmountToSell - (fee['cost'] if fee['currency'] == ts['baseCurrency'] else 0)
                gain = costSells - ts['costIn']
                gainOrig = gain
                if showProfitIn is not None:
                    gain,thisCur = self.convertAmount(gain,ts['baseCurrency'],showProfitIn)
                else:
                    thisCur = ts['baseCurrency']
                string += '\n*Estimated gain/loss when selling all now: * %s %s (%+.2f %%)\n'%(self.cost2Prec(ts['symbol'],gain),thisCur,gainOrig/(ts['costIn'])*100)
        else:
            string += '\n*Warning: Symbol %s is currently deactivated for trading by the exchange!*\n'%ts['symbol']
        return string
    

    def createTradeHistoryEntry(self,iTs):
        self.updateDownState(True)
        # create a trade history entry if the trade set had any filled orders
        ts = self.tradeSets[iTs]
        if self.numBuyLevels(iTs,'filled') > 0 or self.numSellLevels(iTs,'filled') > 0:
            gain = ts['costOut']-ts['costIn']
            # try to convert gain amount into btc currency
            gainBTC,curr = self.convertAmount(gain,ts['baseCurrency'],'BTC')
            if curr != 'BTC':
                gainBTC = None
            if gainBTC:
                # try to convert btc gain into usd currency
                gainUSD,curr = self.convertAmount(gainBTC,'BTC','USD')
                if curr != 'USD':
                    gainUSD,curr = self.convertAmount(gainBTC,'BTC','USDT')
                    if curr != 'USDT':
                        gainUSD = None
            else:
                gainUSD = None
            self.tradeSetHistory.append({'time':time.time(),'days':None if not 'createdAt' in ts else (time.time()-ts['createdAt'])/60/60/24 ,'symbol':ts['symbol'],'gain':gain,'gainRel':gain/(ts['costIn'])*100 if ts['costIn']>0 else None,'quote':ts['baseCurrency'],'gainBTC':gainBTC,'gainUSD':gainUSD})
    
    def getTradeHistory(self):
        string = ''
        for tsh in self.tradeSetHistory:
            string += '%s:  %s\t%s%% ( %s BTC | %s USD)\n'%(datetime.datetime.utcfromtimestamp(tsh['time']).strftime('%Y-%m-%d'),tsh['symbol'],'%+7.1f'%tsh['gainRel'] if tsh['gainRel'] else 'N/A','%+.5f'%tsh['gainBTC'] if tsh['gainBTC'] else 'N/A','%+.2f'%tsh['gainUSD'] if tsh['gainUSD'] else 'N/A')
        if len(self.tradeSetHistory) > 0:
            return '*Profit history on %s:\nAvg. relative gain: %+7.1f%%\nTotal profit in BTC: %+.5f\nTotal profit in USD: %+.2f\n\nDetailed Set Info:\n*'%(self.exchange.name,np.mean([tsh['gainRel'] for tsh in self.tradeSetHistory if tsh['gainRel'] is not None]),sum([tsh['gainBTC'] if tsh['gainBTC'] else 0 for tsh in self.tradeSetHistory]),sum([tsh['gainUSD'] if tsh['gainUSD'] else 0 for tsh in self.tradeSetHistory])) + string
        else:
            return '*No profit history on %s*'%self.exchange.name
    
    def resetTradeHistory(self):
        self.tradeSetHistory = []
        return 1
    
    def convertAmount(self,amount,currency,targetCurrency):
        self.updateDownState(True)
        if isinstance(targetCurrency,str):
            targetCurrency = [targetCurrency]
            
        conversionPairs = [('%s/%s'%(currency,cur) in self.exchange.symbols and self.exchange.markets['%s/%s'%(currency,cur)]['active']) + 2*('%s/%s'%(cur,currency) in self.exchange.symbols and self.exchange.markets['%s/%s'%(cur,currency)]['active']) for cur in targetCurrency]
        ind = next((i for i, x in enumerate(conversionPairs) if x), None)
        if ind is not None:
            thisCur = targetCurrency[ind]
            if conversionPairs[ind] == 1:
                amount *= self.safeRun(lambda: self.exchange.fetchTicker('%s/%s'%(currency,thisCur)))['last']
            else:
                amount /= self.safeRun(lambda: self.exchange.fetchTicker('%s/%s'%(thisCur,currency)))['last']
            return (amount,thisCur)
        else:
            return (amount,currency)
        
        
    def deleteTradeSet(self,iTs,sellAll=False):
        self.updateDownState(True)
        self.lockTradeSet(iTs)
        if sellAll:
            sold = self.sellAllNow(iTs)
        else:
            sold = True
            self.deactivateTradeSet(iTs,1)
        if sold:
            self.createTradeHistoryEntry(iTs)
            self.tradeSets.pop(iTs)
        else:
            self.unlockTradeSet(iTs)
    
    def addInitCoins(self,iTs,initCoins=0,initPrice=None):
        if self.checkNum(initCoins,initPrice) or (initPrice is None and self.checkNum(initCoins)):
            if initPrice is not None and initPrice < 0:
                initPrice = None
            ts = self.tradeSets[iTs]
            # check if free balance is indeed sufficient
            if self.getFreeBalance(ts['coinCurrency']) < initCoins:
                self.message('Adding initial balance failed: %s %s requested but only %s %s are free!'%(self.amount2Prec(ts['symbol'],initCoins),ts['coinCurrency'],self.amount2Prec(ts['symbol'],self.getFreeBalance(ts['coinCurrency'])),ts['coinCurrency']),'error')
                return 0
            self.lockTradeSet(iTs)
            
            if ts['coinsAvail'] > 0 and ts['initPrice'] is not None:
                # remove old cost again
                ts['costIn'] -= (ts['coinsAvail']*ts['initPrice'])
            ts['coinsAvail'] = initCoins
            ts['initCoins'] = initCoins
            
            ts['initPrice'] = initPrice
            if initPrice is not None:
                ts['costIn'] += (initCoins*initPrice)
            self.unlockTradeSet(iTs)
            return 1
        else:
            raise ValueError('Some input was no number')
            
    def numBuyLevels(self,iTs, order='all'):
        return self.getTradeParam(iTs,'amount','num','buy',order)
    
    def numSellLevels(self,iTs, order='all'):
        return self.getTradeParam(iTs,'amount','num','sell',order)

    def sumBuyAmounts(self,iTs,order='all',subtractFee = True):
        return self.getTradeParam(iTs,'amount','sum','buy',order,subtractFee)
    
    def sumSellAmounts(self,iTs,order='all',subtractFee = True):
        return self.getTradeParam(iTs,'amount','sum','sell',order,subtractFee)
    
    def sumBuyCosts(self,iTs,order='all',subtractFee = True):
        return self.getTradeParam(iTs,'cost','sum','buy',order,subtractFee)
    
    def sumSellCosts(self,iTs,order='all',subtractFee = True):
        return self.getTradeParam(iTs,'cost','sum','sell',order,subtractFee)
    
    def minBuyPrice(self,iTs,order='all'):
        return self.getTradeParam(iTs,'price','min','buy',order)
    
    def getTradeParam(self,iTs,what,method,direction, order='all',subtractFee = True):
        if method == 'sum':
            func = lambda x: sum(x)
        elif method == 'min':
            func = lambda x: None if len(x)==0 else np.min(x)
        elif method == 'max':
            func = lambda x: None if len(x)==0 else np.max(x)
        elif method == 'mean':
            func = lambda x: None if len(x)==0 else np.mean(x)
        elif method == 'num':
            func = lambda x: len(x)
            
        if direction == 'sell':
            trade = 'OutTrades'
        else:
            trade = 'InTrades'
            
        if order not in ['all','filled','open','notfilled','notinitiated']:
            raise ValueError('order has to be all, filled, notfilled, notinitiated or open')
            
        if what == 'amount':
            if order == 'all':
                return func([(val['amount'] if direction == 'sell' or subtractFee == False else val['actualAmount']) for val in self.tradeSets[iTs][trade]])
            elif order == 'filled':
                return func([(val['amount'] if direction == 'sell' or subtractFee == False else val['actualAmount'])  for val in self.tradeSets[iTs][trade] if val['oid'] == 'filled'])
            elif order == 'open':
                return func([(val['amount'] if direction == 'sell' or subtractFee == False else val['actualAmount'])  for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled' and val['oid'] is not None])
            elif order == 'notinitiated':
                return func([(val['amount'] if direction == 'sell' or subtractFee == False else val['actualAmount'])  for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled' and val['oid'] is None])
            elif order == 'notfilled':
                return func([(val['amount'] if direction == 'sell' or subtractFee == False else val['actualAmount'])  for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled'])
        elif what == 'price':
            if order == 'all':
                return func([val['price'] for val in self.tradeSets[iTs][trade]])
            elif order == 'filled':
                return func([val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] == 'filled'])
            elif order == 'open':
                return func([val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled' and val['oid'] is not None])
            elif order == 'notinitiated':
                return func([val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled' and val['oid'] is None])
            elif order == 'notfilled':
                return func([val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled'])   
        elif what == 'cost':
            if order == 'all':
                return func([val['amount']*val['price'] for val in self.tradeSets[iTs][trade]])
            elif order == 'filled':
                return func([val['amount']*val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] == 'filled'])
            elif order == 'open':
                return func([val['amount']*val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled' and val['oid'] is not None])
            elif order == 'notinitiated':
                return func([val['amount']*val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled' and val['oid'] is None])
            elif order == 'notfilled':
                return func([val['amount']*val['price'] for val in self.tradeSets[iTs][trade] if val['oid'] != 'filled'])   
            
    
    def addBuyLevel(self,iTs,buyPrice,buyAmount,candleAbove=None):
        self.updateDownState(True)
        ts = self.tradeSets[iTs]
        if self.checkNum(buyPrice,buyAmount,candleAbove) or (candleAbove is None and self.checkNum(buyPrice,buyAmount)):
            fee = self.calculateFee(ts['symbol'],'limit','buy',buyAmount,buyPrice,'maker')
            if not self.checkQuantity(ts['symbol'],'amount',buyAmount):
                self.message('Adding buy level failed, amount is not within the range, the exchange accepts','error')
                return 0
            elif not self.checkQuantity(ts['symbol'],'price',buyPrice):
                self.message('Adding buy level failed, price is not within the range, the exchange accepts','error')
                return 0 
            elif not self.checkQuantity(ts['symbol'],'cost',buyPrice*buyAmount):
                self.message('Adding buy level failed, cost is not within the range, the exchange accepts','error')
                return 0 
            elif self.getFreeBalance(ts['baseCurrency']) < buyAmount*buyPrice + fee['cost'] if fee['currency'] == ts['baseCurrency'] else 0:
                self.message('Adding buy level failed, your balance of %s does not suffice to buy this amount%s!'%(ts['baseCurrency'],' and pay the trading fee (%s %s)'%(self.fee2Prec(ts['symbol'],fee['cost']),ts['baseCurrency']) if fee['currency'] == ts['baseCurrency'] else ''),'error')
                return 0 
            
            if fee['currency'] == ts['coinCurrency']:
                boughtAmount = buyAmount - (fee['cost'] if (self.exchange.name.lower() != 'binance' or self.getFreeBalance('BNB') < 0.5) else 0) # this is a hack, as fees on binance are deduced from BNB if this is activated and there is enough BNB, however so far no API chance to see if this is the case. Here I assume that 0.5 BNB are enough to pay the fee for the trade and thus the fee is not subtracted from the traded coin
            else:
                boughtAmount = buyAmount
            self.lockTradeSet(iTs)
            wasactive = self.deactivateTradeSet(iTs)  
            ts['InTrades'].append({'oid': None, 'price': buyPrice, 'amount': buyAmount, 'actualAmount': boughtAmount, 'candleAbove': candleAbove})
            if wasactive:
                self.activateTradeSet(iTs,0)   
            self.unlockTradeSet(iTs)
            return  self.numBuyLevels(iTs)-1
        else:
            raise ValueError('Some input was no number')
    
    def deleteBuyLevel(self,iTs,iTrade):
        self.updateDownState(True)
        if self.checkNum(iTrade):
            self.lockTradeSet(iTs)
            ts = self.tradeSets[iTs]
            wasactive = self.deactivateTradeSet(iTs)
            if ts['InTrades'][iTrade]['oid'] is not None and ts['InTrades'][iTrade]['oid'] != 'filled' :
                self.cancelBuyOrders(iTs,ts['InTrades'][iTrade]['oid'])
            ts['InTrades'].pop(iTrade)
            if wasactive:
                self.activateTradeSet(iTs,0) 
            self.unlockTradeSet(iTs)
        else:
            raise ValueError('Some input was no number')
            
    def setBuyLevel(self,iTs,iTrade,price,amount): 
        self.updateDownState(True)
        if self.checkNum(iTrade,price,amount):
            ts = self.tradeSets[iTs]
            if ts['InTrades'][iTrade]['oid'] == 'filled':
                self.message('This order is already filled! No change possible')
                return 0
            else:
                fee = self.calculateFee(ts['symbol'],'limit','buy',amount,price,'maker')
                if not self.checkQuantity(ts['symbol'],'amount',amount):
                    self.message('Changing buy level failed, amount is not within the range, the exchange accepts')
                    return 0
                elif not self.checkQuantity(ts['symbol'],'price',price):
                    self.message('Changing buy level failed, price is not within the range, the exchange accepts')
                    return 0 
                elif not self.checkQuantity(ts['symbol'],'cost',price*amount):
                    self.message('Changing buy level failed, cost is not within the range, the exchange accepts')
                    return 0 
                elif self.getFreeBalance(ts['baseCurrency']) + ts['InTrades'][iTrade]['amount']*ts['InTrades'][iTrade]['price'] < amount*price + fee['cost'] if fee['currency'] == ts['baseCurrency'] else 0:
                    self.message('Changing buy level failed, your balance of %s does not suffice to buy this amount%s!'%(ts['baseCurrency'],' and pay the trading fee (%s %s)'%(self.fee2Prec(ts['symbol'],fee['cost']),ts['baseCurrency']) if fee['currency'] == ts['baseCurrency'] else ''))
                    return 0 
                if fee['currency'] == ts['coinCurrency']:
                    boughtAmount = amount - (fee['cost'] if (self.exchange.name.lower() != 'binance' or self.getFreeBalance('BNB') < 0.5) else 0) # this is a hack, as fees on binance are deduced from BNB if this is activated and there is enough BNB, however so far no API chance to see if this is the case. Here I assume that 0.5 BNB are enough to pay the fee for the trade and thus the fee is not subtracted from the traded coin
                else:
                    boughtAmount = amount
                wasactive = self.deactivateTradeSet(iTs)  
                
                if ts['InTrades'][iTrade]['oid'] is not None and ts['InTrades'][iTrade]['oid'] != 'filled' :
                    returnVal = self.cancelBuyOrders(iTs,ts['InTrades'][iTrade]['oid'])
                    ts['InTrades'][iTrade]['oid'] = None
                if returnVal == 0.5 and self.getFreeBalance(ts['baseCurrency']) + ts['InTrades'][iTrade]['amount']*ts['InTrades'][iTrade]['price'] < amount*price + fee['cost'] if fee['currency'] == ts['baseCurrency'] else 0:
                    self.message('Changing buy level failed, your balance of %s does not suffice to buy this amount%s!'%(ts['baseCurrency'],' and pay the trading fee (%s %s)'%(self.fee2Prec(ts['symbol'],fee['cost']),ts['baseCurrency']) if fee['currency'] == ts['baseCurrency'] else ''))
                    return 0
                ts['InTrades'][iTrade].update({'amount': amount, 'actualAmount': boughtAmount, 'price': price})
                    
                if wasactive:
                    self.activateTradeSet(iTs,0)                
                return 1
        else:
            raise ValueError('Some input was no number')
    
    def addSellLevel(self,iTs,sellPrice,sellAmount):
        self.updateDownState(True)
        ts = self.tradeSets[iTs]
        if self.checkNum(sellPrice,sellAmount):
            if not self.checkQuantity(ts['symbol'],'amount',sellAmount):
                self.message('Adding sell level failed, amount is not within the range, the exchange accepts')
                return 0
            elif not self.checkQuantity(ts['symbol'],'price',sellPrice):
                self.message('Adding sell level failed, price is not within the range, the exchange accepts')
                return 0 
            elif not self.checkQuantity(ts['symbol'],'cost',sellPrice*sellAmount):
                self.message('Adding sell level failed, return is not within the range, the exchange accepts')
                return 0 
            self.lockTradeSet(iTs)
            wasactive = self.deactivateTradeSet(iTs)  
            ts['OutTrades'].append({'oid': None, 'price': sellPrice, 'amount': sellAmount})
            if wasactive:
                self.activateTradeSet(iTs,0)  
            self.unlockTradeSet(iTs)
            return  self.numSellLevels(iTs)-1
        else:
            raise ValueError('Some input was no number')

    def deleteSellLevel(self,iTs,iTrade):
        self.updateDownState(True)
        if self.checkNum(iTrade):
            self.lockTradeSet(iTs)
            ts = self.tradeSets[iTs]
            wasactive = self.deactivateTradeSet(iTs)
            if ts['OutTrades'][iTrade]['oid'] is not None and ts['OutTrades'][iTrade]['oid'] != 'filled' :
                self.cancelSellOrders(iTs,ts['OutTrades'][iTrade]['oid'])
            ts['OutTrades'].pop(iTrade)
            self.unlockTradeSet(iTs)
            if wasactive:
                self.activateTradeSet(iTs,0) 
        else:
            raise ValueError('Some input was no number')
    
    def setSellLevel(self,iTs,iTrade,price,amount):  
        self.updateDownState(True)
        if self.checkNum(iTrade,price,amount):
            ts = self.tradeSets[iTs]
            if ts['OutTrades'][iTrade]['oid'] == 'filled':
                self.message('This order is already filled! No change possible')
                return 0
            else:
                if not self.checkQuantity(ts['symbol'],'amount',amount):
                    self.message('Changing sell level failed, amount is not within the range, the exchange accepts')
                    return 0
                elif not self.checkQuantity(ts['symbol'],'price',price):
                    self.message('Changing sell level failed, price is not within the range, the exchange accepts')
                    return 0 
                elif not self.checkQuantity(ts['symbol'],'cost',price*amount):
                    self.message('Changing sell level failed, return is not within the range, the exchange accepts')
                    return 0 
                wasactive = self.deactivateTradeSet(iTs)  
                
                if ts['OutTrades'][iTrade]['oid'] is not None and ts['OutTrades'][iTrade]['oid'] != 'filled' :
                    self.cancelSellOrders(iTs,ts['OutTrades'][iTrade]['oid'])
                    ts['OutTrades'][iTrade]['oid'] = None

                ts['OutTrades'][iTrade]['amount'] = amount
                ts['OutTrades'][iTrade]['price'] = price
                
                if wasactive:
                    self.activateTradeSet(iTs,0)                
                return 1
        else:
            raise ValueError('Some input was no number')
            
    def setTrailingSL(self,iTs,value,typ='abs'): 
        self.updateDownState(True)
        ts = self.tradeSets[iTs]
        if self.checkNum(value):
            if self.numBuyLevels(iTs,'notfilled') > 0:
                raise Exception('Trailing SL cannot be set as there are non-filled buy orders still')
            ticker = self.safeRun(lambda: self.exchange.fetchTicker(ts['symbol']))
            if typ == 'abs':
                if value >= ticker['last'] or value <= 0:
                    raise ValueError('absolute trailing stop-loss offset is not between 0 and current price')
                newSL = ticker['last'] - value
            else:
                if value >= 1 or value <= 0:
                    raise ValueError('Relative trailing stop-loss offset is not between 0 and 1')
                newSL = ticker['last'] * (1- value)     
            ts['trailingSL'] = [value,typ]          
            ts['SL'] = newSL
            self.setDailyCloseSL(iTs,None)
            self.setWeeklyCloseSL(iTs,None)
        elif value is None:
            ts['trailingSL'] = [None,None]
        else:
            raise ValueError('Input was no number')
            
    def setWeeklyCloseSL(self,iTs,value):
        ts = self.tradeSets[iTs]
        if self.checkNum(value):
            ticker = self.safeRun(lambda: self.exchange.fetchTicker(ts['symbol']))
            if ticker['last'] <= value:
                self.message('Weekly-close SL is set but be aware that it is higher than the current market price!','Warning')
            ts['weeklycloseSL'] = value
            self.setDailyCloseSL(iTs,None)
            self.setTrailingSL(iTs,None) # deactivate trailing SL
            self.setSL(iTs,None)  # deactivate standard SL
        elif value is None:
            ts['weeklycloseSL'] = None
        else:
            raise ValueError('Input was no number')    
            
    def setDailyCloseSL(self,iTs,value):
        ts = self.tradeSets[iTs]
        if self.checkNum(value):
            ticker = self.safeRun(lambda: self.exchange.fetchTicker(ts['symbol']))
            if ticker['last'] <= value:
                self.message('Daily-close SL is set but be aware that it is higher than the current market price!','Warning')
            ts['dailycloseSL'] = value
            self.setWeeklyCloseSL(iTs,None)
            self.setTrailingSL(iTs,None) # deactivate trailing SL
            self.setSL(iTs,None)  # deactivate standard SL
        elif value is None:
            ts['dailycloseSL'] = None
        else:
            raise ValueError('Input was no number')    
    
    def setSL(self,iTs,value):   
        if self.checkNum(value):
            ts = self.tradeSets[iTs]
            ticker = self.safeRun(lambda: self.exchange.fetchTicker(ts['symbol']))
            if ticker['last'] <= value:
                self.message('Cannot set new SL as it is higher than the current market price')
                return 0
            self.setTrailingSL(iTs,None) # deactivate trailing SL
            self.setDailyCloseSL(iTs,None) # same for dailyclose SL
            self.setWeeklyCloseSL(iTs,None) # same for weeklycloseSL SL
            self.tradeSets[iTs]['SL'] = value
            return 1
        elif value is None:
            self.tradeSets[iTs]['SL'] = None
            return 1
        else:
            raise ValueError('Input was no number')
        
    def setSLBreakEven(self,iTs): 
        self.updateDownState(True)
        ts = self.tradeSets[iTs]         
        if ts['initCoins'] > 0 and ts['initPrice'] is None:
            self.message('Break even SL cannot be set as you this trade set contains %s that you obtained beforehand and no buy price information was given.'%ts['coinCurrency'])
            return 0
        elif ts['costOut'] - ts['costIn'] > 0:
            self.message('Break even SL cannot be set as your sold coins of this trade already outweigh your buy expenses (congrats!)! You might choose to sell everything immediately if this is what you want.')
            return 0
        elif ts['costOut'] - ts['costIn']  == 0:
            self.message('Break even SL cannot be set as there are no unsold %s coins right now'%ts['coinCurrency'])
            return 0
        else:
            breakEvenPrice = (ts['costIn']-ts['costOut'])/((1-self.exchange.fees['trading']['taker'])*(ts['coinsAvail']+sum([trade['amount'] for trade in ts['OutTrades'] if trade['oid'] != 'filled' and trade['oid'] is not None])))
            ticker = self.safeRun(lambda :self.exchange.fetchTicker(ts['symbol']))
            if ticker['last'] < breakEvenPrice:
                self.message('Break even SL of %s cannot be set as the current market price is lower (%s)!'%tuple([self.price2Prec(ts['symbol'],val) for val in [breakEvenPrice,ticker['last']]]))
                return 0
            else:
                self.setSL(iTs,breakEvenPrice)
                return 1

    def sellAllNow(self,iTs,price=None):
        self.updateDownState(True)
        self.deactivateTradeSet(iTs,2)
        ts = self.tradeSets[iTs]
        ts['SL'] = None # necessary to not retrigger SL
        ts['dailycloseSL'] = None # this one, too
        sold = True
                
        if ts['coinsAvail'] > 0 and self.checkQuantity(ts['symbol'],'amount',ts['coinsAvail']):
            if self.exchange.has['createMarketOrder']:
                try:
                    response = self.safeRun(lambda: self.exchange.createMarketSellOrder (ts['symbol'], ts['coinsAvail']),0)
                except InsufficientFunds:
                    freeBal = self.getFreeBalance(ts['coinCurrency'])
                    response = self.safeRun(lambda: self.exchange.createMarketSellOrder (ts['symbol'], freeBal),0)
                    self.message('When selling %s, only %s %s was found and sold!'%(ts['symbol'], self.amount2Prec(ts['symbol'],freeBal), ts['coinCurrency']),'warning')
                except:
                    params = { 'trading_agreement': 'agree' }  # for kraken api...
                    try:
                        response = self.safeRun(lambda: self.exchange.createMarketSellOrder (ts['symbol'], ts['coinsAvail'],params),iTs=iTs)
                    except InsufficientFunds:
                        freeBal = self.getFreeBalance(ts['coinCurrency'])
                        response = self.safeRun(lambda: self.exchange.createMarketSellOrder (ts['symbol'], freeBal),0)
                        self.message('When selling %s, only %s %s was found and sold!'%(ts['symbol'], self.amount2Prec(ts['symbol'],freeBal), ts['coinCurrency']),'warning')
            else:
                if price is None:
                    price = self.safeRun(lambda :self.exchange.fetch_ticker(ts['symbol'])['last'], iTs=iTs)
                try:
                    response = self.safeRun(lambda: self.exchange.createLimitSellOrder (ts['symbol'], ts['coinsAvail'],price*0.995),iTs=iTs)
                except InsufficientFunds:
                    freeBal = self.getFreeBalance(ts['coinCurrency'])
                    response = self.safeRun(lambda: self.exchange.createMarketSellOrder (ts['symbol'], freeBal),0)
                    self.message('When selling %s, only %s %s was found and sold!'%(ts['symbol'], self.amount2Prec(ts['symbol'],freeBal), ts['coinCurrency']),'warning')
            time.sleep(5) # give exchange 5 sec for trading the order
            orderInfo = self.fetchOrder(response['id'],iTs,'SELL')
                    
            if orderInfo['status']=='FILLED':
                if orderInfo['type'] == 'market' and self.exchange.has['fetchMyTrades'] != False:
                    trades = self.exchange.fetchMyTrades(ts['symbol'])
                    orderInfo['cost'] = sum([tr['cost'] for tr in trades if tr['order'] == orderInfo['id']])
                    orderInfo['price'] = np.mean([tr['price'] for tr in trades if tr['order'] == orderInfo['id']])
                ts['costOut'] += orderInfo['cost']
                self.message('Sold immediately at a price of %s %s: Sold %s %s for %s %s.'%(self.price2Prec(ts['symbol'],orderInfo['price']),ts['symbol'],self.amount2Prec(ts['symbol'],orderInfo['amount']),ts['coinCurrency'],self.cost2Prec(ts['symbol'],orderInfo['cost']),ts['baseCurrency']))
            else:
                self.message('Sell order was not traded immediately, updating status soon.')
                sold = False
                ts['OutTrades'].append({'oid':response['id'],'price': orderInfo['price'],'amount': orderInfo['amount']})
                self.activateTradeSet(iTs,0)
        else:
            self.message('No coins (or too low amount) to sell from this trade set.','warning')
        return sold
                
    def cancelSellOrders(self,iTs,oid=None,deleteOrders=False):
        self.updateDownState(True)
        returnVal = 1
        if iTs in self.tradeSets and self.numSellLevels(iTs) > 0:
            count = 0
            for iTrade,trade in reversed(list(enumerate(self.tradeSets[iTs]['OutTrades']))):
                if (oid is None or trade['oid']==oid):
                    if trade['oid'] is not None and trade['oid'] != 'filled':
                        try:
                            self.cancelOrder(trade['oid'],iTs,'SELL') 
                        except OrderNotFound as e:
                            pass
                        except Exception as e:
                            self.unlockTradeSet(iTs)
                            raise(e)
                        time.sleep(1)
                        count += 1
                        orderInfo = self.fetchOrder(trade['oid'],iTs,'SELL')
                        self.tradeSets[iTs]['coinsAvail'] += trade['amount']
                        if orderInfo['filled'] > 0:
                            self.message('(Partly?) filled sell order found during canceling. Updating balance')
                            self.tradeSets[iTs]['costOut'] += orderInfo['price']*orderInfo['filled']
                            self.tradeSets[iTs]['coinsAvail'] -= orderInfo['filled']  
                            trade['oid'] = 'filled'
                            trade['amount'] = orderInfo['filled']
                            returnVal = 0.5
                    if deleteOrders:
                        if trade['oid'] != 'filled':
                            self.tradeSets[iTs]['OutTrades'].pop(iTrade)
            if count > 0:
                self.message('%d sell orders canceled in total for tradeSet %d (%s)'%(count,list(self.tradeSets.keys()).index(iTs),self.tradeSets[iTs]['symbol']))
        return returnVal
        
    def cancelBuyOrders(self,iTs,oid=None,deleteOrders=False):
        self.updateDownState(True)
        returnVal = 1
        if iTs in self.tradeSets and self.numBuyLevels(iTs) > 0:
            count = 0
            for iTrade,trade in reversed(list(enumerate(self.tradeSets[iTs]['InTrades']))):
                if (oid is None or trade['oid']==oid):
                    if trade['oid'] is not None and trade['oid'] != 'filled':
                        try:
                            self.cancelOrder(trade['oid'],iTs,'BUY') 
                        except OrderNotFound as e:
                            pass
                            
                        time.sleep(1)
                        count += 1
                        orderInfo = self.fetchOrder(trade['oid'],iTs,'BUY')
                        if orderInfo['filled'] > 0:
                            self.message('(Partly?) filled buy order found during canceling. Updating balance')
                            self.tradeSets[iTs]['costIn'] += orderInfo['price']*orderInfo['filled']
                            self.tradeSets[iTs]['coinsAvail'] += orderInfo['filled']  
                            trade['oid'] = 'filled'
                            trade['amount'] = orderInfo['filled'] 
                            returnVal = 0.5
                    if deleteOrders:
                        if trade['oid'] != 'filled':
                            self.tradeSets[iTs]['InTrades'].pop(iTrade)
            if count > 0:
                self.message('%d buy orders canceled in total for tradeSet %d (%s)'%(count,list(self.tradeSets.keys()).index(iTs),self.tradeSets[iTs]['symbol']))
        return returnVal
    
    def initBuyOrders(self,iTs):
        self.updateDownState(True)
        if self.tradeSets[iTs]['active']:
            # initialize buy orders
            for iTrade,trade in enumerate(self.tradeSets[iTs]['InTrades']):
                if trade['oid'] is None and trade['candleAbove'] is None:
                    try:
                        response = self.safeRun(lambda: self.exchange.createLimitBuyOrder(self.tradeSets[iTs]['symbol'], trade['amount'],trade['price']))
                    except InsufficientFunds as e:
                        self.deactivateTradeSet(iTs)
                        self.message('Insufficient funds on exchange %s for trade set #%d. \
                                     Trade set is deactivated now and not updated anymore (open orders are still open)! \
                                     Free the missing funds and reactivate. \n %s.'
                                     %(self.exchange.name, list(self.tradeSets.keys()).index(iTs), str(e)),'error')
                        raise(e)
                    self.tradeSets[iTs]['InTrades'][iTrade]['oid'] = response['id']
    
    def cancelOrder(self,oid,iTs,typ):
        self.updateDownState(True)
        symbol = self.tradeSets[iTs]['symbol']
        try:
            return self.safeRun(lambda: self.exchange.cancelOrder (oid,symbol),0)
        except OrderNotFound as e:
            self.unlockTradeSet(iTs)
            raise(e)
        except ccxt.ExchangeError as e:
            return self.safeRun(lambda: self.exchange.cancelOrder (oid,symbol,{'type':typ}) , iTs=iTs)
        
    def fetchOrder(self,oid,iTs,typ):
        symbol = self.tradeSets[iTs]['symbol']
        try:
            return self.safeRun(lambda: self.exchange.fetchOrder (oid,symbol),0)
        except OrderNotFound as e:
            self.unlockTradeSet(iTs)
            raise(e)
        except ccxt.ExchangeError as e:
            return self.safeRun(lambda: self.exchange.fetchOrder (oid,symbol,{'type':typ}), iTs=iTs)  
        
    def updateDownState(self,raiseError = False):
        if self.down:
            self.safeRun(self.exchange.loadMarkets, printError = False)
            if raiseError:
                raise ccxt.ExchangeError('Exchange is down!')
            return self.down
        else:
            return False
        
    def update(self,specialCheck=0):
        # goes through all trade sets and checks/updates the buy/sell/stop loss orders
        # daily check is for checking if a candle closed above a certain value
        if not specialCheck:
            # fix for accumulating update jobs if update interval is set too small
            if (time.time()-self.lastUpdate) < 1:
                return None            
            
        if self.updateDownState():
            # check if exchange is still down, if yes, return
            return
        else: 
            try:
                self.updateBalance()
            except AuthenticationError as e:#
                self.message('Failed to authenticate at exchange %s. Please check your keys'%self.exchange.name,'error')
                return
            except ccxt.ExchangeError as e:#
                if 'key' in str(e).lower():
                    self.message('Failed to authenticate at exchange %s. Please check your keys'%self.exchange.name,'error')
                else:
                    self.down = True
                    self.message('Some error occured at exchange %s. Maybe it is down.'%self.exchange.name,'error')
                return
        
        tradeSetsToDelete = []
        try:
            if specialCheck != 2:
                if self.exchange.has['fetchTickers']:
                    tickers = self.safeRun(self.exchange.fetchTickers)
                    func = lambda sym, iTs: tickers[sym] if sym in tickers else self.safeRun(lambda : self.exchange.fetchTicker(sym), iTs=iTs)  # includes a hot fix for some ccxt problems
                else:
                    func = lambda sym, iTs: self.safeRun(lambda : self.exchange.fetchTicker(sym), iTs=iTs)
            
            for indTs, iTs in enumerate(self.tradeSets):
                try:
                    ts = self.tradeSets[iTs]
                    if not ts['active']:
                        continue
                    self.lockTradeSet(iTs)
                    if specialCheck != 2:
                        ticker = func(ts['symbol'], iTs=iTs)
                    # check if stop loss is reached
                    if not specialCheck:
                        if ts['SL'] is not None:
                            if ticker['last'] <= ts['SL']:
                                self.message('Stop loss for pair %s has been triggered!'%ts['symbol'],'warning')
                                # cancel all sell orders, create market sell order and save resulting amount of base currency
                                sold = self.sellAllNow(iTs,price=ticker['last'])
                                if sold:
                                    tradeSetsToDelete.append(iTs)
                                    self.unlockTradeSet(iTs)
                                    continue
                            elif 'trailingSL' in ts and ts['trailingSL'][0] is not None:
                                if ts['trailingSL'][1] == 'abs':
                                    newSL = ticker['last'] - ts['trailingSL'][0]
                                else:
                                    newSL = ticker['last'] * (1- ts['trailingSL'][0])
                                if newSL > ts['SL']:
                                    ts['SL'] = newSL
                    elif specialCheck == 1:
                        if 'dailycloseSL' in ts and ts['dailycloseSL'] is not None and ticker['last'] < ts['dailycloseSL']:
                            self.message('Daily candle closed below chosen SL of %s for pair %s! Selling now!'%(self.price2Prec(ts['symbol'],ts['dailycloseSL']),ts['symbol']),'warning')
                            # cancel all sell orders, create market sell order and save resulting amount of base currency
                            sold = self.sellAllNow(iTs,price=ticker['last'])
                            if sold:
                                tradeSetsToDelete.append(iTs)
                                self.unlockTradeSet(iTs)
                                continue
                        if datetime.date.today().weekday() == 0 and 'weeklycloseSL' in ts and ts['weeklycloseSL'] is not None and ticker['last'] < ts['weeklycloseSL']:
                            self.message('Weekly candle closed below chosen SL of %s for pair %s! Selling now!'%(self.price2Prec(ts['symbol'],ts['weeklycloseSL']),ts['symbol']),'warning')
                            # cancel all sell orders, create market sell order and save resulting amount of base currency
                            sold = self.sellAllNow(iTs,price=ticker['last'])
                            if sold:
                                tradeSetsToDelete.append(iTs)
                                self.unlockTradeSet(iTs)
                                continue
                    elif specialCheck == 2: # tax warning check
                        for iTrade,trade in enumerate(ts['InTrades']):
                            if 'time' in trade and (datetime.datetime.now() - trade['time']).days > 358 and (datetime.datetime.now() - trade['time']).days < 365:
                                self.message('Time since buy level #%d of trade set %d (%s) on exchange %s was filled approaches one year (%s) after which gains/losses are not eligible for reporting in the tax report in most countries!'%(iTrade,indTs,ts['symbol'],self.exchange.name,(trade['time']+datetime.timedelta(days=365)).strftime('%Y-%m-%d %H:%M')),'warning')
                        continue
                    orderExecuted = 0
                    # go through buy trades 
                    for iTrade,trade in enumerate(ts['InTrades']):
                        if trade['oid'] == 'filled':
                            continue
                        elif specialCheck == 1 and trade['oid'] is None and trade['candleAbove'] is not None:
                            if ticker['last'] > trade['candleAbove']:
                                response = self.safeRun(lambda: self.exchange.createLimitBuyOrder(ts['symbol'], trade['amount'],trade['price']), iTs=iTs)
                                ts['InTrades'][iTrade]['oid'] = response['id']
                                self.message('Daily candle of %s above %s triggering buy level #%d on %s!'%(ts['symbol'], self.price2Prec(ts['symbol'], trade['candleAbove']), iTrade, self.exchange.name))
                        elif trade['oid'] is not None:
                            try:
                                orderInfo = self.fetchOrder(trade['oid'],iTs,'BUY')
                                # fetch trades for all orders because a limit order might also be filled at a lower val
                                if orderInfo['status'].lower() in ['closed','filled','canceled'] and self.exchange.has['fetchMyTrades'] != False:
                                    trades = self.exchange.fetchMyTrades(ts['symbol'])
                                    orderInfo['cost'] = sum([tr['cost'] for tr in trades if tr['order'] == orderInfo['id']])
                                    if orderInfo['cost'] == 0:
                                        orderInfo['price'] = None
                                    else:
                                        orderInfo['price'] = np.mean([tr['price'] for tr in trades if tr['order'] == orderInfo['id']])
    
                                if orderInfo['status'].lower() in ['closed','filled']:
                                    orderExecuted = 1
                                    ts['InTrades'][iTrade]['oid'] = 'filled'
                                    ts['InTrades'][iTrade]['time'] = datetime.datetime.now()
                                    ts['InTrades'][iTrade]['price'] = orderInfo['price']
                                    ts['costIn'] += orderInfo['cost']
                                    self.message('Buy level of %s %s reached on %s! Bought %s %s for %s %s.'%(self.price2Prec(ts['symbol'],orderInfo['price']),ts['symbol'],self.exchange.name,self.amount2Prec(ts['symbol'],orderInfo['amount']),ts['coinCurrency'],self.cost2Prec(ts['symbol'],orderInfo['cost']),ts['baseCurrency']))
                                    ts['coinsAvail'] += trade['actualAmount']        
                                elif orderInfo['status'] == 'canceled':
                                    if 'reason' in orderInfo['info']:
                                        reason = orderInfo['info']['reason']
                                    else:
                                        reason = 'N/A'
                                    if orderInfo['cost'] > 0:
                                        ts['InTrades'][iTrade]['oid'] = 'filled'
                                        ts['InTrades'][iTrade]['price'] = orderInfo['price']
                                        ts['costIn'] += orderInfo['cost']  
                                        orderInfo['amount'] = sum([tr['amount'] for tr in trades if tr['order'] == orderInfo['id']])
                                        ts['coinsAvail'] += orderInfo['amount']
                                        self.message('Buy order (level %d of trade set %d on %s) was canceled by exchange or someone else (reason: %s) but already partly filled! Treating order as closed now and updating trade set info.'%(iTrade,list(self.tradeSets.keys()).index(iTs),self.exchange.name), 'error')
                                    else:
                                        ts['InTrades'][iTrade]['oid'] = None
                                        self.message('Buy order (level %d of trade set %d on %s) was canceled by exchange or someone else (reason:%s)! Will be reinitialized during next update.'%(iTrade,list(self.tradeSets.keys()).index(iTs),self.exchange.name,reason), 'error')
                                           
                            except OrderNotFound as e:
                                self.lockTradeSet(iTs)
                                self.message('Buy order id %s for trade set %s not found on %s! Maybe exchange API has changed? Resetting order to "not initiated", will be initiated on next trade set update!'%(str(ts['InTrades'][iTrade]['oid']), ts['symbol'], self.exchange.name), 'error')
                                ts['InTrades'][iTrade]['oid'] = None
    
                        else:
                            self.initBuyOrders(iTs)                                
                            time.sleep(1)
                    
                    if not specialCheck:
                        # go through all selling positions and create those for which the bought coins suffice
                        for iTrade,_ in enumerate(ts['OutTrades']):
                            if ts['OutTrades'][iTrade]['oid'] is None and ts['coinsAvail'] >= ts['OutTrades'][iTrade]['amount']:
                                try:
                                    response = self.safeRun(lambda: self.exchange.createLimitSellOrder(ts['symbol'], ts['OutTrades'][iTrade]['amount'], ts['OutTrades'][iTrade]['price']), iTs=iTs)
                                except InsufficientFunds as e:
                                    self.deactivateTradeSet(iTs)
                                    self.message('Insufficient funds on exchange %s for trade set #%d. \
                                                 Trade set is deactivated now and not updated anymore (open orders are still open)! \
                                                 Free the missing funds and reactivate. \n %s.'
                                                 %(self.exchange.name, list(self.tradeSets.keys()).index(iTs), str(e)),'error')

                                    raise(e)
                                ts['OutTrades'][iTrade]['oid'] = response['id']
                                ts['coinsAvail'] -= ts['OutTrades'][iTrade]['amount']
                        # go through sell trades 
                        for iTrade,trade in enumerate(ts['OutTrades']):
                            if trade['oid'] == 'filled':
                                continue
                            elif trade['oid'] is not None:
                                try:
                                    orderInfo = self.fetchOrder(trade['oid'],iTs,'SELL')
                                    # fetch trades for all orders because a limit order might also be filled at a higher val
                                    if self.exchange.has['fetchMyTrades'] != False:
                                        trades = self.exchange.fetchMyTrades(ts['symbol'])
                                        orderInfo['cost'] = sum([tr['cost'] for tr in trades if tr['order'] == orderInfo['id']])
                                        if orderInfo['cost'] == 0:
                                            orderInfo['price'] = None
                                        else:
                                            orderInfo['price'] = np.mean([tr['price'] for tr in trades if tr['order'] == orderInfo['id']])
                                    
                                    if any([orderInfo['status'].lower() == val for val in ['closed','filled']]):
                                        orderExecuted = 2
                                        ts['OutTrades'][iTrade]['oid'] = 'filled'  
                                        ts['OutTrades'][iTrade]['time'] = datetime.datetime.now()
                                        ts['OutTrades'][iTrade]['price'] = orderInfo['price']
                                        ts['costOut'] += orderInfo['cost']
                                        self.message('Sell level of %s %s reached on %s! Sold %s %s for %s %s.'%(self.price2Prec(ts['symbol'],orderInfo['price']),ts['symbol'],self.exchange.name,self.amount2Prec(ts['symbol'],orderInfo['amount']),ts['coinCurrency'],self.cost2Prec(ts['symbol'],orderInfo['cost']),ts['baseCurrency']))   
                                    elif orderInfo['status'] == 'canceled':
                                        if 'reason' in orderInfo['info']:
                                            reason = orderInfo['info']['reason']
                                        else:
                                            reason = 'N/A'
                                        if orderInfo['cost'] > 0:
                                            ts['OutTrades'][iTrade]['oid'] = 'filled'
                                            ts['OutTrades'][iTrade]['price'] = orderInfo['price']
                                            ts['costOut'] += orderInfo['cost']    
                                            orderInfo['amount'] = sum([tr['amount'] for tr in trades if tr['order'] == orderInfo['id']])
                                            ts['coinsAvail'] +=  ts['OutTrades'][iTrade]['amount']-orderInfo['amount']
                                            self.message('Sell order (level %d of trade set %d on %s) was canceled by exchange or someone else (reason: %s) but already partly filled! Treating order as closed now and updating trade set info.'%(iTrade,list(self.tradeSets.keys()).index(iTs),self.exchange.name))
                                        else:
                                            ts['OutTrades'][iTrade]['oid'] = None
                                            ts['coinsAvail'] += ts['OutTrades'][iTrade]['amount']
                                            self.message('Sell order (level %d of trade set %d on %s) was canceled by exchange or someone else (reason:%s)! Will be reinitialized during next update.'%(iTrade,list(self.tradeSets.keys()).index(iTs),self.exchange.name,reason))
                                        
                                except OrderNotFound as e:
                                    self.lockTradeSet(iTs)
                                    self.message('Sell order id %s for trade set %s not found on %s! Maybe exchange API has changed? Resetting order to "not initiated"! If InsufficientFunds errors pop up, the order had probably been executed. In this case please delete the trade set.'%(str(ts['OutTrades'][iTrade]['oid']), ts['symbol'], self.exchange.name),'error')
                                    ts['coinsAvail'] +=  ts['OutTrades'][iTrade]['amount']
                                    ts['OutTrades'][iTrade]['oid'] = None
                            
                        # delete Tradeset when all orders have been filled (but only if there were any to execute and if no significant coin amount is left)
                        if ((ts['SL'] is None and orderExecuted > 0) or (orderExecuted == 2 and (self.sumBuyAmounts(iTs,order='filled')+ts['initCoins']-self.sumSellAmounts(iTs,order='filled'))/(ts['initCoins']+self.sumBuyAmounts(iTs,order='filled')) < 0.01 )) and self.numSellLevels(iTs,'notfilled') == 0 and self.numBuyLevels(iTs,'notfilled') == 0:
                            gain = self.cost2Prec(ts['symbol'],ts['costOut']-ts['costIn'])
                            self.message('Trading set %s on %s completed! Total gain: %s %s'%(ts['symbol'],self.exchange.name,gain,ts['baseCurrency']))
                            tradeSetsToDelete.append(iTs)
                finally:
                    self.unlockTradeSet(iTs)
        finally:  
            # makes sure that the tradeSet deletion takes place even if some error occurred in another trade
            for iTs in tradeSetsToDelete:
                self.createTradeHistoryEntry(iTs)
                self.tradeSets.pop(iTs) 
            self.lastUpdate = time.time()
    