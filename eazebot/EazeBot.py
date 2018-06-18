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
"""This module contains all functions necessary for starting the Bot"""


#%% import modules
import logging
import logging.handlers  # necessary if run as main script and not interactively...dunno why
import re
import time
import datetime
import json
import dill
import requests
import base64
from shutil import copy2
from collections import defaultdict
import os
import inspect
from telegram import (ReplyKeyboardMarkup,InlineKeyboardMarkup,InlineKeyboardButton,bot)
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, RegexHandler,
                          ConversationHandler,CallbackQueryHandler)

if __name__ == '__main__':
    from tradeHandler import tradeHandler
else:
    from EazeBot.tradeHandler import tradeHandler

logFileName = 'telegramEazeBot'
MAINMENU,SETTINGS,SYMBOL,TRADESET,NUMBER,TIMING,INFO = range(7)

logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
rootLogger = logging.getLogger()
rootLogger.handlers = []  # delete old handlers in case bot is restarted but not python
rootLogger.setLevel('INFO')
fileHandler = logging.handlers.RotatingFileHandler("{0}/{1}.log".format(os.getcwd(), logFileName),maxBytes=1000000, backupCount=5)
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)
consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)


with open(os.path.join(os.path.dirname(__file__),'version.txt')) as fh:
    thisVersion = re.search('(?<=version = )\d+\.\d+',str(fh.read())).group(0)

#%% init menues
mainMenu = [['Status of Trade Sets', 'New Trade Set','Check Balance'],['Add/update exchanges (API.json)','Settings','Bot Info']]
markupMainMenu = ReplyKeyboardMarkup(mainMenu)#, one_time_keyboard=True)

tradeSetMenu = [['Add buy position', 'Add sell position','Add initial coins'],
                  ['Add stop-loss','Show trade set','Done','Cancel']]
markupTradeSetMenu = ReplyKeyboardMarkup(tradeSetMenu,one_time_keyboard=True)


#%% init base variables
__config__ = {}
job_queue = []



## define  helper functions
def copyJSON(folderName=os.getcwd(),force=0):
    if force == 0 and os.path.isfile(os.path.join(folderName,'botConfig.json')):
        logging.warning('botConfig.json already exists in\n%s\nUse copyJSON(targetfolder,force=1) or copyJSON(force=1) to overwrite both (!) JSONs'%folderName)
    else:
        copy2(os.path.join(os.path.dirname(__file__),'botConfig.json'),folderName)
    if force == 0 and os.path.isfile(os.path.join(folderName,'APIs.json')):
        logging.warning('APIs.json already exists in\n%s\nUse copyJSON(targetfolder,force=1) or copyJSON(force=1) to overwrite both (!) JSONs'%folderName)
    else:  
        copy2(os.path.join(os.path.dirname(__file__),'APIs.json'),folderName)
    logging.info('botConfig.json and APIs.json successfully copied to\n%s\nPlease open and configure these files before running the bot'%folderName)
        
def broadcastMsg(bot,userId,msg,level='info'):
    # put msg into log with userId
    getattr(rootLogger,level.lower())('User %d: %s'%(userId,msg))
    # return msg to user
    while True:
        try:
            bot.send_message(chat_id=userId, text=level + ': ' + msg)
            break
        except TypeError as e:
            pass            
        except:
            logging.warning('Some connection (?) error occured')
            continue

def unknownCmd(bot, update):
    while True:
        try:
            bot.send_message(chat_id=update.message.chat_id, text="Sorry, I didn't understand that command.")
            break
        except:
            continue
       
    
def wrongSymbolFormat(bot, update):
    while True:
        try:
            bot.send_message(chat_id=update.message.chat_id, text="Sorry, the currency pair is not in the form COINA/COINB")
            break
        except:
            continue

def getCName(symbol,which=0):
    if which == 0:
        return re.search('^\w+(?=/)',symbol).group(0)
    else:
        return re.search('(?<=/)\w+$',symbol).group(0)
    
def getFreeBalance(user_data,exch,sym):
    coin = getCName(sym,0)
    currency = getCName(sym,1)
    bal = user_data['trade'][exch].exchange.fetchBalance()
    if coin in bal:
        freeBal = [bal[coin]['free']]
    else:
        freeBal = [0]
    if currency in bal:
        freeBal.append(bal[currency]['free'])
    else:
        freeBal.append(0)
    return freeBal
        
def receivedSymbol(bot,update,user_data):
    sym = update.message.text.upper()
    if sym in user_data['trade'][user_data['chosenExchange']].exchange.symbols:
        freeBal = getFreeBalance(user_data,user_data['chosenExchange'],sym)
        user_data['newTradeSet'] = {'symbol': sym,'freeBalance':freeBal,'currency':0,'buyLevels':[],'buyAmounts':[],'sellLevels':[],'sellAmounts':[],'sl':None,'initCoins':0,'initPrice':None,'candleAbove':[]}
        bot.send_message(user_data['chatId'],'Thank you, now let us begin setting the trade set',reply_markup=markupTradeSetMenu)
        return TRADESET
    else:
        bot.send_message(user_data['chatId'],'Symbol %s was not found on exchange %s\n'%(sym,user_data['trade'][user_data['chosenExchange']].exchange.name))
        return SYMBOL
    
def receivedInfo(bot,update,user_data):    
    return user_data['lastFct'].pop()(bot,update,user_data,update.message.text)

def receivedFloat(bot,update,user_data):    
    return user_data['lastFct'].pop()(bot,update,user_data,float(update.message.text))
      
        
