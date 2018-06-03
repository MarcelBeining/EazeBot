#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
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

class CryptoTrader:
    
    def __init__(self,exchName,key,secret,password=None,uid=None,messagerFct=None):
        checkThese = ['cancelOrder','createLimitOrder','fetchBalance','fetchTicker']
        self.tradeSets = []
        self.exchange = getattr (ccxt, exchName) ({'options': { 'adjustForTimeDifference': True }})
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
        self.exchange.loadMarkets()
        # use either the given messager function or define a simple print messager function which takes a level argument as second optional input
        if messagerFct:
            self.message = messagerFct
        else:
            self.message = lambda a,b='Info': print(b + ': ' + a)
            
        if not all([self.exchange.has[x] for x in checkThese]):
            raise Exception('Exchange %s does not support all required features (cancelOrder,LimitOrder,getBalance,getTicker)'%exchName)
        self.updating = False
        self.authenticated = False
        try:
            # check if keys work
            self.exchange.fetch_balance ()
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
        self.tradeSets = state
        
    def __getstate__(self):
        return self.tradeSets
        
        
    def checkNum(self,*value):
        return all([(isinstance(val,float) | isinstance(val,int)) if not isinstance(val,list) else self.checkNum(*val) for val in value])
    
    def getITS(self,iTs):
        if isinstance(iTs,int):
            return iTs
        elif isinstance(iTs,str):
            indices =  [i for i, x in enumerate(self.tradeSets) if x['uid']==iTs]
            if len(indices)==0:
                raise ValueError('Trade set id not found')
            else:
                return indices[0]
        else:
            raise TypeError('Wrong trade set identifier Type')
           
            
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
        self.exchange.loadMarkets()            
        try:
            # check if keys work
            self.exchange.fetch_balance ()
            self.authenticated = True
        except getattr(ccxt,'AuthenticationError') as e:#
            self.authenticated = False
            self.message('Failed to authenticate at exchange %s. Please check your keys'%self.exchange.name,'error')
          
            
    def newTradeSet(self,symbol,buyLevels=[],buyAmounts=[],sellLevels=[],sellAmounts=[],sl=None,candleAbove=[],initBal=0,force=False,*moreArgs):
        if symbol not in self.exchange.symbols:
            raise NameError('Trading pair %s not found on %s'%(symbol,self.exchange.name))
        if not self.checkNum(buyAmounts) or not self.checkNum(buyLevels):
            raise TypeError('Buy levels and amounts must be of type float!')
        if not self.checkNum(sellAmounts) or not self.checkNum(sellLevels):
            raise TypeError('Sell levels and amounts must be of type float!')
        if sl and not self.checkNum(sl):
            raise TypeError('Stop-loss must be of type float!')
        if not self.checkNum(initBal): 
            raise TypeError('Initial balance must be of type float!')
        if len(buyLevels)!=len(buyAmounts):
            raise ValueError('The number of buy levels and buy amounts has to be the same')
        if len(sellLevels)!=len(sellAmounts):
            raise ValueError('The number of sell levels and sell amounts has to be the same')
            
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
                
        ts = {}
        ts['symbol'] = symbol
        ts['InTrades'] = []
        ts['uid'] = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
        ts['OutTrades'] = []
        ts['baseCurrency'] = re.search("(?<=/).*", symbol).group(0)
        ts['coinCurrency'] = re.search(".*(?=/)", symbol).group(0)
        if not force and sum(buyAmounts) != sum(sellAmounts):
            raise ValueError('Warning: It seems the buy and sell amount of %s is not the same. Is this correct?'%ts['coinCurrency'])
        if buyLevels.size > 0 and sellLevels.size > 0 and max(buyLevels) > min(sellLevels):
            raise ValueError('It seems at least one of your sell prices is lower than one of your buy, which does not make sense')
        balance = self.exchange.fetchBalance()
        if balance[ts['baseCurrency']]['free'] < sum(buyLevels*buyAmounts):
            raise ValueError('Free balance of %s not sufficient to initiate trade set'%ts['baseCurrency'])
        
        summed = 0
        # create the buy orders
        for n,_ in enumerate(buyLevels):
            trade = {}
            trade['oid'] = None
            trade['price'] = buyLevels[n]
            trade['amount'] = buyAmounts[n]
            trade['candleAbove'] = candleAbove[n]
            ts['InTrades'].append(trade)
            summed += buyAmounts[n]*buyLevels[n]
        ts['totalBuyCost'] = summed
        ts['balance'] = 0
        ts['coinsIn'] = initBal
        ts['initBal'] = initBal
        ts['baseCurrency'] = re.search("(?<=/).*", symbol).group(0)
        ts['coinCurrency'] = re.search(".*(?=/)", symbol).group(0)
        summed = 0
        # create the sell orders
        for n,_ in enumerate(sellLevels):
            trade = {}
            trade['oid'] = None
            trade['price'] = sellLevels[n]
            trade['amount'] = sellAmounts[n]
            ts['OutTrades'].append(trade)
            summed += sellAmounts[n]*sellLevels[n]
        self.message('Estimated return if all trades are executed: %.5g %s'%(summed-ts['totalBuyCost'],ts['baseCurrency']))
        ts['SL'] = sl
        if sl is not None:
            self.message('Estimated loss if buys reach stop-loss before selling: %.5g %s'%(ts['totalBuyCost']-sum(buyAmounts)*sl,ts['baseCurrency']))
        
        self.tradeSets.append(ts)
