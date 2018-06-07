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
        self.amount2Prec = lambda a,b: str(self.exchange.amountToPrecision(a,b)).rstrip('0').rstrip('.')
        self.price2Prec = lambda a,b: str(self.exchange.priceToPrecision(a,b)).rstrip('0').rstrip('.')
        self.cost2Prec = lambda a,b: str(self.exchange.costToPrecision(a,b)).rstrip('0').rstrip('.')
        self.fee2Prec = lambda a,b: str(self.exchange.feeToPrecision(a,b)).rstrip('0').rstrip('.')

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
            if iTs < 0:
                return len(self.tradeSets)+iTs
            else:
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
          
        ts = {}
        ts['symbol'] = symbol
        ts['InTrades'] = []
        ts['uid'] = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
        ts['OutTrades'] = []
        ts['baseCurrency'] = re.search("(?<=/).*", symbol).group(0)
        ts['coinCurrency'] = re.search(".*(?=/)", symbol).group(0)

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
        ts['balance'] = 0
        ts['coinsIn'] = initCoins
        ts['initCoins'] = initCoins
        ts['initPrice'] = initPrice
        ts['totalBuyCost'] = summed + ((initCoins*initPrice) if initPrice is not None else 0)
        summed = 0
        # create the sell orders
        for n,_ in enumerate(sellLevels):
            trade = {}
            trade['oid'] = None
            trade['price'] = sellLevels[n]
            trade['amount'] = sellAmounts[n]
            ts['OutTrades'].append(trade)
            summed += sellAmounts[n]*sellLevels[n]
        self.message('Estimated return if all trades are executed: %s %s'%(self.amount2Prec(ts['symbol'],summed-ts['totalBuyCost']),ts['baseCurrency']))
        ts['SL'] = sl
        if sl is not None:
            self.message('Estimated loss if buys reach stop-loss before selling: %s %s'%(self.cost2Prec(ts['symbol'],ts['totalBuyCost']-(initCoins+sum(buyAmounts))*sl),ts['baseCurrency']))        
        self.tradeSets.append(ts)
        self.update()
        return len(self.tradeSets)
        
    def getTradeSetInfo(self,iTs):
        iTs = self.getITS(iTs)
        ts = self.tradeSets[iTs]
        string = '*Trade set #%d on %s [%s]:*\n'%(iTs,self.exchange.name,ts['symbol'])
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
            string += '*Filled buy orders:* %s %s for an average price of %s\n'%(self.amount2Prec(ts['symbol'],sumBuys,ts['coinPrecision']),ts['coinCurrency'],self.amount2Prec(ts['symbol'],sum([val[0]*val[1]/sumBuys if sumBuys > 0 else None for val in filledBuys])))
        if sumSells>0:
            string += '*Filled sell orders:* %s %s for an average price of %s\n'%(self.amount2Prec(ts['symbol'],sumSells),ts['coinCurrency'],self.cost2Prec(ts['symbol'],sum([val[0]*val[1]/sumSells if sumSells > 0 else None for val in filledSells])))
        ticker = self.exchange.fetch_ticker(ts['symbol'])
        string += '\n*Current market price *: %s, \t24h-high: %s, \t24h-low: %s\n'%tuple([self.price2Prec(ts['symbol'],val) for val in [ticker['last'],ticker['high'],ticker['low']]])
        if (ts['initCoins'] == 0 or ts['initPrice'] is not None) and (sumBuys>0 or ts['initCoins'] > 0):
            gain = (ts['coinsIn']+sum([trade['amount'] for trade in ts['OutTrades'] if trade['oid'] != 'filled']))*ticker['last'] - sum([val[0]*val[1] for val in filledBuys])
            if ts['initPrice'] is not None:
                gain -=  (ts['initCoins']*ts['initPrice'])
            string += '\n*Estimated gain/loss when selling all now: *: %s %s\n'%(self.cost2Prec(ts['symbol'],gain),ts['baseCurrency'])
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
        ts = self.tradeSets[iTs]         
        if ts['initCoins'] > 0 and ts['initPrice'] is None:
            self.message('Break even SL cannot be set as you this trade set contains %s that you obtained beforehand and no buy price information was given.'%ts['coinCurrency'])
            return 0
        elif ts['balance'] > 0:
            self.message('Break even SL cannot be set as your sold coins of this trade already outweigh your buy expenses (congrats!)! You might choose to sell everything immediately if this is what you want.')
            return 0
        elif ts['balance'] == 0:
            self.message('Break even SL cannot be set as there are no unsold %s coins right now'%ts['coinCurrency'])
            return 0
        else:
            breakEvenPrice = -ts['balance']/(ts['coinsIn']+sum([trade['amount'] for trade in ts['OutTrades'] if trade['oid'] != 'filled']))
            ticker = self.exchange.fetch_ticker(ts['symbol'])
            if ticker['last'] < breakEvenPrice:
                self.message('Break even SL of %s cannot be set as the current market price is lower (%s)!'%tuple([self.price2Prec(ts['symbol'],val) for val in [breakEvenPrice,ticker['last']]]))
                return 0
            else:
                ts['SL'] = breakEvenPrice
                return 1

    def sellAllNow(self,iTs,price=None):
        iTs = self.getITS(iTs)
        self.cancelBuyOrders(iTs)
        self.cancelSellOrders(iTs)
        ts = self.tradeSets[iTs]
        if ts['coinsIn'] > 0:
            if self.exchange.has['createMarketOrder']:
                response = self.exchange.createMarketSellOrder (ts['symbol'], ts['coinsIn'])
            else:
                if price is None:
                    price = self.exchange.fetch_ticker(ts['symbol'])['last']
                response = self.exchange.createLimitSellOrder (ts['symbol'], ts['coinsIn'],price)
            time.sleep(1) # give exchange 1 sec for trading the order
            try:
                orderInfo = self.exchange.fetchOrder (response['id'],ts['symbol'])
            except ccxt.ExchangeError as e:
                orderInfo = self.exchange.fetchOrder (response['id'],ts['symbol'],{'type':'SELL'})
                    
            if orderInfo['status']=='FILLED':
                ts['balance'] += orderInfo['cost']
                self.message('Sold immediately at a price of %s %s: Sold %s %s for %s %s.'%(self.price2Prec(ts['symbol'],orderInfo['price']),ts['symbol'],self.amount2Prec(ts['symbol'],orderInfo['amount']),ts['coinCurrency'],self.cost2Prec(ts['symbol'],orderInfo['cost']),ts['baseCurrency']))
            else:
                self.message('Sell order was not traded immediately, updating status soon.')
                ts['OutTrades'].append({'oid':response['id'],'price': orderInfo['price'],'amount': orderInfo['amount']})
        else:
            self.message('No coins to sell from this trade set.')
                
    def cancelSellOrders(self,iTs):
        iTs = self.getITS(iTs)
        if len(self.tradeSets) > iTs and len(self.tradeSets[iTs]['OutTrades']) > 0:
            for iTrade,trade in reversed(list(enumerate(self.tradeSets[iTs]['OutTrades']))):
                if trade['oid'] is not None:
                    self.cancelOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'SELL') 
                    orderInfo = self.fetchOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'SELL')
                    if orderInfo['filled'] > 0:
                        self.message('Partly filled sell order found during canceling. Updating balance')
                        self.tradeSets[iTs]['balance'] += orderInfo['price']*orderInfo['filled']
                        self.tradeSets[iTs]['coinsIn'] -= orderInfo['filled']                                
                    self.tradeSets[iTs]['coinsIn'] += trade['amount']
                del self.tradeSets[iTs]['OutTrades'][iTrade]
            self.message('All sell orders canceled for tradeSet %d (%s)'%(iTs,self.tradeSets[iTs]['symbol']))
        return True
        
    def cancelBuyOrders(self,iTs):
        iTs = self.getITS(iTs)
        if len(self.tradeSets) > iTs and len(self.tradeSets[iTs]['InTrades']) > 0:
            for iTrade,trade in reversed(list(enumerate(self.tradeSets[iTs]['InTrades']))):
                print(trade)
                if trade['oid'] is not None:
                    self.cancelOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'BUY') 
                    orderInfo = self.fetchOrder(trade['oid'],self.tradeSets[iTs]['symbol'],'BUY')
                    if orderInfo['filled'] > 0:
                        self.message('Partly filled buy order found during canceling. Updating balance')
                        self.tradeSets[iTs]['balance'] -= orderInfo['price']*orderInfo['filled']
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
    
    def cancelOrder(self,oid,symbol,typ):
        try:
            return self.exchange.cancelOrder (oid,symbol)
        except ccxt.ExchangeError as e:
            return self.exchange.cancelOrder (oid,symbol,{'type':typ}) 
        
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
                    for iTrade,trade in enumerate(ts['InTrades']):
                        if trade['oid'] == 'filled':
                            filledIn += 1
                            continue
                        elif dailyCheck and trade['oid'] is None and trade['candleAbove'] is not None:
                            ticker = self.exchange.fetch_ticker(ts['symbol'])
                            if ticker['last'] > trade['candleAbove']:
                                response = self.exchange.createLimitBuyOrder(ts['symbol'], trade['amount'],trade['price'])
                                ts['InTrades'][iTrade]['oid'] = response['id']
                                self.message('Daily candle of %s above %s triggering buy level #%d!'%(ts['symbol'],self.price2Prec(ts['symbol'],trade['candleAbove']),iTrade))
                        elif trade['oid'] is not None:
                            orderInfo = self.fetchOrder(trade['oid'],ts['symbol'],'BUY')
                            if any([orderInfo['status'].lower() == val for val in ['closed','filled']]):
                                ts['InTrades'][iTrade]['oid'] = 'filled'
                                ts['balance'] -= orderInfo['cost']
                                self.message('Buy level of %s %s reached, bought %s %s for %s %s.'%(self.price2Prec(ts['symbol'],orderInfo['price']),ts['symbol'],self.amount2Prec(ts['symbol'],orderInfo['amount']),ts['coinCurrency'],self.cost2Prec(ts['symbol'],orderInfo['cost']),ts['baseCurrency']))
                                ts['coinsIn'] += orderInfo['filled']
                            elif orderInfo['status'] == 'canceled':
                                ts['InTrades'][iTrade]['oid'] = None
                                self.message('Buy order (level %d of trade set %d) was canceled manually by someone! Will be reinitialized during next update.'%(iTrade,iTs))
                        else:
                            self.initBuyOrders(iTs)                                
                            time.sleep(1)
                                
                    if not dailyCheck:
                        # go through all selling positions and create those for which the bought coins suffice
                        for iTrade,_ in enumerate(ts['OutTrades']):
                            if ts['OutTrades'][iTrade]['oid'] is None and ts['coinsIn'] >= ts['OutTrades'][iTrade]['amount']:
                                response = self.exchange.createLimitSellOrder(ts['symbol'], ts['OutTrades'][iTrade]['amount'], ts['OutTrades'][iTrade]['price'])
                                ts['OutTrades'][iTrade]['oid'] = response['id']
                                ts['coinsIn'] -= ts['OutTrades'][iTrade]['amount']
            
                        # go through sell trades 
                        for iTrade,trade in enumerate(ts['OutTrades']):
                            if trade['oid'] == 'filled':
                                filledOut += 1
                                continue
                            elif trade['oid'] is not None:
                                orderInfo = self.fetchOrder(trade['oid'],ts['symbol'],'SELL')
                                if any([orderInfo['status'].lower() == val for val in ['closed','filled']]):
                                    ts['OutTrades'][iTrade]['oid'] = 'filled'
                                    ts['balance'] += orderInfo['cost']
                                    self.message('Sell level of %s %s reached, sold %s %s for %s %s.'%(self.price2Prec(ts['symbol'],orderInfo['price']),ts['symbol'],self.amount2Prec(ts['symbol'],orderInfo['amount']),ts['coinCurrency'],self.cost2Prec(ts['symbol'],orderInfo['cost']),ts['baseCurrency']))
                                elif orderInfo['status'] == 'canceled':
                                    ts['coinsIn'] += ts['OutTrades'][iTrade]['amount']
                                    ts['OutTrades'][iTrade]['oid'] = None
                                    self.message('Sell order (level %d of trade set %d) was canceled manually by someone! Will be reinitialized during next update.'%(iTrade,iTs))
                        
                        if len(ts['OutTrades']) == filledOut and len(ts['InTrades']) == filledIn:
                            self.message('Trading set %s completed! Total gain: %s %s'%(ts['symbol'],self.cost2Prec(ts['symbol'],ts['balance']),ts['baseCurrency']))
                            del self.tradeSets[iTs]
                self.updating = False
            except Exception as e:
                self.updating = False
                raise(e)
            