## define menu function
def startCmd(bot, update,user_data):
    # initiate user_data if it does not exist yet
    if __config__['telegramUserId'] != update.message.from_user.id:
        bot.send_message(user_data['chatId'],'Sorry your Telegram ID (%d) is not recognized! Bye!'%update.message.from_user.id)
        logging.warning('Unknown user %s %s (username: %s, id: %s) tried to start the bot!'%(update.message.from_user.first_name,update.message.from_user.last_name,update.message.from_user.username,update.message.from_user.id))
        return
    else:
        logging.info('User %s %s (username: %s, id: %s) (re)started the bot'%(update.message.from_user.first_name,update.message.from_user.last_name,update.message.from_user.username,update.message.from_user.id))
    if user_data:
        washere = 'back '
        user_data.update({'lastFct':[],'chosenExchange':None,'newTradeSet':None,'tempTradeSet':[None,None,None]})
    else:
        washere = ''
        user_data.update({'chatId':update.message.chat_id,'exchanges':{},'trade':{},'settings':{'fiat':[],'showProfitIn':None},'lastFct':None,'chosenExchange':None,'newTradeSet':None})
    bot.send_message(user_data['chatId'],
        "Welcome %s%s to the EazeBot! You are in the main menu."%(washere,update.message.from_user.first_name),
        reply_markup=markupMainMenu)
    return MAINMENU

def makeTSInlineKeyboard(exch,iTS):
    button_list = [[
        InlineKeyboardButton("Edit Set", callback_data='2/%s/%s'%(exch,iTS)),
        InlineKeyboardButton("Delete/SellAll", callback_data='3/%s/%s'%(exch,iTS))]]
    return InlineKeyboardMarkup(button_list)
    
def printTradeStatus(bot,update,user_data):
    if user_data['newTradeSet']:
        ct = user_data['trade'][user_data['chosenExchange']]
        tradeSet = user_data['newTradeSet']
        coin = getCName(tradeSet['symbol'],0)
        string = '*Trade set for %s*\n'%tradeSet['symbol']
        if tradeSet['initCoins']:
            string += 'Initial coins: %s %s bought for %s %s'%(ct.amount2Prec(user_data['newTradeSet']['symbol'],tradeSet['initCoins']),coin,'unknown' if tradeSet['initPrice']<0 else ct.price2Prec(tradeSet['symbol'],tradeSet['initPrice']),tradeSet['symbol'])
            
        for n,_ in enumerate(tradeSet['buyLevels']):
            string += '*Buy level %d:* Price %s , Amount %s %s %s    \n'%(n,ct.price2Prec(tradeSet['symbol'],tradeSet['buyLevels'][n]),ct.amount2Prec(tradeSet['symbol'],tradeSet['buyAmounts'][n]),coin,'' if tradeSet['candleAbove'][n] is None else 'if DC > %.5g'%tradeSet['candleAbove'][n])
        for n,_ in enumerate(tradeSet['sellLevels']):
            string+= '*Sell level %d:* Price %s , Amount %s %s   \n'%(n,ct.price2Prec(tradeSet['symbol'],tradeSet['sellLevels'][n]),ct.price2Prec(tradeSet['symbol'],tradeSet['sellAmounts'][n]),coin)
        string+= '*Stop-loss:* '+ str(tradeSet['sl'])
        bot.send_message(user_data['chatId'],string,parse_mode='markdown')    
        return TRADESET
    else:
        count = 0
        for iex,ex in enumerate(user_data['trade']):
            ct = user_data['trade'][ex]
            if ct.updating:
                bot.send_message(user_data['chatId'],'Trade sets on %s currently updating...Please retry in a few seconds.\n\n'%ex)
                count += 1
            else:
                for iTS,ts in enumerate(ct.tradeSets):
                    count += 1
                    bot.send_message(user_data['chatId'],ct.getTradeSetInfo(iTS,user_data['settings']['showProfitIn']),reply_markup=makeTSInlineKeyboard(ex,ts['uid']),parse_mode='markdown')
        if count == 0:
            bot.send_message(user_data['chatId'],'No Trade sets found')
        return MAINMENU 

def checkBalance(bot,update,user_data):
    if user_data['chosenExchange']:
        exchange = user_data['chosenExchange']
        user_data['chosenExchange'] = None
        ct = user_data['trade'][exchange]
        balance = ct.exchange.fetchBalance()
        ticker = ct.exchange.fetchTickers()
        coins = list(balance['total'].keys())
        string = '*Balance on %s (>0.001 BTC):*\n'%(exchange)
        for c in coins:
            BTCpair = '%s/BTC'%c
            BTCpair2 = 'BTC/%s'%c
            if (c == 'BTC' and balance['total'][c] > 0.001):
                string += '*%s:* %s _(free: %s)_\n'%(c, ct.cost2Prec('ETH/BTC',balance['total'][c]), ct.cost2Prec('ETH/BTC',balance['free'][c]))
            elif (c in ['EUR','USD','USDT','TUSD'] and balance['total'][c]/ticker[BTCpair2]['last'] > 0.001):
                string += '*%s:* %s _(free: %s)_\n'%(c, ct.cost2Prec(BTCpair2,balance['total'][c]), ct.cost2Prec(BTCpair2,balance['free'][c]))
            elif (BTCpair in ticker and ticker[BTCpair]['last']*balance['total'][c] > 0.001):
                string += '*%s:* %s _(free: %s)_\n'%(c, ct.amount2Prec(BTCpair,balance['total'][c]), ct.amount2Prec(BTCpair,balance['free'][c]))
        bot.send_message(user_data['chatId'],string,parse_mode='markdown')
    else:
        user_data['lastFct'].append(checkBalance)
        # list all available exanches for choosing
        exchs = [ct.exchange.name for _,ct in user_data['trade'].items()]
        buttons = [[InlineKeyboardButton(exch,callback_data='chooseExch/%s/xxx'%(exch.lower()))] for exch in sorted(exchs)] + [[InlineKeyboardButton('Cancel',callback_data='chooseExch/xxx/xxx/cancel')]]
        bot.send_message(user_data['chatId'],'For which exchange do you want to see your balance?',reply_markup=InlineKeyboardMarkup(buttons))
            
    