#        self.initBuyOrders(len(self.tradeSets)-1)
        self.update()
        return len(self.tradeSets)

    def getTradeSetInfo(self,iTs):
        iTs = self.getITS(iTs)
        string = '*Trade set #%d on %s [%s]:*\n'%(iTs,self.exchange.name,self.tradeSets[iTs]['symbol'])
        filledBuys = []
        filledSells = []
        for iTrade,trade in enumerate(self.tradeSets[iTs]['InTrades']):
            tmpstr = '*Buy level %d:* Price %.5g , Amount %.5g %s   '%(iTrade,trade['price'],trade['amount'],self.tradeSets[iTs]['coinCurrency'])
            if trade['oid'] is None:
                if trade['candleAbove'] is None:
                    tmpstr = tmpstr + '_Order not initiated_\n'
                else:
                    tmpstr = tmpstr + 'if DC > %.5g'%trade['candleAbove']
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                filledBuys.append([trade['amount'],trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            string += tmpstr
        string+= '\n'
        for iTrade,trade in enumerate(self.tradeSets[iTs]['OutTrades']):
            tmpstr = '*Sell level %d:* Price %.5g , Amount %.5g %s   '%(iTrade,trade['price'],trade['amount'],self.tradeSets[iTs]['coinCurrency'])
            if trade['oid'] is None:
                tmpstr = tmpstr + '_Order not initiated_\n'
            elif trade['oid'] == 'filled':
                tmpstr = tmpstr + '_Order filled_\n'
                filledSells.append([trade['amount'],trade['price']])
            else:
                tmpstr = tmpstr + '_Open order_\n'
            string += tmpstr
        if self.tradeSets[iTs]['SL'] is not None:
            string += '\n*Stop-loss* set at %.5g.\n'%self.tradeSets[iTs]['SL']
        else:
            string += '\n*No stop-loss set.*\n'
        sumBuys = sum([val[0] for val in filledBuys])
        sumSells = sum([val[0] for val in filledSells])
        string += '\n*Filled buy orders*: %.5g %s for an average price of %.5g\nFilled sell orders: %.5g %s for an average price of %.5g\n'%(sumBuys,self.tradeSets[iTs]['coinCurrency'],sum([val[0]*val[1]/sumBuys if sumBuys > 0 else None for val in filledBuys]),sumSells,self.tradeSets[iTs]['coinCurrency'],sum([val[0]*val[1]/sumSells if sumSells > 0 else None for val in filledSells]) )
        ticker = self.exchange.fetch_ticker(self.tradeSets[iTs]['symbol'])
        string += '\n*Current market price *: %.5g, \t24h-high: %.5g, \t24h-low: %.5g\n'%(ticker['last'],ticker['high'],ticker['low'])
        return string
    
    def deleteTradeSet(self,iTs,sellAll=False):
        iTs = self.getITS(iTs)
        if sellAll:
            self.sellAllNow(iTs)
        else:
            self.cancelBuyOrders(iTs)
            self.cancelSellOrders(iTs)
        self.tradeSets.pop(iTs)
        
    def deleteBuyLevel(self,iTs,iTrade):   
        iTs = self.getITS(iTs)
        if self.checkNum(iTrade):
            self.tradeSets[iTs]['InTrades'].pop(iTrade)
        else:
            raise ValueError('Some input was no number')
            
    def setBuyLevel(self,iTs,iTrade,price,amount):   
        iTs = self.getITS(iTs)
        if self.checkNum(iTrade,price,amount):
            self.tradeSets[iTs]['InTrades'][iTrade]['amount'] = amount
            self.tradeSets[iTs]['InTrades'][iTrade]['price'] = price
        else:
            raise ValueError('Some input was no number')
            
    def deleteSellLevel(self,iTs,iTrade):   
        iTs = self.getITS(iTs)
        if self.checkNum(iTrade):
            self.tradeSets[iTs]['OutTrades'].pop(iTrade)
        else:
            raise ValueError('Some input was no number')
            
    def setSellLevel(self,iTs,iTrade,price,amount):   
        iTs = self.getITS(iTs)
        if self.checkNum(iTrade,price,amount):
            self.tradeSets[iTs]['OutTrades'][iTrade]['amount'] = amount
            self.tradeSets[iTs]['OutTrades'][iTrade]['price'] = price
        else:
            raise ValueError('Some input was no number')
    
    def setSL(self,iTs,value):   
        iTs = self.getITS(iTs)
        if self.checkNum(value):
            self.tradeSets[iTs]['SL'] = value
        else:
            raise ValueError('Input was no number')
        
    def setSLBreakEven(self,iTs):   
        iTs = self.getITS(iTs)                 
        if self.tradeSets[iTs]['initBal'] > 0:
            self.message('Break even SL cannot be set as you this trade set contains %s that you obtained beforehand. Thus I do not know its buy price(s).'%self.tradeSets[iTs]['coinCurrency'])
            return 0
        elif self.tradeSets[iTs]['balance'] > 0:
            self.message('Break even SL cannot be set as your sold coins of this trade already outweigh your buy expenses (congrats!)! You might choose to sell everything immediately if this is what you want.')
            return 0
        elif self.tradeSets[iTs]['balance'] == 0:
            self.message('Break even SL cannot be set as there are no unsold %s coins right now'%self.tradeSets[iTs]['coinCurrency'])
            return 0
        else:
            breakEvenPrice = -self.tradeSets[iTs]['balance']/(self.tradeSets[iTs]['coinsIn']+sum([trade['amount'] for trade in self.tradeSets[iTs]['OutTrades'] if trade['oid'] != 'filled']))
            ticker = self.exchange.fetch_ticker(self.tradeSets[iTs]['symbol'])
            if ticker['last'] < breakEvenPrice:
                self.message('Break even SL of %.5g cannot be set as the current market price is lower (%.5g)!'%(breakEvenPrice,ticker['last']))
                return 0
            else:
                self.tradeSets[iTs]['SL'] = breakEvenPrice
                return 1

    def sellAllNow(self,iTs,price=None):
        iTs = self.getITS(iTs)
        self.cancelBuyOrders(iTs)
        self.cancelSellOrders(iTs)
        ts = self.tradeSets[iTs]
        if self.tradeSets[iTs]['coinsIn'] > 0:
            if self.exchange.has['createMarketOrder']:
                response = self.exchange.createMarketSellOrder (ts['symbol'], self.tradeSets[iTs]['coinsIn'])
            else:
                if price is None:
                    price = self.exchange.fetch_ticker(ts['symbol'])['last']
                response = self.exchange.createLimitSellOrder (ts['symbol'], self.tradeSets[iTs]['coinsIn'],price)
            time.sleep(1) # give exchange 1 sec for trading the order
            try:
                orderInfo = self.exchange.fetchOrder (response['id'],ts['symbol'])
            except ccxt.ExchangeError as e:
                orderInfo = self.exchange.fetchOrder (response['id'],ts['symbol'],{'type':'SELL'})
                    
            if orderInfo['status']=='FILLED':
                self.tradeSets[iTs]['balance'] += orderInfo['cost']
                self.message('Sold immediately at a price of %.5g %s: Sold %.5g %s for %.5g %s.'%(orderInfo['price'],ts['symbol'],orderInfo['amount'],ts['coinCurrency'],orderInfo['cost'],ts['baseCurrency']))
            else:
                self.message('Sell order was not traded immediately, updating status soon.')
                self.tradeSets[iTs]['OutTrades'].append({'oid':response['id'],'price': orderInfo['price'],'amount': orderInfo['amount']})
        else:
            self.message('No coins to sell from this trade set.')
                
    def cancelSellOrders(self,iTs):
        iTs = self.getITS(iTs)
        if len(self.tradeSets) > iTs and len(self.tradeSets[iTs]['OutTrades']) > 0:
            for iTrade,trade in reversed(list(enumerate(self.tradeSets[iTs]['OutTrades']))):
                if trade['oid'] is not None:
                    self.exchange.cancelOrder(trade['oid'],self.tradeSets[iTs]['symbol']) 
                    orderInfo = self.fetchOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'SELL')
                    if orderInfo['cost'] > 0:
                        self.message('Partly filled sell order found during canceling. Updating balance')
                        self.tradeSets[iTs]['balance'] += orderInfo['cost']
                        self.tradeSets[iTs]['coinsIn'] -= orderInfo['filled']                                
                    self.tradeSets[iTs]['coinsIn'] += trade['amount']
                del self.tradeSets[iTs]['OutTrades'][iTrade]
            self.message('All sell orders canceled for tradeSet %d (%s)'%(iTs,self.tradeSets[iTs]['symbol']))
        return True
        
    def cancelBuyOrders(self,iTs):
        iTs = self.getITS(iTs)
        if len(self.tradeSets) > iTs + 1 and len(self.tradeSets[iTs]['InTrades']) > 0:
            for iTrade,trade in reversed(list(enumerate(self.tradeSets[iTs]['InTrades']))):
                if trade['oid'] is not None:
                    self.exchange.cancelOrder(trade['oid'],self.tradeSets[iTs]['symbol']) 
                    orderInfo = self.fetchOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'BUY')
                    if orderInfo['cost'] > 0:
                        self.message('Partly filled buy order found during canceling. Updating balance')
                        self.tradeSets[iTs]['balance'] -= orderInfo['cost']
                        self.tradeSets[iTs]['coinsIn'] += orderInfo['filled']   
                    self.tradeSets[iTs]['totalBuyCost'] -= trade['amount']*trade['price']
                del self.tradeSets[iTs]['InTrades'][iTrade]
            self.message('All buy orders canceled for tradeSet %d (%s)'%(iTs,self.tradeSets[iTs]['symbol']))
        return True
    
    def initBuyOrders(self,iTs):
        iTs = self.getITS(iTs)
        # initialize buy orders
        for iTrade,trade in enumerate(self.tradeSets[iTs]['InTrades']):
            if trade['oid'] is None and trade['candleAbove'] is None:
                response = self.exchange.createLimitBuyOrder(self.tradeSets[iTs]['symbol'], trade['amount'],trade['price'])
                self.tradeSets[iTs]['InTrades'][iTrade]['oid'] = response['id']
    
    def fetchOrder(self,oid,symbol,typ):
        try:
            return self.exchange.fetchOrder (oid,symbol)
        except ccxt.ExchangeError as e:
            return self.exchange.fetchOrder (oid,symbol,{'type':typ})  
                                    
    def update(self,dailyCheck=0):
        # goes through all trade sets and checks/updates the buy/sell/stop loss orders
        # daily check is for checking if a candle closed above a certain value
        if not self.updating:
            self.updating = True
            try:
                for iTs,ts in enumerate(self.tradeSets):
                    # check if stop loss is reached
                    if not dailyCheck and ts['SL'] is not None:
                        ticker = self.exchange.fetch_ticker(ts['symbol'])
                        if ticker['last'] < ts['SL']:
                            self.message('Stop loss for pair %s has been triggered!'%ts['symbol'],'warning')
                            # cancel all sell orders, create market sell order and save resulting amount of base currency
                            self.sellAllNow(iTs,price=ticker['last'])
                    filledIn = 0
                    filledOut = 0
                    # go through buy trades 
                    for iTrade,trade in enumerate(self.tradeSets[iTs]['InTrades']):
                        if trade['oid'] == 'filled':
                            filledIn += 1
                            continue
                        elif dailyCheck and trade['oid'] is None and trade['candleAbove'] is not None:
                            ticker = self.exchange.fetch_ticker(ts['symbol'])
                            if ticker['last'] > trade['candleAbove']:
                                response = self.exchange.createLimitBuyOrder(ts['symbol'], trade['amount'],trade['price'])
                                self.tradeSets[iTs]['InTrades'][iTrade]['oid'] = response['id']
                                self.message('Daily candle of %s above %.5g triggering buy level #%d!'%(ts['symbol'],trade['candleAbove'],iTrade))
                        elif trade['oid'] is not None:
                            orderInfo = self.fetchOrder(trade['oid'],ts['symbol'],'BUY')
                            if any([orderInfo['status'].lower() == val for val in ['closed','filled']]):
                                self.tradeSets[iTs]['InTrades'][iTrade]['oid'] = 'filled'
                                self.tradeSets[iTs]['balance'] -= orderInfo['cost']
                                self.message('Buy level of %.5g %s reached, bought %.5g %s for %.5g %s.'%(orderInfo['price'],ts['symbol'],orderInfo['amount'],ts['coinCurrency'],orderInfo['cost'],ts['baseCurrency']))
                                self.tradeSets[iTs]['coinsIn'] += orderInfo['filled']
                            elif orderInfo['status'] == 'canceled':
                                self.tradeSets[iTs]['InTrades'][iTrade]['oid'] = None
                                self.message('Buy order (level %d of trade set %d) was canceled manually by someone! Will be reinitialized during next update.'%(iTrade,iTs))
                        else:
                            self.initBuyOrders(iTs)                                
                                
                    if not dailyCheck:
                        # go through all selling positions and create those for which the bought coins suffice
                        for iTrade,_ in enumerate(self.tradeSets[iTs]['OutTrades']):
                            if self.tradeSets[iTs]['OutTrades'][iTrade]['oid'] is None and self.tradeSets[iTs]['coinsIn'] >= self.tradeSets[iTs]['OutTrades'][iTrade]['amount']:
                                response = self.exchange.createLimitSellOrder(ts['symbol'], self.tradeSets[iTs]['OutTrades'][iTrade]['amount'], self.tradeSets[iTs]['OutTrades'][iTrade]['price'])
                                self.tradeSets[iTs]['OutTrades'][iTrade]['oid'] = response['id']
                                self.tradeSets[iTs]['coinsIn'] -= self.tradeSets[iTs]['OutTrades'][iTrade]['amount']
            
                        # go through sell trades 
                        for iTrade,trade in enumerate(self.tradeSets[iTs]['OutTrades']):
                            if trade['oid'] == 'filled':
                                filledOut += 1
                                continue
                            elif trade['oid'] is not None:
                                orderInfo = self.fetchOrder(trade['oid'],ts['symbol'],'SELL')
                                if any([orderInfo['status'].lower() == val for val in ['closed','filled']]):
                                    self.tradeSets[iTs]['OutTrades'][iTrade]['oid'] = 'filled'
                                    self.tradeSets[iTs]['balance'] += orderInfo['cost']
                                    self.message('Sell level of %.5g %s reached, sold %.5g %s for %.5g %s.'%(orderInfo['price'],ts['symbol'],orderInfo['amount'],ts['coinCurrency'],orderInfo['cost'],ts['baseCurrency']))
                                elif orderInfo['status'] == 'canceled':
                                    self.tradeSets[iTs]['coinsIn'] += self.tradeSets[iTs]['OutTrades'][iTrade]['amount']
                                    self.tradeSets[iTs]['OutTrades'][iTrade]['oid'] = None
                                    self.message('Sell order (level %d of trade set %d) was canceled manually by someone! Will be reinitialized during next update.'%(iTrade,iTs))
                        
                        if len(self.tradeSets[iTs]['OutTrades']) == filledOut and len(self.tradeSets[iTs]['InTrades']) == filledIn:
                            self.message('Trading set %s completed! Total gain: %.5g %s'%(ts['symbol'],self.tradeSets[iTs]['balance'],ts['baseCurrency']))
                            del self.tradeSets[iTs]
                self.updating = False
            except Exception as e:
                self.updating = False
                raise(e)
            