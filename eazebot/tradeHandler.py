#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# EazeBot
# Free python/telegram bot for easy execution and surveillance of crypto trading plans on multiple exchanges.
# Copyright (C) 2018
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
import numpy as np
import time
import random
import string
import sys, os
from ccxt.base.errors import (NetworkError,OrderNotFound)

# might be usable in future release to calculate fees:
# self.exchange.calculateFee('KCS/BTC','limit','buy',amount,price,'taker')

class tradeHandler:
    
    def __init__(self,exchName,key,secret,password=None,uid=None,messagerFct=None):
        checkThese = ['cancelOrder','createLimitOrder','fetchBalance','fetchTicker']
        self.tradeSets = {}
        self.exchange = getattr (ccxt, exchName) ({'enableRateLimit': True,'options': { 'adjustForTimeDifference': True }}) # 'nonce': ccxt.Exchange.milliseconds,
        if key:
            self.exchange.apiKey = key
        else:
            raise TypeError('key argument not given to class')
        if secret:
            self.exchange.secret = secret
        else:
            raise TypeError('key argument not given to class')
        if password:
            self.exchange.password = password
        if uid:
            self.exchange.uid = uid
        self.safeRun(self.exchange.loadMarkets)
        self.amount2Prec = lambda a,b: self.stripZeros(str(self.exchange.amountToPrecision(a,b)))
        self.price2Prec = lambda a,b: self.stripZeros(str(self.exchange.priceToPrecision(a,b)))
        self.cost2Prec = lambda a,b: self.stripZeros(str(self.exchange.costToPrecision(a,b)))
        self.fee2Prec = lambda a,b: self.stripZeros(str(self.exchange.feeToPrecision(a,b)))

        # use either the given messager function or define a simple print messager function which takes a level argument as second optional input
        if messagerFct:
            self.message = messagerFct
        else:
            self.message = lambda a,b='Info': print(b + ': ' + a)
            
        if not all([self.exchange.has[x] for x in checkThese]):
            text = 'Exchange %s does not support all required features (%s)'%(exchName,', '.join(checkThese))
            self.message(text,'error')
            raise Exception(text)
        self.updating = False
        self.authenticated = False
        try:
            # check if keys work
            self.balance = self.safeRun(self.exchange.fetch_balance,0)
            self.authenticated = True
        except getattr(ccxt,'AuthenticationError') as e:#
            self.message('Failed to authenticate at exchange %s. Please check your keys'%exchName,'error')
        except getattr(ccxt,'ExchangeError') as e:#
            if 'key' in str(e).lower():
                self.message('Failed to authenticate at exchange %s. Please check your keys'%exchName,'error')
            else:
                self.message('An error occured during checking authentication:\n%s'%str(e),'error')
          
    def __reduce__(self):
        # function needes for serializing the object
        return (self.__class__, (self.exchange.__class__.__name__,self.exchange.apiKey,self.exchange.secret,self.exchange.password,self.exchange.uid,self.message),self.__getstate__(),None,None)
    
    def __setstate__(self,state):
        if isinstance(state,list):  # temp fix for old class
            tmpstate = {}
            for trade in state:
                tmpstate[trade['uid']] = trade
            self.tradeSets = tmpstate
        else:
            self.tradeSets = state
        
    def __getstate__(self):
        return self.tradeSets
    
    @staticmethod
    def stripZeros(string):
        if '.' in string:
            return string.rstrip('0').rstrip('.')
        else:
            return string
        
    def checkNum(self,*value):
        return all([(isinstance(val,float) | isinstance(val,int)) if not isinstance(val,list) else self.checkNum(*val) for val in value])
    
     
    def safeRun(self,func,printError=True):
        count = 0
        while True:
            try:
                return func()
            except NetworkError as e:
                count += 1
                if count >= 5:
                    self.updating = False
                    print('Network exception occurred 5 times in a row')             
                    raise(e)
                else:
                    time.sleep(0.5)
                    continue
            except OrderNotFound as e:
                count += 1
                if count >= 5:
                    self.updating = False
                    print('Order not found 5 times in a row')             
                    raise(e)
                else:
                    time.sleep(0.5)
                    continue
            except Exception as e:
                if count < 4 and ('unknown error' in str(e).lower() or 'connection' in str(e).lower()):
                    count += 1
                    time.sleep(0.5)
                    continue
                else:
                    self.updating = False
                    if count >= 5:
                        print('Network exception occurred 5 times in a row')             
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    if printError:
                        self.message('%s in %s at line %s: %s'%(exc_type, fname, exc_tb.tb_lineno,str(e)),'Error')
                    raise(e)
        

    def waitForUpdate(self):
        count = 0
        while self.updating:
            count += 1
            time.sleep(1)		
            if count > 60: # 60 sec max wait
                self.message('Waiting for tradeSet update to finish timed out after 1 min, resetting updating variable','error')
                break
        self.updating = True
        
    def updateBalance(self):
        self.balance = self.safeRun(self.exchange.fetch_balance)
        
    def getFreeBalance(self,coin):
        if coin in self.balance:
            return self.balance[coin]['free']
        else:
            return 0

    def updateKeys(self,key,secret,password=None,uid=None):
        if key:
            self.exchange.apiKey = key
        else:
            raise TypeError('key argument not given to class')
        if secret:
            self.exchange.secret = secret
        else:
            raise TypeError('key argument not given to class')
        if password:
            self.exchange.password = password
        if uid:
            self.exchange.uid = uid
        self.safeRun(self.exchange.loadMarkets) 
        try:
            # check if keys work
            self.safeRun(self.updateBalance,0)
            self.authenticated = True
        except getattr(ccxt,'AuthenticationError') as e:#
            self.authenticated = False
            self.message('Failed to authenticate at exchange %s. Please check your keys'%self.exchange.name,'error')
        except getattr(ccxt,'ExchangeError') as e:
            self.authenticated = False
            self.message('Failed to fetch balance at exchange %s. The following error occurred:\n%s'%(self.exchange.name,str(e)),'error')
          
    
    def initTradeSet(self,symbol):
        ts = {}
        ts['symbol'] = symbol
        ts['InTrades'] = []
        iTs = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
        # redo if uid already reserved
        while iTs in self.tradeSets:
            iTs = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
        ts['OutTrades'] = []
        ts['baseCurrency'] = re.search("(?<=/).*", symbol).group(0)
        ts['coinCurrency'] = re.search(".*(?=/)", symbol).group(0)
        ts['costIn'] = 0
        ts['costOut'] = 0
        ts['coinsAvail'] = 0
        ts['initCoins'] = 0
        ts['initPrice'] = None
        ts['SL'] = None
        ts['active'] = False
        ts['virgin'] = True
        self.waitForUpdate()
        self.tradeSets[iTs] = ts
        self.updating = False
        return ts, iTs
        
    def activateTradeSet(self,iTs,verbose=True):
        ts = self.tradeSets[iTs]
        wasactive = ts['active']
        self.tradeSets[iTs]['virgin'] = False
        self.tradeSets[iTs]['active'] = True
        
        if verbose and not wasactive:
            totalBuyCost = ts['costIn'] + self.sumBuyCosts(iTs)
            self.message('Estimated return if all trades are executed: %s %s'%(self.cost2Prec(ts['symbol'],self.sumSellCosts(iTs)-totalBuyCost),ts['baseCurrency']))
            if ts['SL'] is not None:
                loss = totalBuyCost-(ts['initCoins']+self.sumBuyAmounts(iTs))*ts['SL']
                self.message('Estimated loss if buys reach stop-loss before selling: %s %s %s'%(self.cost2Prec(ts['symbol'],loss),'*(negative = gain!)*'if loss<0 else '',ts['baseCurrency']))        
        self.initBuyOrders(iTs)
        self.update()
        return wasactive
    
    def deactivateTradeSet(self,iTs,cancelOrders=False):
        wasactive = self.tradeSets[iTs]['active']
        if cancelOrders:
            self.cancelBuyOrders(iTs)
            self.cancelSellOrders(iTs)
        self.tradeSets[iTs]['active'] = False
        return wasactive
        
    def newTradeSet(self,symbol,buyLevels=[],buyAmounts=[],sellLevels=[],sellAmounts=[],sl=None,candleAbove=[],initCoins=0,initPrice=None,force=False):
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
            raise ValueError('Warning: It seems the buy and sell amount of %s is not the same. Is this correct?'%ts['coinCurrency'])
        if buyLevels.size > 0 and sellLevels.size > 0 and max(buyLevels) > min(sellLevels):
            raise ValueError('It seems at least one of your sell prices is lower than one of your buy, which does not make sense')
        self.updateBalance()
        if self.balance[ts['baseCurrency']]['free'] < sum(buyLevels*buyAmounts):
            raise ValueError('Free balance of %s not sufficient to initiate trade set'%ts['baseCurrency'])
        
        # create the buy orders
        for n,_ in enumerate(buyLevels):
            self.addBuyLevel(iTs,buyLevels[n],buyAmounts[n],candleAbove[n])
        
        self.addInitCoins(iTs,initCoins,initPrice)
        self.setSL(iTs,sl)
        # create the sell orders
        for n,_ in enumerate(sellLevels):
            self.addSellLevel(iTs,sellLevels[n],sellAmounts[n])

        self.activateTradeSet(iTs)
        self.update()
        return iTs
        
    def getTradeSetInfo(self,iTs,showProfitIn=None):
        ts = self.tradeSets[iTs]
        string = '*%srade set #%d on %s [%s]:*\n'%('T' if ts['active'] else 'INACTIVE t',list(self.tradeSets.keys()).index(iTs),self.exchange.name,ts['symbol'])
        filledBuys = []
        filledSells = []
        for iTrade,trade in enumerate(ts['InTrades']):
            tmpstr = '*Buy level %d:* Price %s , Amount %s %s   '%(iTrade,self.price2Prec(ts['symbol'],trade['price']),self.amount2Prec(ts['symbol'],trade['amount']),ts['coinCurrency'])
            if trade['oid'] is None:
                if trade['candleAbove'] is None:
                    tmpstr = tmpstr + '_Order not initiated_\n'
                else:
                    tmpstr = tmpstr + 'if DC > %s'%self.price2Prec(ts['symbol'],trade['candleAbove'])
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                filledBuys.append([trade['amount'],trade['price']])
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
            string += '\n*Stop-loss* set at %s\n\n'%self.price2Prec(ts['symbol'],ts['SL'])
        else:
            string += '\n*No stop-loss set.*\n\n'
        sumBuys = sum([val[0] for val in filledBuys])
        sumSells = sum([val[0] for val in filledSells])
        if ts['initCoins']>0:
            string += '*Initial coins:* %s %s for an average price of %s\n'%(self.amount2Prec(ts['symbol'],ts['initCoins']),ts['coinCurrency'],self.price2Prec(ts['symbol'],ts['initPrice']) if ts['initPrice'] is not None else 'unknown')
        if sumBuys>0:
            string += '*Filled buy orders:* %s %s for an average price of %s\n'%(self.amount2Prec(ts['symbol'],sumBuys),ts['coinCurrency'],self.cost2Prec(ts['symbol'],sum([val[0]*val[1]/sumBuys if sumBuys > 0 else None for val in filledBuys])))
        if sumSells>0:
            string += '*Filled sell orders:* %s %s for an average price of %s\n'%(self.amount2Prec(ts['symbol'],sumSells),ts['coinCurrency'],self.cost2Prec(ts['symbol'],sum([val[0]*val[1]/sumSells if sumSells > 0 else None for val in filledSells])))
        ticker = self.safeRun(lambda: self.exchange.fetchTicker(ts['symbol']))
        string += '\n*Current market price *: %s, \t24h-high: %s, \t24h-low: %s\n'%tuple([self.price2Prec(ts['symbol'],val) for val in [ticker['last'],ticker['high'],ticker['low']]])
        if (ts['initCoins'] == 0 or ts['initPrice'] is not None) and (sumBuys>0 or ts['initCoins'] > 0):
            costSells = ts['costOut'] + (ts['coinsAvail']+sum([trade['amount'] for trade in ts['OutTrades'] if trade['oid'] != 'filled' and trade['oid'] is not None]))*ticker['last'] 
            gain = costSells - ts['costIn']
            gainOrig = gain
            thisCur = ts['baseCurrency']
            if showProfitIn is not None:
                if isinstance(showProfitIn,str):
                    showProfitIn = [showProfitIn]
                conversionPairs = [('%s/%s'%(ts['baseCurrency'],cur) in self.exchange.symbols) + 2*('%s/%s'%(cur,ts['baseCurrency']) in self.exchange.symbols) for cur in showProfitIn]
                ind = next((i for i, x in enumerate(conversionPairs) if x), None)
                if ind is not None:
                    thisCur = showProfitIn[ind]
                    if conversionPairs[ind] == 1:
                        gain *= self.safeRun(lambda: self.exchange.fetchTicker('%s/%s'%(ts['baseCurrency'],thisCur)))['last']
                    else:
                        gain /= self.safeRun(lambda: self.exchange.fetchTicker('%s/%s'%(thisCur,ts['baseCurrency'])))['last']
                    
            string += '\n*Estimated gain/loss when selling all now: * %s %s (%+.2f %%)\n'%(self.cost2Prec(ts['symbol'],gain),thisCur,gainOrig/(ts['costIn'])*100)
        return string
    
    def deleteTradeSet(self,iTs,sellAll=False):
        self.waitForUpdate()
        if sellAll:
            self.sellAllNow(iTs)
        else:
            self.deactivateTradeSet(iTs,1)
        self.tradeSets.pop(iTs)
        self.updating = False
    
    def addInitCoins(self,iTs,initCoins=0,initPrice=None):
        if self.checkNum(initCoins,initPrice) or (initPrice is None and self.checkNum(initCoins)):
            self.waitForUpdate()
            ts = self.tradeSets[iTs]
            if ts['coinsAvail'] > 0 and ts['initPrice'] is not None:
                # remove old cost again
                ts['costIn'] -= (ts['coinsAvail']*ts['initPrice'])
            ts['coinsAvail'] = initCoins
            ts['initCoins'] = initCoins
            if initPrice is not None and initPrice < 0:
                initPrice = None
            ts['initPrice'] = initPrice
            if initPrice is not None:
                ts['costIn'] += (initCoins*initPrice)
            self.updating = False
        else:
            raise ValueError('Some input was no number')
            
    def numBuyLevels(self,iTs):
        return len(self.tradeSets[iTs]['InTrades'])

    def sumBuyAmounts(self,iTs):
        return sum([val['amount'] for val in self.tradeSets[iTs]['InTrades']])

    def sumBuyCosts(self,iTs):
        return sum([val['amount']*val['price'] for val in self.tradeSets[iTs]['InTrades']])
    
    def numSellLevels(self,iTs):
        return len(self.tradeSets[iTs]['OutTrades'])
    
    def sumSellAmounts(self,iTs):
        return sum([val['amount'] for val in self.tradeSets[iTs]['OutTrades']])

    def sumSellCosts(self,iTs):
        return sum([val['amount']*val['price'] for val in self.tradeSets[iTs]['OutTrades']])
    
    def addBuyLevel(self,iTs,buyPrice,buyAmount,candleAbove=None):
        
        if self.checkNum(buyPrice,buyAmount,candleAbove) or (candleAbove is None and self.checkNum(buyPrice,buyAmount)):
            self.waitForUpdate()
            wasactive = self.deactivateTradeSet(iTs)  
            self.tradeSets[iTs]['InTrades'].append({'oid': None, 'price': buyPrice, 'amount': buyAmount, 'candleAbove': candleAbove})
            if wasactive:
                self.activateTradeSet(iTs,0)   
            self.updating = False
            return  self.numBuyLevels(iTs)-1
        else:
            raise ValueError('Some input was no number')
    
    def deleteBuyLevel(self,iTs,iTrade): 
        
        if self.checkNum(iTrade):
            self.waitForUpdate()
            ts = self.tradeSets[iTs]
            wasactive = self.deactivateTradeSet(iTs)
            if ts['InTrades'][iTrade]['oid'] is not None and ts['InTrades'][iTrade]['oid'] != 'filled' :
                self.cancelOrder(ts['InTrades'][iTrade]['oid'],ts['symbol'],'BUY')
            ts['InTrades'].pop(iTrade)
            if wasactive:
                self.activateTradeSet(iTs,0) 
            self.updating = False
        else:
            raise ValueError('Some input was no number')
            
    def setBuyLevel(self,iTs,iTrade,price,amount):   
        if self.checkNum(iTrade,price,amount):
            ts = self.tradeSets[iTs]
            if ts['InTrades'][iTrade]['oid'] == 'filled':
                self.message('This order is already filled! No change possible')
                return 0
            else:
                wasactive = self.deactivateTradeSet(iTs)  
                
                if ts['InTrades'][iTrade]['oid'] is not None and ts['InTrades'][iTrade]['oid'] != 'filled' :
                    self.cancelOrder(ts['InTrades'][iTrade]['oid'],ts['symbol'],'BUY')
                ts['InTrades'][iTrade]['amount'] = amount
                ts['InTrades'][iTrade]['price'] = price
                
                if wasactive:
                    self.activateTradeSet(iTs,0)                
                return 1
        else:
            raise ValueError('Some input was no number')
    
    def addSellLevel(self,iTs,sellPrice,sellAmount):
        
        if self.checkNum(sellPrice,sellAmount):
            self.waitForUpdate()
            wasactive = self.deactivateTradeSet(iTs)  
            self.tradeSets[iTs]['OutTrades'].append({'oid': None, 'price': sellPrice, 'amount': sellAmount})
            if wasactive:
                self.activateTradeSet(iTs,0)  
            self.updating = False
            return  self.numSellLevels(iTs)-1
        else:
            raise ValueError('Some input was no number')

    def deleteSellLevel(self,iTs,iTrade):   
        
        if self.checkNum(iTrade):
            self.waitForUpdate()
            ts = self.tradeSets[iTs]
            wasactive = self.deactivateTradeSet(iTs)
            if ts['OutTrades'][iTrade]['oid'] is not None and ts['OutTrades'][iTrade]['oid'] != 'filled' :
                self.cancelOrder(ts['OutTrades'][iTrade]['oid'],ts['symbol'],'SELL')
                ts['coinsAvail'] += ts['OutTrades'][iTrade]['amount']
            ts['OutTrades'].pop(iTrade)
            self.updating = False
            if wasactive:
                self.activateTradeSet(iTs,0) 
        else:
            raise ValueError('Some input was no number')
    
    def setSellLevel(self,iTs,iTrade,price,amount):   
        if self.checkNum(iTrade,price,amount):
            ts = self.tradeSets[iTs]
            if ts['OutTrades'][iTrade]['oid'] == 'filled':
                self.message('This order is already filled! No change possible')
                return 0
            else:
                wasactive = self.deactivateTradeSet(iTs)  
                
                if ts['OutTrades'][iTrade]['oid'] is not None and ts['OutTrades'][iTrade]['oid'] != 'filled' :
                    self.cancelOrder(ts['OutTrades'][iTrade]['oid'],ts['symbol'],'SELL')
                ts['OutTrades'][iTrade]['amount'] = amount
                ts['OutTrades'][iTrade]['price'] = price
                
                if wasactive:
                    self.activateTradeSet(iTs,0)                
                return 1
        else:
            raise ValueError('Some input was no number')
            
            
    def setSL(self,iTs,value):   
        if self.checkNum(value) or value is None:
            self.tradeSets[iTs]['SL'] = value
        else:
            raise ValueError('Input was no number')
        
    def setSLBreakEven(self,iTs):   
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
            breakEvenPrice = (ts['costIn']-ts['costOut'])/(ts['coinsAvail']+sum([trade['amount'] for trade in ts['OutTrades'] if trade['oid'] != 'filled' and trade['oid'] is not None]))
            ticker = self.safeRun(lambda :self.exchange.fetch_ticker(ts['symbol']))
            if ticker['last'] < breakEvenPrice:
                self.message('Break even SL of %s cannot be set as the current market price is lower (%s)!'%tuple([self.price2Prec(ts['symbol'],val) for val in [breakEvenPrice,ticker['last']]]))
                return 0
            else:
                ts['SL'] = breakEvenPrice
                return 1

    def sellAllNow(self,iTs,price=None):
        self.deactivateTradeSet(iTs,1)
        ts = self.tradeSets[iTs]
        ts['InTrades'] = []
        ts['OutTrades'] = []
        ts['SL'] = None # necessary to not retrigger SL
        if ts['coinsAvail'] > 0:
            if self.exchange.has['createMarketOrder']:
                try:
                    response = self.safeRun(lambda: self.exchange.createMarketSellOrder (ts['symbol'], ts['coinsAvail']),0)
                except:
                    params = { 'trading_agreement': 'agree' }  # for kraken api...
                    response = self.safeRun(lambda: self.exchange.createMarketSellOrder (ts['symbol'], ts['coinsAvail'],params))
            else:
                if price is None:
                    price = self.safeRun(lambda :self.exchange.fetch_ticker(ts['symbol'])['last'])
                response = self.safeRun(lambda: self.exchange.createLimitSellOrder (ts['symbol'], ts['coinsAvail'],price))
            time.sleep(3) # give exchange 3 sec for trading the order
            try:
                orderInfo = self.safeRun(lambda: self.exchange.fetchOrder (response['id'],ts['symbol']),0)
            except ccxt.ExchangeError as e:
                orderInfo = self.safeRun(lambda: self.exchange.fetchOrder (response['id'],ts['symbol'],{'type':'SELL'}))
                    
            if orderInfo['status']=='FILLED':
                ts['costOut'] += orderInfo['cost']
                self.message('Sold immediately at a price of %s %s: Sold %s %s for %s %s.'%(self.price2Prec(ts['symbol'],orderInfo['price']),ts['symbol'],self.amount2Prec(ts['symbol'],orderInfo['amount']),ts['coinCurrency'],self.cost2Prec(ts['symbol'],orderInfo['cost']),ts['baseCurrency']))
                self.deleteTradeSet(iTs)
            else:
                self.message('Sell order was not traded immediately, updating status soon.')
                ts['OutTrades'].append({'oid':response['id'],'price': orderInfo['price'],'amount': orderInfo['amount']})
                self.activateTradeSet(iTs,0)
        else:
            self.message('No coins to sell from this trade set.')
                
    def cancelSellOrders(self,iTs):
        if iTs in self.tradeSets and self.numSellLevels(iTs) > 0:
            count = 0
            for iTrade,trade in reversed(list(enumerate(self.tradeSets[iTs]['OutTrades']))):
                if trade['oid'] is not None and trade['oid'] != 'filled':
                    self.cancelOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'SELL') 
                    time.sleep(1)
                    count += 1
                    orderInfo = self.fetchOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'SELL')
                    if orderInfo['filled'] > 0:
                        self.message('Partly filled sell order found during canceling. Updating balance')
                        self.tradeSets[iTs]['costOut'] += orderInfo['price']*orderInfo['filled']
                        self.tradeSets[iTs]['coinsAvail'] -= orderInfo['filled']                                
                    self.tradeSets[iTs]['coinsAvail'] += trade['amount']
            if count > 0:
                self.message('%d sell orders canceled in total for tradeSet %d (%s)'%(count,list(self.tradeSets.keys()).index(iTs),self.tradeSets[iTs]['symbol']))
        return True
        
    def cancelBuyOrders(self,iTs):
        if iTs in self.tradeSets and self.numBuyLevels(iTs) > 0:
            count = 0
            for iTrade,trade in reversed(list(enumerate(self.tradeSets[iTs]['InTrades']))):
                if trade['oid'] is not None and trade['oid'] != 'filled':
                    self.cancelOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'BUY') 
                    time.sleep(1)
                    count += 1
                    orderInfo = self.fetchOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'BUY')
                    if orderInfo['filled'] > 0:
                        self.message('Partly filled buy order found during canceling. Updating balance')
                        self.tradeSets[iTs]['costIn'] += orderInfo['price']*orderInfo['filled']
                        self.tradeSets[iTs]['coinsAvail'] += orderInfo['filled']   
            if count > 0:
                self.message('%d buy orders canceled in total for tradeSet %d (%s)'%(count,list(self.tradeSets.keys()).index(iTs),self.tradeSets[iTs]['symbol']))
        return True
    
    def initBuyOrders(self,iTs):
        if self.tradeSets[iTs]['active']:
            # initialize buy orders
            for iTrade,trade in enumerate(self.tradeSets[iTs]['InTrades']):
                if trade['oid'] is None and trade['candleAbove'] is None:
                    response = self.safeRun(lambda: self.exchange.createLimitBuyOrder(self.tradeSets[iTs]['symbol'], trade['amount'],trade['price']))
                    self.tradeSets[iTs]['InTrades'][iTrade]['oid'] = response['id']
    
    def cancelOrder(self,oid,symbol,typ):
        try:
            return self.safeRun(lambda: self.exchange.cancelOrder (oid,symbol),0)
        except ccxt.ExchangeError as e:
            return self.safeRun(lambda: self.exchange.cancelOrder (oid,symbol,{'type':typ}) )
        
    def fetchOrder(self,oid,symbol,typ):
        try:
            return self.safeRun(lambda: self.exchange.fetchOrder (oid,symbol),0)
        except ccxt.ExchangeError as e:
            return self.safeRun(lambda: self.exchange.fetchOrder (oid,symbol,{'type':typ}))  
                                    
    def update(self,dailyCheck=0):
        # goes through all trade sets and checks/updates the buy/sell/stop loss orders
        # daily check is for checking if a candle closed above a certain value
        self.waitForUpdate()
        tradeSetsToDelete = []
        for iTs in self.tradeSets:
            ts = self.tradeSets[iTs]
            if not ts['active']:
#                        self.message('Trade set %d on exchange %s skipped during update'%(iTs,self.exchange.name))
                continue
            # check if stop loss is reached
            if not dailyCheck and ts['SL'] is not None:
                ticker = self.safeRun(lambda: self.exchange.fetch_ticker(ts['symbol']))
                if ticker['last'] <= ts['SL']:
                    self.message('Stop loss for pair %s has been triggered!'%ts['symbol'],'warning')
                    # cancel all sell orders, create market sell order and save resulting amount of base currency
                    self.sellAllNow(iTs,price=ticker['last'])
            filledIn = 0
            filledOut = 0
            # go through buy trades 
            for iTrade,trade in enumerate(ts['InTrades']):
                if trade['oid'] == 'filled':
                    filledIn += 1
                    continue
                elif dailyCheck and trade['oid'] is None and trade['candleAbove'] is not None:
                    ticker = self.safeRun(lambda: self.exchange.fetch_ticker(ts['symbol']))
                    if ticker['last'] > trade['candleAbove']:
                        response = self.safeRun(lambda: self.exchange.createLimitBuyOrder(ts['symbol'], trade['amount'],trade['price']))
                        ts['InTrades'][iTrade]['oid'] = response['id']
                        self.message('Daily candle of %s above %s triggering buy level #%d on %s!'%(ts['symbol'],self.price2Prec(ts['symbol'],trade['candleAbove']),iTrade,self.exchange.name))
                elif trade['oid'] is not None:
                    orderInfo = self.fetchOrder(trade['oid'],ts['symbol'],'BUY')
                    if any([orderInfo['status'].lower() == val for val in ['closed','filled']]):
                        ts['InTrades'][iTrade]['oid'] = 'filled'
                        ts['costIn'] += orderInfo['cost']
                        self.message('Buy level of %s %s reached on %s! Bought %s %s for %s %s.'%(self.price2Prec(ts['symbol'],orderInfo['price']),ts['symbol'],self.exchange.name,self.amount2Prec(ts['symbol'],orderInfo['amount']),ts['coinCurrency'],self.cost2Prec(ts['symbol'],orderInfo['cost']),ts['baseCurrency']))
                        ts['coinsAvail'] += orderInfo['filled']
                        filledIn += 1
                    elif orderInfo['status'] == 'canceled':
                        ts['InTrades'][iTrade]['oid'] = None
                        self.message('Buy order (level %d of trade set %d on %s) was canceled manually by someone! Will be reinitialized during next update.'%(iTrade,list(self.tradeSets.keys()).index(iTs),self.exchange.name))
                else:
                    self.initBuyOrders(iTs)                                
                    time.sleep(1)
                        
            if not dailyCheck:
                # go through all selling positions and create those for which the bought coins suffice
                for iTrade,_ in enumerate(ts['OutTrades']):
                    if ts['OutTrades'][iTrade]['oid'] is None and ts['coinsAvail'] >= ts['OutTrades'][iTrade]['amount']:
                        response = self.safeRun(lambda: self.exchange.createLimitSellOrder(ts['symbol'], ts['OutTrades'][iTrade]['amount'], ts['OutTrades'][iTrade]['price']))
                        ts['OutTrades'][iTrade]['oid'] = response['id']
                        ts['coinsAvail'] -= ts['OutTrades'][iTrade]['amount']
    
                # go through sell trades 
                for iTrade,trade in enumerate(ts['OutTrades']):
                    if trade['oid'] == 'filled':
                        filledOut += 1
                        continue
                    elif trade['oid'] is not None:
                        orderInfo = self.fetchOrder(trade['oid'],ts['symbol'],'SELL')
                        if any([orderInfo['status'].lower() == val for val in ['closed','filled']]):
                            ts['OutTrades'][iTrade]['oid'] = 'filled'
                            ts['costOut'] += orderInfo['cost']
                            filledOut += 1
                            self.message('Sell level of %s %s reached on %s! Sold %s %s for %s %s.'%(self.price2Prec(ts['symbol'],orderInfo['price']),ts['symbol'],self.exchange.name,self.amount2Prec(ts['symbol'],orderInfo['amount']),ts['coinCurrency'],self.cost2Prec(ts['symbol'],orderInfo['cost']),ts['baseCurrency']))
                        elif orderInfo['status'] == 'canceled':
                            ts['coinsAvail'] += ts['OutTrades'][iTrade]['amount']
                            ts['OutTrades'][iTrade]['oid'] = None
                            self.message('Sell order (level %d of trade set %d on %s) was canceled manually by someone! Will be reinitialized during next update.'%(iTrade,iTs,self.exchange.name))
                
                if self.numSellLevels(iTs) == filledOut and self.numBuyLevels(iTs) == filledIn:
                    self.message('Trading set %s on %s completed! Total gain: %s %s'%(ts['symbol'],self.exchange.name,self.cost2Prec(ts['symbol'],ts['costOut']-ts['costIn']),ts['baseCurrency']))
                    tradeSetsToDelete.append(iTs)
        for iTs in tradeSetsToDelete:
            self.tradeSets.pop(iTs) 
        self.updating = False
            