def createTradeSet(bot,update,user_data):
    # check if user is registered and has any authenticated exchange
    if 'trade' in user_data and len(user_data['trade'])>0:
        # check if exchange was already chosen
        if user_data['chosenExchange']:
            exchange = user_data['chosenExchange']
            if user_data['newTradeSet']:
                dif = user_data['newTradeSet']['initCoins'] + sum(user_data['newTradeSet']['buyAmounts']) - sum(user_data['newTradeSet']['sellAmounts'])
                if dif < 0:
                    coin = getCName(user_data['newTradeSet']['symbol'],0)
                    freeCoins = user_data['trade'][exchange].exchange.fetchBalance()[coin]['free']
                    if freeCoins >= -dif:
                        user_data['newTradeSet']['initCoins'] += -dif
                        bot.send_message(user_data['chatId'],'Warning: You want to sell %.5g %s more than you want to buy! I will use that amount of %s from your free balance on %s. Please make sure that amount stays free, otherwise the trade will not work.'%(-dif,coin,coin,exchange))
                    else:
                        bot.send_message(user_data['chatId'],'Warning: You want to sell %.5g %s more than you want to buy and your free balance of %s on %s is not sufficient! Please adjust trade set.'%(-dif,coin,coin,exchange))
                        return TRADESET
                logging.info('User id %s wants to create new trade set'%(update.message.from_user.id))
                user_data['newTradeSet']['force']=1
                try:    
                    # filter out non arguments and initialize tradeSet
                    user_data['newTradeSet'] = { key: user_data['newTradeSet'][key] for key in list(set(inspect.signature(user_data['trade'][exchange].newTradeSet).parameters.keys()) & set(user_data['newTradeSet'])) }
                    user_data['trade'][exchange].newTradeSet(**user_data['newTradeSet'])
                except Exception as e:
                    bot.send_message(user_data['chatId'],'There was an error during initializing the trade :\n%s\nPlease check your trade settings'%str(e),reply_markup=markupTradeSetMenu)
                    return TRADESET
                user_data['newTradeSet'] = None
                user_data['chosenExchange'] = None
                bot.send_message(user_data['chatId'],"%s trade set initiated and updated every %d min."%(user_data['trade'][exchange].tradeSets[-1]['symbol'],__config__['updateInterval']),reply_markup=markupMainMenu)
                return MAINMENU
            else:
                bot.send_message(user_data['chatId'],'Please specify your trade set now. First: Which currency pair do you want to trade? (e.g. ETH/BTC)')
                return SYMBOL
        else:
            user_data['lastFct'].append(createTradeSet)
            # list all available exanches for choosing
            exchs = [ct.exchange.name for _,ct in user_data['trade'].items()]
            buttons = [[InlineKeyboardButton(exch,callback_data='chooseExch/%s/xxx'%(exch.lower()))] for exch in sorted(exchs)] + [[InlineKeyboardButton('Cancel',callback_data='chooseExch/xxx/xxx/cancel')]]
            bot.send_message(user_data['chatId'],'For which of your authenticated exchanges do you want to add a trade set?',reply_markup=InlineKeyboardMarkup(buttons))
    else:
        bot.send_message(user_data['chatId'],'No authenticated exchanges found for your account! Please click "Add exchanges"')
        return MAINMENU

def cancelTradeSet(bot,update,user_data):
    user_data['newTradeSet'] = None
    user_data['chosenExchange'] = None
    bot.send_message(user_data['chatId'],"New trade set canceled",reply_markup=markupMainMenu)
    return MAINMENU
    
def addSL(bot,update,user_data,inputType=None,response=None):
    if inputType is None:
        user_data['lastFct'].append(lambda b,u,us,res : addSL(b,u,us,'sl',res))
        bot.send_message(user_data['chatId'],"At which price of %s do you want to trigger a market stop-loss?"%user_data['newTradeSet']['symbol'])
        return NUMBER
    elif inputType == 'sl':
        if response == 0:
            response = None
            user_data['newTradeSet']['sl'] = response
            bot.send_message(user_data['chatId'],"No SL set",reply_markup=markupTradeSetMenu)
        else:
            user_data['newTradeSet']['sl'] = response
            bot.send_message(user_data['chatId'],"Your stop-loss level is %.5g %s"%(user_data['newTradeSet']['sl'],user_data['newTradeSet']['symbol']),reply_markup=markupTradeSetMenu)
        return TRADESET

def askAmount(user_data,direction='buy',botOrQuery=None,exch,symbol):
    if direction=='sell':
        # free balance is free coins plus coins that will be bought minus coins already selling
        
        len2 = len(user_data['newTradeSet']['sellLevels'])+1
        bal = user_data['newTradeSet']['freeBalance'][0]+sum(user_data['newTradeSet']['buyAmounts'])-sum(user_data['newTradeSet']['sellAmounts'][0:len2])
        if user_data['newTradeSet']['currency']==0:
            cname = getCName(user_data['newTradeSet']['symbol'],0)
            action = 'sell'
        else:
            bal = bal*user_data['tempTradeSet'][0]
            cname = getCName(user_data['newTradeSet']['symbol'],1)
            action = 'receive'
    elif direction == 'buy':
        # free balance is free currency minus price for coins already buying
        len1 = len(user_data['newTradeSet']['buyLevels'])+1
        bal = user_data['newTradeSet']['freeBalance'][1]-sum([a*b for a,b in zip(user_data['newTradeSet']['buyLevels'][0:len1],user_data['newTradeSet']['buyAmounts'][0:len1])])
        if user_data['newTradeSet']['currency']==0:
            bal = bal/user_data['tempTradeSet'][0]
            cname = getCName(user_data['newTradeSet']['symbol'],0)
            action = 'buy'
        else:
            cname = getCName(user_data['newTradeSet']['symbol'],1)
            action = 'use'
    else:
        raise ValueError('Unknown direction specification')
    if isinstance(botOrQuery,bot.Bot):
        botOrQuery.send_message(user_data['chatId'],"What amount of %s do you want to %s (max ~%.5g minus trading fee)?"%(cname,action,bal),reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Toggle currency", callback_data='toggleCurrency/%s'%direction)]]))
    else:
        botOrQuery.edit_message_text("What amount of %s do you want to %s (max ~%.5g minus trading fee)?"%(cname,action,bal),reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Toggle currency", callback_data='toggleCurrency/%s'%direction)]]))
        botOrQuery.answer('Currency switched')
    
def addInitBalance(bot,update,user_data,inputType=None,response=None):
    coin = getCName(user_data['newTradeSet']['symbol'],0)
    if inputType is None:
        user_data['lastFct'].append(lambda b,u,us,res : addInitBalance(b,u,us,'initCoins',res))
        bot.send_message(user_data['chatId'],"You already have %s that you want to add to the trade set? How much is it?"%coin)
        return NUMBER
    elif inputType == 'initCoins':
        user_data['newTradeSet']['initCoins'] = response
        user_data['lastFct'].append(lambda b,u,us,res : addInitBalance(b,u,us,'initPrice',res))
        bot.send_message(user_data['chatId'],"What was the average price (%s) you bought it for? Type 0 if received for free and a negative number if you do not know?"%user_data['newTradeSet']['symbol'])
    elif inputType == 'initPrice':
        if response >= 0:
            user_data['newTradeSet']['initPrice'] = response
        ct = user_data['trade'][user_data['chosenExchange']]
        bot.send_message(user_data['chatId'],"You added an initial amount of %s %s that you bought for %s %s"%(ct.amount2Prec(user_data['newTradeSet']['symbol'],user_data['newTradeSet']['initCoins']),coin,'unknown' if response<0 else ct.price2Prec(user_data['newTradeSet']['symbol'],response),user_data['newTradeSet']['symbol']),reply_markup=markupTradeSetMenu)
        return TRADESET

def addPos(bot,user_data,direction):
    coin = getCName(user_data['newTradeSet']['symbol'],0)
    if direction == 'buy':
        user_data['newTradeSet']['buyLevels'].append(user_data['tempTradeSet'][0])
        user_data['newTradeSet']['buyAmounts'].append(user_data['tempTradeSet'][1])
        user_data['newTradeSet']['candleAbove'].append(user_data['tempTradeSet'][2])
    else:
        user_data['newTradeSet']['sellLevels'].append(user_data['tempTradeSet'][0])
        user_data['newTradeSet']['sellAmounts'].append(user_data['tempTradeSet'][1])
    user_data['tempTradeSet'] = [None,None,None]
    ct = user_data['trade'][user_data['chosenExchange']]
    bot.send_message(user_data['chatId'],"Your %s position #%d is %s %s for %s %s"%(direction,len(user_data['newTradeSet']['%sLevels'%direction])-1,ct.amount2Prec(user_data['newTradeSet']['symbol'],user_data['newTradeSet']['%sAmounts'%direction][-1]),coin,ct.price2Prec(user_data['newTradeSet']['symbol'],user_data['newTradeSet']['%sLevels'%direction][-1]),user_data['newTradeSet']['symbol']),reply_markup=markupTradeSetMenu)
    return TRADESET

        
def askPos(bot,update,user_data,direction,applyFct=None,inputType=None,response=None,exch=None,symbol=None):
    if symbol is None:
        symbol = user_data['newTradeSet']['symbol']
    if exch is None:
        exch = user_data['chosenExchange']
        
    if inputType is None:
        user_data['tempTradeSet'] = [None,None,None]
        user_data['lastFct'].append(lambda b,u,us,res : askPos(b,u,us,direction,applyFct,'price',res,exch,symbol))
        bot.send_message(user_data['chatId'],"At which price do you want to %s %s"%(direction,symbol))
        return NUMBER
    elif inputType == 'price':        
        if response == 0:
            bot.send_message(user_data['chatId'],"Zero not allowed")
            return NUMBER
        response = float(user_data['trade'][exch].exchange.priceToPrecision(symbol,response))
        user_data['tempTradeSet'][0] = response
        user_data['lastFct'].append(lambda b,u,us,res : askPos(b,u,us,direction,applyFct,'amount',res,exch,symbol))
        askAmount(user_data,direction,bot,exch,symbol)
        return NUMBER
    elif inputType == 'amount':
        if user_data['newTradeSet']['currency']==1:
            response =response/user_data['tempTradeSet'][0]
        response = float(user_data['trade'][exch].exchange.amountToPrecision(symbol,response))
        user_data['tempTradeSet'][1] = response
        if direction == 'buy':
            user_data['lastFct'].append(lambda b,u,us,res : askPos(b,u,us,direction,applyFct,'candleAbove',res,exch,symbol))
            bot.send_message(user_data['chatId'],'Do you want to make this a timed buy (buy only if daily candle closes above X)',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data='Yes'),InlineKeyboardButton("No", callback_data='No')]]))
            return TIMING    
        else:
            inputType = 'apply'
    if inputType == 'candleAbove':
        user_data['tempTradeSet'][2] = response
        inputType = 'apply'
    if inputType == 'apply':
        if applyFct == None:
            return addPos(bot,user_data,direction)
        else:
            return applyFct()

def addExchanges(bot,update,user_data):
    with open("APIs.json", "r") as fin:
        APIs = json.load(fin)   
    keys = list(APIs.keys())
    hasKey = [re.search('(?<=^apiKey).*',val).group(0) for val in keys if re.search('(?<=^apiKey).*',val,re.IGNORECASE) is not None ]
    hasSecret = [re.search('(?<=^apiSecret).*',val).group(0) for val in keys if re.search('(?<=^apiSecret).*',val,re.IGNORECASE) is not None ]
    hasUid = [re.search('(?<=^apiUid).*',val).group(0) for val in keys if re.search('(?<=^apiUid).*',val,re.IGNORECASE) is not None ]
    hasPassword = [re.search('(?<=^apiPassword).*',val).group(0) for val in keys if re.search('(?<=^apiPassword).*',val,re.IGNORECASE) is not None ]
    availableExchanges = set(hasKey).intersection(set(hasSecret))
    if len(availableExchanges) > 0:
        authenticatedExchanges = []
        for a in availableExchanges:
            exch = a.lower()
            exchParams = {'key': APIs['apiKey%s'%a] , 'secret': APIs['apiSecret%s'%a]}
            if a in hasUid:
                exchParams['uid'] = APIs['apiUid%s'%a]
            if a in hasPassword:
                exchParams['password'] = APIs['apiPassword%s'%a]
            # if no tradeHandler object has been created yet, create one, but also check for correct authentication, otherwise remove again
            if exch not in user_data['trade']:
                user_data['trade'][exch] = tradeHandler(exch,**exchParams,messagerFct = lambda a,b='info': broadcastMsg(bot,user_data['chatId'],a,b))
            else:
                user_data['trade'][exch].updateKeys(**exchParams)
            if not user_data['trade'][exch].authenticated:
                user_data['trade'].pop(exch)
            else:
                authenticatedExchanges.append(a)
        bot.send_message(user_data['chatId'],'Exchanges %s added/updated'%authenticatedExchanges)
    else:
        bot.send_message(user_data['chatId'],'No exchange found to add')    
        if update is not None:
            return MAINMENU

def botInfo(bot,update,user_data):
    remoteTxt = base64.b64decode(requests.get('https://api.github.com/repos/MarcelBeining/eazebot/contents/eazebot/version.txt').json()['content'])
    remoteVersion = re.search('(?<=version = )\d+\.\d+',str(remoteTxt)).group(0)
    string = '<b>******** EazeBot (v%s) ********</b>\n<i>Free python/telegram bot for easy execution and surveillance of crypto trading plans on multiple exchanges</i>\n'%thisVersion
    if float(remoteVersion) > float(thisVersion):
        string += '\n<b>There is a new version of EazeBot available on git (v%s)!</b>\n'%remoteVersion
    string+='\nReward my efforts on this bot by donating some cryptos!'
    bot.send_message(user_data['chatId'],string,parse_mode='html',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Donate',callback_data='1/xxx/xxx')]]))
    return MAINMENU
    
def doneCmd(bot,update,user_data):
    job_queue.stop()
    bot.send_message(user_data['chatId'],"Bot stopped! Trades are not updated until starting again! See you soon %s! Start me again using /start anytime you want"%(update.message.from_user.first_name))
    logging.info('User %s (id: %s) ended the bot'%(update.message.from_user.first_name,update.message.from_user.id))
    
    
# job functions   
def updateTradeSets(bot,job):
    updater = job.context
    logging.info('Updating trade sets...')
    for user in updater.dispatcher.user_data:
        if user == __config__['telegramUserId']:
            for iex,ex in enumerate(updater.dispatcher.user_data[user]['trade']):
                updater.dispatcher.user_data[user]['trade'][ex].update()
    logging.info('Finished updating trade sets...')
    
def checkCandle(bot,job):
    updater = job.context
    logging.info('Checking candles for all trade sets...')
    for user in updater.dispatcher.user_data:
        if user == __config__['telegramUserId']:
            for iex,ex in enumerate(updater.dispatcher.user_data[user]['trade']):
                # avoid to hit it during updating
                while updater.dispatcher.user_data[user]['trade'][ex].updating:
                    time.sleep(0.5)
                updater.dispatcher.user_data[user]['trade'][ex].update(dailyCheck=1)
    logging.info('Finished checking candles for all trade sets...')

def timingCallback(bot, update,user_data,query=None,response=None):
    if query is None:
        query = update.callback_query
    if query is None:
        return 0
    query.message.delete()
    if query.data == 'Yes':
        query.answer('Please give the price above which the daily candle should close in order to initiate the buy!')
        return NUMBER
    else:
        query.answer()
        return user_data['lastFct'].pop()(bot,update,user_data,None)
   
def showSettings  (bot, update,user_data,botOrQuery=None):
    # show gain/loss in fiat
    # give preferred fiat
    # stop bot with security question
    string = '*Settings:*\n_Fiat currencies(descending priority):_ %s\n_Show gain/loss in:_ %s'%(', '.join(user_data['settings']['fiat']), 'Fiat (if available)' if user_data['settings']['showProfitIn'] is not None else 'Base currency') #user_data['settings']['showProfitIn']
    settingButtons = [[InlineKeyboardButton('Define your fiat',callback_data='settings/defFiat')],[InlineKeyboardButton("Toggle showing gain/loss in baseCurrency or fiat", callback_data='settings/toggleProfit')],[InlineKeyboardButton("*Stop bot*", callback_data='settings/stopBot')]]    
    if botOrQuery == None or isinstance(botOrQuery,type(bot)):
        bot.send_message(user_data['chatId'], string, parse_mode = 'markdown', reply_markup=InlineKeyboardMarkup(settingButtons))
    else:
        botOrQuery.answer('Settings updated')
        botOrQuery.edit_message_text(string, parse_mode = 'markdown', reply_markup=InlineKeyboardMarkup(settingButtons))
        
    
    
def InlineButtonCallback(bot, update,user_data,query=None,response=None):
    if query is None:
        query = update.callback_query
    if query is None:
        return 0
    command,*args = query.data.split('/')
    
    if 'cancel' in args:
        query.message.delete()
        user_data['chosenExchange'] = None
        return MAINMENU
    else:
        if command == 'toggleCurrency':
            user_data['newTradeSet']['currency'] = (user_data['newTradeSet']['currency']+1)%2
            return askAmount(user_data,args[0],query)
        elif command == 'settings':
            subcommand = args.pop(0)
            if subcommand == 'stopBot':
                if len(args) == 0:
                    query.answer('')
                    bot.send_message(user_data['chatId'],'Are you sure you want to stop the bot? *Caution! You have to restart the Python script; until then the bot will not be responding to Telegram input!*',parse_mode = 'markdown', reply_markup = InlineKeyboardMarkup( [[InlineKeyboardButton('Yes',callback_data='settings/stopBot/Yes')],[InlineKeyboardButton("No", callback_data='settings/cancel')]]) )
                elif args[0] == 'Yes':
                    query.answer('stopping')
                    bot.send_message(user_data['chatId'],'Bot is aborting now. Goodbye!')
                    doneCmd(bot,update,user_data)
            else:
                if subcommand == 'defFiat':
                    if response is None:
                        user_data['lastFct'].append(lambda b,u,us,res : InlineButtonCallback(b,u,us,query,res))
                        return INFO
                    else:
                        user_data['settings']['fiat'] =  response.split(',')
                        
                elif subcommand == 'toggleProfit':
                        if user_data['settings']['showProfitIn'] is None:
                            if len(user_data['settings']['fiat'])>0:
                                user_data['settings']['showProfitIn'] = user_data['settings']['fiat']
                            else:
                                query.answer('Please first specify fiat currency(s) in the settings.')
                                return 0
                        else:
                            user_data['settings']['showProfitIn'] = None
                showSettings(bot, update,user_data,query)
                return MAINMENU
        else:
            exch = args.pop(0)
            uidTS = args.pop(0)
            if command == '1':   # donations
                if len(args) > 0:
                    if exch == 'xxx':
                        # get all exchange names that list the chosen coin and ask user from where to withdraw
                        exchs = [ct.exchange.name for _,ct in user_data['trade'].items() if args[0] in ct.exchange.currencies]
                        buttons = [[InlineKeyboardButton(exch,callback_data='1/%s/%s/%s'%(exch.lower(),'xxx',args[0]))] for exch in sorted(exchs)] + [[InlineKeyboardButton('Cancel',callback_data='1/xxx/xxx/cancel')]]
                        query.edit_message_text('From which exchange listing %s do you want to donate?'%args[0],reply_markup=InlineKeyboardMarkup(buttons))
                        query.answer('')
                    else:
                        if response is not None:
                            if args[0] == 'BTC':
                                address = '17SfuTsJ3xpbzgArgRrjYSjvmzegMRcU3L'
                            elif args[0] == 'ETH':
                                address = '0x2DdbDA69B27D36D0900970BCb8049546a9d621Ef'
                            elif args[0] == 'NEO':
                                address = 'AaGRMPuwtGrudXR5s7F5n11cxK595hCWUg'  
                            try:
                                if response > 0:
                                    user_data['trade'][exch].exchange.withdraw(args[0], response, address)
                                    bot.send_message(user_data['chatId'],'Donation suceeded, thank you very much!!!')
                                else:
                                    bot.send_message(user_data['chatId'],'Amount <= 0 %s. Donation canceled =('%args[0])
                                return MAINMENU
                            except Exception as e:
                                bot.send_message(user_data['chatId'],'There was an error during withdrawing, thus donation failed! =( Please consider the following reasons:\n- Insufficient funds?\n-2FA authentication required?\n-API key has no withdrawing permission?\n\nServer response was:\n<i>%s</i>'%str(e),parse_mode='html')
                                return MAINMENU
                        else:
                            ct = user_data['trade'][exch]
                            balance = ct.exchange.fetch_balance()
                            if ct.exchange.fees['funding']['percentage']:
                                query.answer('')
                                bot.send_message(user_data['chatId'],'Error. Exchange using relative withdrawal fees. Not implemented, please contact developer.')
                                return MAINMENU
                            if balance['free'][args[0]] > ct.exchange.fees['funding']['withdraw'][args[0]]:
                                query.answer('')
                                bot.send_message(user_data['chatId'],'Your free balance is %.8g %s and withdrawing fee on %s is %.8g %s. How much do you want to donate (excluding fees)'%(balance['free'][args[0]],args[0],exch,ct.exchange.fees['funding']['withdraw'][args[0]],args[0])) 
                                user_data['lastFct'].append(lambda b,u,us,res : InlineButtonCallback(b,u,us,query,res))
                                return NUMBER
                            else:
                                query.answer('%s has insufficient free %s. Choose another exchange!'%(exch,args[0])) 
                else:
                    buttons = [[InlineKeyboardButton("Donate BTC",callback_data='1/%s/%s/BTC'%('xxx','xxx')),InlineKeyboardButton("Donate ETH",callback_data='%s/%s/%d/ETH'%('xxx','xxx',1)),InlineKeyboardButton("Donate NEO",callback_data='1/%s/%s/NEO'%('xxx','xxx'))]] 
    #                    bot.send_message(user_data['chatId'],'Thank you very much for your intention to donate some crypto! Accepted coins are BTC, ETH and NEO.\nYou may either donate by sending coins manually to one of the addresses below, or more easily by letting the bot send coins (amount will be asked in a later step) from one of your exchanges by clicking the corresponding button below.\n\n*BTC address:*\n17SfuTsJ3xpbzgArgRrjYSjvmzegMRcU3L\n*ETH address:*\n0x2DdbDA69B27D36D0900970BCb8049546a9d621Ef\n*NEO address:*\nAaGRMPuwtGrudXR5s7F5n11cxK595hCWUg'  ,reply_markup=InlineKeyboardMarkup(buttons),parse_mode='markdown')
                    query.edit_message_text('Thank you very much for your intention to donate some crypto! Accepted coins are BTC, ETH and NEO.\nYou may either donate by sending coins manually to one of the addresses below, or more easily by letting the bot send coins (amount will be asked in a later step) from one of your exchanges by clicking the corresponding button below.\n\n*BTC address:*\n17SfuTsJ3xpbzgArgRrjYSjvmzegMRcU3L\n*ETH address:*\n0x2DdbDA69B27D36D0900970BCb8049546a9d621Ef\n*NEO address:*\nAaGRMPuwtGrudXR5s7F5n11cxK595hCWUg'  ,reply_markup=InlineKeyboardMarkup(buttons),parse_mode='markdown')
                    return MAINMENU
            elif command == 'chooseExch':
                query.answer('%s chosen'%exch)
                query.message.delete()
                user_data['chosenExchange'] = exch
                return user_data['lastFct'].pop()(bot,update,user_data)
            else:  # trade set commands
                if (exch not in user_data['trade'] or not any([ts['uid']==uidTS for ts in user_data['trade'][exch].tradeSets])):
                    query.edit_message_reply_markup()
                    query.edit_message_text('This trade set is not found anymore. Probably it was deleted')
                else:
                    ct = user_data['trade'][exch]
                    if ct.updating:
                        query.answer('Trade sets on %s currently updating...Please wait'%exch)
                    else:
                        if command == '2':  # edit trade set
                            if 'done' in args:
                                'done'
                            elif any(['BLD' in val for val in args]):    
                                ct.deleteBuyLevel(uidTS,int([re.search('(?<=^BLD)\d+',val).group(0) for val in args if isinstance(val,str) and 'BLD' in val][0]))
                                query.edit_message_text(ct.getTradeSetInfo(uidTS),reply_markup=makeTSInlineKeyboard(exch,uidTS),parse_mode='markdown')
                                query.answer('Deleted buy level')
                            elif any(['SLD' in val for val in args]):    
                                ct.deleteSellLevel(uidTS,int([re.search('(?<=^SLD)\d+',val).group(0) for val in args if isinstance(val,str) and 'SLD' in val][0]))
                                query.edit_message_text(ct.getTradeSetInfo(uidTS),reply_markup=makeTSInlineKeyboard(exch,uidTS),parse_mode='markdown')
                                query.answer('Deleted sell level')
                            elif 'buyAdd' in args:   
                                if response is None:
                                    sym = ct.tradeSets[ct.getITS(uidTS)]['symbol']
                                    return askPos(bot,update,user_data,direction='buy',applyFct=lambda : InlineButtonCallback(bot,update,user_data,query,'continue'),exch=exch,symbol=sym)
                                else:
                                    ct.addBuyPos(uidTS,**user_data['tempTradeSet'])
                                    user_data['tempTradeSet'] = [None,None,None]
                                    query.edit_message_text(ct.getTradeSetInfo(uidTS),reply_markup=makeTSInlineKeyboard(exch,uidTS),parse_mode='markdown')
                                    query.answer('Added new buy level')
                            elif 'sellAdd' in args:
                                print('...')
                            elif 'SLBE' in args:
                                ans = ct.setSLBreakEven(uidTS)
                                if ans:
                                    query.answer('SL set break even')
                                else:
                                    query.answer('SL break even failed to set')
                                query.edit_message_text(ct.getTradeSetInfo(uidTS),reply_markup=makeTSInlineKeyboard(exch,uidTS),parse_mode='markdown')
                            elif 'SLC' in args:
                                if response is None:
                                    query.answer('Please enter the new SL (0 = no SL)')
                                    user_data['lastFct'].append(lambda b,u,us,res : InlineButtonCallback(b,u,us,query,res))
                                    return NUMBER
                                else:
                                    response = float(response)
                                    if response == 0:
                                        response = None
                                    ct.setSL(uidTS,response)
                                    query.edit_message_text(ct.getTradeSetInfo(uidTS),reply_markup=makeTSInlineKeyboard(exch,uidTS),parse_mode='markdown')
                                    return MAINMENU                                
                            else: 
                                buttons = [[InlineKeyboardButton("Set SL Break Even",callback_data='2/%s/%s/SLBE'%(exch,uidTS)),InlineKeyboardButton("Change SL",callback_data='2/%s/%s/SLC'%(exch,uidTS))]]#,[InlineKeyboardButton("Add buy level",callback_data='2/%s/%s/buyAdd'%(exch,uidTS)),InlineKeyboardButton("Add sell level",callback_data='2/%s/%s/sellAdd'%(exch,uidTS))]]
                                iTs = ct.getITS(uidTS)
                                for i,_ in enumerate(ct.tradeSets[iTs]['InTrades']):
                                    buttons.append([InlineKeyboardButton("Delete Buy level #%d"%i,callback_data='2/%s/%s/BLD%d'%(exch,uidTS,i))])
                                for i,_ in enumerate(ct.tradeSets[iTs]['OutTrades']):
                                    buttons.append([InlineKeyboardButton("Delete Sell level #%d"%i,callback_data='2/%s/%s/SLD%d'%(exch,uidTS,i))])
                                query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
                                query.answer('Choose an option')
                        elif command == '3':  # init trade set deletion
                            if 'ok' in args:
                                query.message.delete()
                                ct.deleteTradeSet(uidTS,sellAll='yes' in args)
                                query.answer('Trade Set deleted')
                            elif 'yes' in args or 'no' in args:
                                query.answer('Ok, and are you really sure to delete this trade set?')
                                query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data='3/%s/%s/ok/%s'%(exch,uidTS,'/'.join(args))),InlineKeyboardButton("Cancel",callback_data='3/%s/%s/cancel'%(exch,uidTS))]]))
                            else:
                                query.answer('Do you want to sell your remaining coins?')
                                query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data='3/%s/%s/yes'%(exch,uidTS)),InlineKeyboardButton("No", callback_data='3/%s/%s/no'%(exch,uidTS))]]))
            

def save_data(*arg):
    if len(arg) == 1:
        updater = arg[0]
    else:
        bot,job = arg
        updater = job.context
    # remove backup
    try:
        os.remove('data.bkp') 
    except:
        logging.warning('No backup file found')
        pass
    # rename last save to backup
    try:
        os.rename('data.pickle', 'data.bkp')
        logging.info('Created user data autosave backup')
    except:
        logging.warning('Could not rename last saved data to backup')
        pass
    # write user data
    with open('data.pickle', 'wb') as f:
        dill.dump(updater.dispatcher.user_data, f)
    logging.info('User data autosaved')
        
def load_data(filename='data.pickle'):
    # load latest user data
    try:
        with open(filename, 'rb') as f:
            logging.info('Loading user data')
            return dill.load(f)
    except:
        logging.error('Error loading last autosave')
        return defaultdict(dict)
    
    
    
def startBot():
    global __config__
    global job_queue
    #%% load bot configuration
    with open("botConfig.json", "r") as fin:
        __config__ = json.load(fin)
    if isinstance(__config__['telegramUserId'],str):
        __config__['telegramUserId'] = int(__config__['telegramUserId'])
    if isinstance(__config__['updateInterval'],str):
        __config__['updateInterval'] = int(__config__['updateInterval'])
    
    
    
    #%% define the handlers to communicate with user
    conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', startCmd,pass_user_data=True)],
            states={
                MAINMENU: [RegexHandler('^Status of Trade Sets$',printTradeStatus,pass_user_data=True),
                            RegexHandler('^New Trade Set$',createTradeSet,pass_user_data=True),
                            RegexHandler('^Add/update exchanges',addExchanges,pass_user_data=True),
                            RegexHandler('^Bot Info$',botInfo,pass_user_data=True),
                            RegexHandler('^Check Balance$',checkBalance,pass_user_data=True),
                            RegexHandler('^Settings$',showSettings,pass_user_data=True),
                            CallbackQueryHandler(InlineButtonCallback,pass_user_data=True)],
                SYMBOL:   [RegexHandler('\w+/\w+',receivedSymbol,pass_user_data=True),
                            MessageHandler(Filters.text,wrongSymbolFormat)],
                TRADESET: [RegexHandler('^Add buy position$',lambda b,u,**args: askPos(b,u,direction='buy',**args),pass_user_data=True),
                            RegexHandler('^Add sell position$',lambda b,u,**args: askPos(b,u,direction='sell',**args),pass_user_data=True),
                            RegexHandler('^Add initial coins$',addInitBalance,pass_user_data=True),
                            RegexHandler('^Add stop-loss$',addSL,pass_user_data=True),
                            RegexHandler('^Show trade set$',printTradeStatus,pass_user_data=True),
                            RegexHandler('^Done$',createTradeSet,pass_user_data=True),
                            RegexHandler('^Cancel$',cancelTradeSet,pass_user_data=True),
                            MessageHandler(Filters.text,unknownCmd),
                            CallbackQueryHandler(InlineButtonCallback,pass_user_data=True)],
                NUMBER:   [RegexHandler('^[\+,\-]?\d+\.?\d*$',receivedFloat,pass_user_data=True),
                           MessageHandler(Filters.text,unknownCmd),
                           CallbackQueryHandler(InlineButtonCallback,pass_user_data=True)],
                TIMING:   [CallbackQueryHandler(timingCallback,pass_user_data=True)],
                INFO:     [RegexHandler('\w+',receivedInfo,pass_user_data=True)]
            },
            fallbacks=[CommandHandler('exit', doneCmd,pass_user_data=True)], allow_reentry = True)#, per_message = True)
    unknown_handler = MessageHandler(Filters.command, unknownCmd)
    
    #%% start telegram API, add handlers to dispatcher and start bot
    updater = Updater(token = __config__['telegramAPI'], request_kwargs={'read_timeout': 8})#, 'connect_timeout': 7})
    job_queue = updater.job_queue
    updater.dispatcher.add_handler(conv_handler)
    updater.dispatcher.add_handler(unknown_handler)
    
    updater.dispatcher.user_data = load_data()
    if len(updater.dispatcher.user_data[__config__['telegramUserId']]) > 0:
        time.sleep(2) # wait because of possibility of temporary exchange lockout
        addExchanges(updater.bot,None,updater.dispatcher.user_data[__config__['telegramUserId']])
    
    # start a job updating the trade sets each minute
    updater.job_queue.run_repeating(updateTradeSets, interval=60*__config__['updateInterval'], first=60,context=updater)
    # start a job checking every day 10 sec after midnight if any 'candleAbove' buys need to be initiated
    updater.job_queue.run_daily(checkCandle, datetime.time(0,0,10), context=updater)
    # start a job saving the user data each 5 minutes
    updater.job_queue.run_repeating(save_data, interval=5*60, first=60,context=updater)
    updater.bot.send_message(__config__['telegramUserId'],'Bot was restarted.\n Please press /start to continue.',reply_markup=ReplyKeyboardMarkup([['/start']]),one_time_keyboard=True)
    updater.start_polling()
    updater.idle()
    save_data(updater)  # last data save when finishing

# execute main if running as script
if __name__ == '__main__':
    startBot()
