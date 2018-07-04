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
#import inspect
from telegram import (ReplyKeyboardMarkup,InlineKeyboardMarkup,InlineKeyboardButton,bot)
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, RegexHandler,
                          ConversationHandler,CallbackQueryHandler)
from telegram.error import BadRequest

if __name__ == '__main__' or os.path.isfile('tradeHandler.py'):
    from tradeHandler import tradeHandler
else:
    from eazebot.tradeHandler import tradeHandler

logFileName = 'telegramEazeBot'
MAINMENU,SETTINGS,SYMBOL,NUMBER,TIMING,INFO = range(6)

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
    thisVersion = re.search('(?<=version = )[0-9\.]+',str(fh.read())).group(0)

#%% init menues
mainMenu = [['Status of Trade Sets', 'New Trade Set','Check Balance'],['Add/update exchanges (APIs.json)','Settings','Bot Info']]
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
    copy2(os.path.join(os.path.dirname(__file__),'startBotScript.py'),folderName)
    copy2(os.path.join(os.path.dirname(__file__),'startBot.bat'),folderName)
    copy2(os.path.join(os.path.dirname(__file__),'updateBot.bat'),folderName)
    logging.info('botConfig.json and APIs.json successfully copied to\n%s\nPlease open and configure these files before running the bot'%folderName)
        
def broadcastMsg(bot,userId,msg,level='info'):
    # put msg into log with userId
    getattr(rootLogger,level.lower())('User %d: %s'%(userId,msg))
    # return msg to user
    count = 0
    while count < 5:
        try:
            bot.send_message(chat_id=userId, text=level + ': ' + msg)
            break
        except TypeError as e:
            pass            
        except:
            count += 1
            logging.warning('Some connection (?) error occured')
            time.sleep(1)
            continue
    if count >= 5:
        logging.error('Could not send message to bot')

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
             
def receivedInfo(bot,update,user_data):    
    if len(user_data['lastFct']) > 0:
        return user_data['lastFct'].pop()(update.message.text)
    else:
        bot.send_message(user_data['chatId'],'Unknown previous error, returning to main menu')
        return MAINMENU

def receivedFloat(bot,update,user_data): 
    if len(user_data['lastFct']) > 0:
        return user_data['lastFct'].pop()(float(update.message.text))
    else:
        bot.send_message(user_data['chatId'],'Unknown previous error, returning to main menu')
        return MAINMENU
      
        
## define menu function
def startCmd(bot, update,user_data):
    # initiate user_data if it does not exist yet
    if update.message.from_user.id not in __config__['telegramUserId']:
        bot.send_message(update.message.from_user.id,'Sorry your Telegram ID (%d) is not recognized! Bye!'%update.message.from_user.id)
        logging.warning('Unknown user %s %s (username: %s, id: %s) tried to start the bot!'%(update.message.from_user.first_name,update.message.from_user.last_name,update.message.from_user.username,update.message.from_user.id))
        return
    else:
        logging.info('User %s %s (username: %s, id: %s) (re)started the bot'%(update.message.from_user.first_name,update.message.from_user.last_name,update.message.from_user.username,update.message.from_user.id))
    if user_data:
        washere = 'back '
        user_data.update({'lastFct':[],'whichCurrency':0,'tempTradeSet':[None,None,None]})
    else:
        washere = ''
        user_data.update({'chatId':update.message.chat_id,'exchanges':{},'trade':{},'settings':{'fiat':[],'showProfitIn':None},'lastFct':[],'whichCurrency':0,'tempTradeSet':[None,None,None]})
    bot.send_message(user_data['chatId'],
        "Welcome %s%s to the EazeBot! You are in the main menu."%(washere,update.message.from_user.first_name),
        reply_markup=markupMainMenu)
    return MAINMENU

def makeTSInlineKeyboard(exch,iTS):
    button_list = [[
        InlineKeyboardButton("Edit Set", callback_data='2|%s|%s'%(exch,iTS)),
        InlineKeyboardButton("Delete/SellAll", callback_data='3|%s|%s'%(exch,iTS))]]
    return InlineKeyboardMarkup(button_list)

def buttonsEditTS(ct,uidTS,mode='full'):
    exch = ct.exchange.name.lower()
    buttons = [[InlineKeyboardButton("Add buy level",callback_data='2|%s|%s|buyAdd'%(exch,uidTS)),InlineKeyboardButton("Add sell level",callback_data='2|%s|%s|sellAdd'%(exch,uidTS))]]
    for i,_ in enumerate(ct.tradeSets[uidTS]['InTrades']):
        buttons.append([InlineKeyboardButton("Delete Buy level #%d"%i,callback_data='2|%s|%s|BLD%d'%(exch,uidTS,i))])
    for i,_ in enumerate(ct.tradeSets[uidTS]['OutTrades']):
            buttons.append([InlineKeyboardButton("Delete Sell level #%d"%i,callback_data='2|%s|%s|SLD%d'%(exch,uidTS,i))])
    if mode == 'full':
        buttons.append([InlineKeyboardButton("Set SL Break Even",callback_data='2|%s|%s|SLBE'%(exch,uidTS)),InlineKeyboardButton("Change SL",callback_data='2|%s|%s|SLC'%(exch,uidTS))])
    elif mode == 'init':
        buttons.append([InlineKeyboardButton("Add initial coins",callback_data='2|%s|%s|AIC'%(exch,uidTS)),InlineKeyboardButton("Add/change SL",callback_data='2|%s|%s|SLC'%(exch,uidTS))])
    buttons.append([InlineKeyboardButton("%s trade set"%('Deactivate' if ct.tradeSets[uidTS]['active'] else 'Activate'),callback_data='2|%s|%s|%s'%(exch,uidTS,'TSstop' if ct.tradeSets[uidTS]['active'] else 'TSgo')),InlineKeyboardButton("Delete trade set",callback_data='3|%s|%s|ok|no'%(exch,uidTS))])
    if mode == 'full':
        buttons.append([InlineKeyboardButton("Back",callback_data='2|%s|%s|back'%(exch,uidTS))])
    return buttons
    
def printTradeStatus(bot,update,user_data,onlyThisTs=None):
    count = 0
    for iex,ex in enumerate(user_data['trade']):
        ct = user_data['trade'][ex]
        if onlyThisTs is not None and onlyThisTs not in ct.tradeSets:
            continue
        count = 0       
        for iTs in ct.tradeSets:
            ts = ct.tradeSets[iTs]
            if onlyThisTs is not None and onlyThisTs != iTs:
                continue
            if ts['virgin']:
                markup = InlineKeyboardMarkup(buttonsEditTS(ct,iTs,mode='init'))
            else:
                markup = makeTSInlineKeyboard(ex,iTs)
            count += 1
            bot.send_message(user_data['chatId'],ct.getTradeSetInfo(iTs,user_data['settings']['showProfitIn']),reply_markup=markup,parse_mode='markdown')
    if count == 0:
        bot.send_message(user_data['chatId'],'No Trade sets found')
    return MAINMENU 

def checkBalance(bot,update,user_data,exchange=None):
    if exchange:
        ct = user_data['trade'][exchange]
        balance = ct.exchange.fetchBalance()
        if ct.exchange.has['fetchTickers']:
            tickers = ct.safeRun(ct.exchange.fetchTickers)
            func = lambda sym: tickers[sym]
        else:
            func = lambda sym: ct.safeRun(lambda : ct.exchange.fetchTicker(sym))
        coins = list(balance['total'].keys())
        string = '*Balance on %s (>%g BTC):*\n'%(exchange,__config__['minBalanceInBTC'])
        for c in coins:
            BTCpair = '%s/BTC'%c
            BTCpair2 = 'BTC/%s'%c
            if balance['total'][c] > 0:
                if c == 'BTC' and balance['total'][c] > __config__['minBalanceInBTC']:
                    string += '*%s:* %s _(free: %s)_\n'%(c, ct.cost2Prec('ETH/BTC',balance['total'][c]), ct.cost2Prec('ETH/BTC',balance['free'][c]))
                elif BTCpair2 in ct.exchange.symbols and balance['total'][c]/func(BTCpair2)['last'] > __config__['minBalanceInBTC'] :
                    string += '*%s:* %s _(free: %s)_\n'%(c, ct.cost2Prec(BTCpair2,balance['total'][c]), ct.cost2Prec(BTCpair2,balance['free'][c]))
                elif BTCpair in ct.exchange.symbols and func(BTCpair)['last']*balance['total'][c] > __config__['minBalanceInBTC']:
                    string += '*%s:* %s _(free: %s)_\n'%(c, ct.amount2Prec(BTCpair,balance['total'][c]), ct.amount2Prec(BTCpair,balance['free'][c]))
                
        bot.send_message(user_data['chatId'],string,parse_mode='markdown')
    else:
        user_data['lastFct'].append(lambda res: checkBalance(bot,update,user_data,res))
        # list all available exanches for choosing
        exchs = [ct.exchange.name for _,ct in user_data['trade'].items()]
        buttons = [[InlineKeyboardButton(exch,callback_data='chooseExch|%s|xxx'%(exch.lower()))] for exch in sorted(exchs)] + [[InlineKeyboardButton('Cancel',callback_data='chooseExch|xxx|xxx|cancel')]]
        bot.send_message(user_data['chatId'],'For which exchange do you want to see your balance?',reply_markup=InlineKeyboardMarkup(buttons))
            
    
def createTradeSet(bot,update,user_data,exchange=None,symbol=None):
    # check if user is registered and has any authenticated exchange
    if 'trade' in user_data and len(user_data['trade'])>0:
        # check if exchange was already chosen
        if exchange:
            ct = user_data['trade'][exchange]
            if symbol and symbol.upper() in ct.exchange.symbols:
                symbol = symbol.upper()                    
                ts, uidTS = ct.initTradeSet(symbol)
                ct.updateBalance()
                bot.send_message(user_data['chatId'],'Thank you, now let us begin setting the trade set')#,reply_markup=markupTradeSetMenu)
                printTradeStatus(bot,update,user_data,uidTS)
                return MAINMENU
            else:
                if symbol:
                    text = 'Symbol %s was not found on exchange %s'%(symbol,exchange)
                else:
                    text = 'Please specify your trade set now. First: Which currency pair do you want to trade? (e.g. ETH/BTC)'
                user_data['lastFct'].append(lambda res: createTradeSet(bot,update,user_data,exchange,res))
                bot.send_message(user_data['chatId'],text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('List all pairs on %s'%exchange,callback_data='showSymbols|%s|%s'%(exchange,'xxx')),InlineKeyboardButton('Cancel',callback_data='blabla|cancel')]]))
                return SYMBOL
        else:
            user_data['lastFct'].append(lambda res: createTradeSet(bot,update,user_data,res))
            # list all available exanches for choosing
            exchs = [ct.exchange.name for _,ct in user_data['trade'].items()]
            buttons = [[InlineKeyboardButton(exch,callback_data='chooseExch|%s|xxx'%(exch.lower()))] for exch in sorted(exchs)] + [[InlineKeyboardButton('Cancel',callback_data='chooseExch|xxx|xxx|cancel')]]
            bot.send_message(user_data['chatId'],'For which of your authenticated exchanges do you want to add a trade set?',reply_markup=InlineKeyboardMarkup(buttons))
    else:
        bot.send_message(user_data['chatId'],'No authenticated exchanges found for your account! Please click "Add exchanges"')
        return MAINMENU


def askAmount(user_data,exch,uidTS,direction,botOrQuery):
    ct = user_data['trade'][exch]
    coin = ct.tradeSets[uidTS]['coinCurrency']
    currency = ct.tradeSets[uidTS]['baseCurrency']
    if direction=='sell':
        # free balance is free coins plus coins that will be bought minus coins already selling
        bal = ct.getFreeBalance(coin) - ct.sumSellAmounts(uidTS)
        buyAmounts = ct.sumBuyAmounts(uidTS,'notfilled')
        if user_data['whichCurrency']==0:
            cname = coin
            action = 'sell'
            balText = 'free %s is'%coin
        else:
            bal *= user_data['tempTradeSet'][0]
            buyAmounts *= user_data['tempTradeSet'][0]
            cname = currency
            action = 'receive'
            balText = 'return from free %s would be'%coin
    elif direction == 'buy':
        # free balance is free currency minus price for coins already buying
        bal = ct.getFreeBalance(currency) - ct.sumBuyCosts(uidTS)
        if user_data['whichCurrency']==0:
            bal /= user_data['tempTradeSet'][0]
            cname = coin
            action = 'buy'
            balText = 'possible buy amount from your free balance is'
        else:
            cname = currency
            action = 'use'
            balText = 'free balance is'
    else:
        raise ValueError('Unknown direction specification')
    text = "What amount of %s do you want to %s (%s ~%.5g %s)?"%(cname,action,balText,bal,'plus ~%.5g from your set future buys [minus trading fee]'%(buyAmounts) if direction == 'sell' else '')
    if isinstance(botOrQuery,bot.Bot):
        botOrQuery.send_message(user_data['chatId'],text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Toggle currency", callback_data='toggleCurrency|%s|%s|%s'%(exch,uidTS,direction))],[InlineKeyboardButton("Cancel", callback_data='askAmount|cancel')]]))
    else:
        botOrQuery.edit_message_text(text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Toggle currency", callback_data='toggleCurrency|%s|%s|%s'%(exch,uidTS,direction))],[InlineKeyboardButton("Cancel", callback_data='askAmount|cancel')]]))
        botOrQuery.answer('Currency switched')
    
def addInitBalance(bot,user_data,exch,uidTS,inputType=None,response=None,fct = None):
    ct = user_data['trade'][exch]
    if inputType is None:
        user_data['lastFct'].append(lambda res : addInitBalance(bot,user_data,exch,uidTS,'initCoins',res,fct))
        bot.send_message(user_data['chatId'],"You already have %s that you want to add to the trade set? How much is it?"%ct.tradeSets[uidTS]['coinCurrency'], reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data='addInitBal|cancel')]]))
        return NUMBER
    elif inputType == 'initCoins':
        user_data['tempTradeSet'][0] = response
        user_data['lastFct'].append(lambda res : addInitBalance(bot,user_data,exch,uidTS,'initPrice',res,fct))
        bot.send_message(user_data['chatId'],"What was the average price (%s) you bought it for? Type 0 if received for free and a negative number if you do not know?"%ct.tradeSets[uidTS]['symbol'], reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data='addInitBal|cancel')]]))
        return NUMBER
    elif inputType == 'initPrice':
        if response >= 0:
            user_data['tempTradeSet'][1] = response
        addPos(bot,user_data,exch,uidTS,'init',fct)
        return MAINMENU

def addPos(bot,user_data,exch,uidTS,direction,fct=None):
    ct = user_data['trade'][exch]
    if direction == 'buy':
        ct.addBuyLevel(uidTS,user_data['tempTradeSet'][0],user_data['tempTradeSet'][1],user_data['tempTradeSet'][2])
    elif direction == 'sell':
        ct.addSellLevel(uidTS,user_data['tempTradeSet'][0],user_data['tempTradeSet'][1])
    else:
        ct.addInitCoins(uidTS,user_data['tempTradeSet'][0],user_data['tempTradeSet'][1])
    user_data['tempTradeSet'] = [None,None,None]
    if fct:
        fct()
        
def askPos(bot,user_data,exch,uidTS,direction,applyFct=None,inputType=None,response=None):
    ct = user_data['trade'][exch]
    symbol = ct.tradeSets[uidTS]['symbol']
    if inputType is None:
        user_data['tempTradeSet'] = [None,None,None]
        user_data['lastFct'].append(lambda res : askPos(bot,user_data,exch,uidTS,direction,applyFct,'price',res))
        bot.send_message(user_data['chatId'],"At which price do you want to %s %s"%(direction,symbol), reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data='askPos|cancel')]]))
        return NUMBER
    elif inputType == 'price':        
        if response == 0:
            bot.send_message(user_data['chatId'],"Zero not allowed")
            return NUMBER
        response = float(user_data['trade'][exch].exchange.priceToPrecision(symbol,response))
        user_data['tempTradeSet'][0] = response
        user_data['lastFct'].append(lambda res : askPos(bot,user_data,exch,uidTS,direction,applyFct,'amount',res))
        askAmount(user_data,exch,uidTS,direction,bot)
        return NUMBER
    elif inputType == 'amount':
        if user_data['whichCurrency']==1:
            response =response/user_data['tempTradeSet'][0]
        response = float(user_data['trade'][exch].exchange.amountToPrecision(symbol,response))
        user_data['tempTradeSet'][1] = response
        if direction == 'buy':
            user_data['lastFct'].append(lambda res : askPos(bot,user_data,exch,uidTS,direction,applyFct,'candleAbove',res))
            bot.send_message(user_data['chatId'],'Do you want to make this a timed buy (buy only if daily candle closes above X)',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data='Yes'),InlineKeyboardButton("No", callback_data='No')], [InlineKeyboardButton("Cancel", callback_data='askPos|cancel')]]))
            return TIMING    
        else:
            inputType = 'apply'
    if inputType == 'candleAbove':
        user_data['tempTradeSet'][2] = response
        inputType = 'apply'
    if inputType == 'apply':
        if applyFct == None:
            return addPos(bot,user_data,exch,direction)
        else:
            return applyFct()

def addExchanges(bot,update,user_data):
    idx = [i for i, x in enumerate(__config__['telegramUserId']) if x==user_data['chatId']][0]+1
    if idx == 1:
        with open("APIs.json", "r") as fin:
            APIs = json.load(fin)   
    else:
        with open("APIs%d.json"%idx, "r") as fin:
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
                userId = user_data['chatId']
                user_data['trade'][exch] = tradeHandler(exch,**exchParams,messagerFct = lambda a,b='info': broadcastMsg(bot,userId,a,b))
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

def getRemoteVersion():
    remoteTxt = base64.b64decode(requests.get('https://api.github.com/repos/MarcelBeining/eazebot/contents/eazebot/version.txt').json()['content'])
    return re.search('(?<=version = )[0-9\.]+',str(remoteTxt)).group(0)
        
def botInfo(bot,update,user_data):
    string = '<b>******** EazeBot (v%s) ********</b>\n<i>Free python/telegram bot for easy execution and surveillance of crypto trading plans on multiple exchanges</i>\n'%thisVersion
    remoteVersion = getRemoteVersion()
    if remoteVersion > thisVersion:
        string += '\n<b>There is a new version of EazeBot available on git (v%s)!</b>\n'%remoteVersion
    string+='\nReward my efforts on this bot by donating some cryptos!'
    bot.send_message(user_data['chatId'],string,parse_mode='html',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Donate',callback_data='1|xxx|xxx')]]))
    return MAINMENU
    
def doneCmd(bot,update,user_data):
    updater.stop()
    bot.send_message(user_data['chatId'],"Bot stopped! Trades are not updated until starting again! See you soon %s! Start me again using /start anytime you want"%(update.message.from_user.first_name))
    logging.info('User %s (id: %s) ended the bot'%(update.message.from_user.first_name,update.message.from_user.id))
    
    
# job functions   
def checkForUpdates(bot,job):
    updater = job.context
    remoteVersion = getRemoteVersion()
    if remoteVersion > thisVersion:
        updater = job.context
        for user in updater.dispatcher.user_data:
            if 'chatId' in updater.dispatcher.user_data[user]:
                bot.send_message(updater.dispatcher.user_data[user]['chatId'],'There is a new version of EazeBot available on git/pip (v%s)! Consider updating!'%remoteVersion)

def updateTradeSets(bot,job):
    updater = job.context
    logging.info('Updating trade sets...')
    for user in updater.dispatcher.user_data:
        if user in __config__['telegramUserId'] and 'trade' in updater.dispatcher.user_data[user]:
            for iex,ex in enumerate(updater.dispatcher.user_data[user]['trade']):
                updater.dispatcher.user_data[user]['trade'][ex].update()
    logging.info('Finished updating trade sets...')
    
def checkCandle(bot,job):
    updater = job.context
    logging.info('Checking candles for all trade sets...')
    for user in updater.dispatcher.user_data:
        if user in __config__['telegramUserId']:
            for iex,ex in enumerate(updater.dispatcher.user_data[user]['trade']):
                # avoid to hit it during updating
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
        return user_data['lastFct'].pop()(None)
   
def showSettings  (bot, update,user_data,botOrQuery=None):
    # show gain/loss in fiat
    # give preferred fiat
    # stop bot with security question
    string = '*Settings:*\n_Fiat currencies(descending priority):_ %s\n_Show gain/loss in:_ %s'%(', '.join(user_data['settings']['fiat']), 'Fiat (if available)' if user_data['settings']['showProfitIn'] is not None else 'Base currency') #user_data['settings']['showProfitIn']
    settingButtons = [[InlineKeyboardButton('Define your fiat',callback_data='settings|defFiat')],[InlineKeyboardButton("Toggle showing gain/loss in baseCurrency or fiat", callback_data='settings|toggleProfit')],[InlineKeyboardButton("*Stop bot*", callback_data='settings|stopBot'),InlineKeyboardButton("Back", callback_data='settings|cancel')]]    
    if botOrQuery == None or isinstance(botOrQuery,type(bot)):
        bot.send_message(user_data['chatId'], string, parse_mode = 'markdown', reply_markup=InlineKeyboardMarkup(settingButtons))
    else:
        try:
            botOrQuery.answer('Settings updated')
            botOrQuery.edit_message_text(string, parse_mode = 'markdown', reply_markup=InlineKeyboardMarkup(settingButtons))
        except BadRequest:
            bot.send_message(user_data['chatId'], string, parse_mode = 'markdown', reply_markup=InlineKeyboardMarkup(settingButtons))
        
def updateTStext(bot,update,user_data,uidTS,query=None):
    if query:
        query.message.delete()
    printTradeStatus(bot,update,user_data,uidTS)

    
def InlineButtonCallback(bot, update,user_data,query=None,response=None):
    if query is None:
        query = update.callback_query
    if query is None:
        return 0
    command,*args = query.data.split('|')
    
    if 'cancel' in args:
        query.message.delete()
        user_data['tempTradeSet'] = [None,None,None]
    else:
        if command == 'settings':
            subcommand = args.pop(0)
            if subcommand == 'stopBot':
                if len(args) == 0:
                    query.answer('')
                    bot.send_message(user_data['chatId'],'Are you sure you want to stop the bot? *Caution! You have to restart the Python script; until then the bot will not be responding to Telegram input!*',parse_mode = 'markdown', reply_markup = InlineKeyboardMarkup( [[InlineKeyboardButton('Yes',callback_data='settings|stopBot|Yes')],[InlineKeyboardButton("No", callback_data='settings|cancel')]]) )
                elif args[0] == 'Yes':
                    query.answer('stopping')
                    bot.send_message(user_data['chatId'],'Bot is aborting now. Goodbye!')
                    doneCmd(bot,update,user_data)
            else:
                if subcommand == 'defFiat':
                    if response is None:
                        user_data['lastFct'].append(lambda res : InlineButtonCallback(bot,update,user_data,query,res))
                        bot.send_message(user_data['chatId'],'Please name your fiat currencies (e.g. USD). You can also name multiple currencies separated with commata,  \
                                         (e.g. type: USD,USDT,TUSD) such that in case the first currency does not exist on an exchange, the second one is used, and so on.')
                        return INFO
                    else:
                        user_data['settings']['fiat'] =  response.upper().split(',')
                        
                elif subcommand == 'toggleProfit':
                        if user_data['settings']['showProfitIn'] is None:
                            if len(user_data['settings']['fiat'])>0:
                                user_data['settings']['showProfitIn'] = user_data['settings']['fiat']
                            else:
                                query.answer('Please first specify fiat currency(s) in the settings.')
                        else:
                            user_data['settings']['showProfitIn'] = None
                showSettings(bot, update,user_data,query)
        else:
            exch = args.pop(0)
            uidTS = args.pop(0)
            if command == 'toggleCurrency':
                user_data['whichCurrency'] = (user_data['whichCurrency']+1)%2
                return askAmount(user_data,exch,uidTS,args[0],query)
            
            elif command == 'showSymbols':
                syms = [val for val in user_data['trade'][exch].exchange.symbols if not '.d' in val]
                buttons = list()
                rowbuttons = []
                string = ''                        
                for count, sym in enumerate(syms):
                    if count % 4 == 0: # 4 buttons per row
                        if len(rowbuttons) > 0:
                            buttons.append(rowbuttons)
                        rowbuttons = [InlineKeyboardButton(sym,callback_data='chooseSymbol|%s|%s'%(exch,sym))]
                    else:
                        rowbuttons.append(InlineKeyboardButton(sym,callback_data='chooseSymbol|%s|%s'%(exch,sym)))
                    string += (sym + ', ')
                buttons.append(rowbuttons)
                buttons.append([InlineKeyboardButton('Cancel',callback_data='xxx|cancel')])
                try:
                    query.edit_message_text('Choose a pair...',reply_markup=InlineKeyboardMarkup(buttons))
                except BadRequest as e:
                    query.edit_message_text('Too many pairs to make buttons, you have to type the pair. Here is a list of all pairs:\n'+string[0:-2],reply_markup=[])
                
            elif command == 'chooseSymbol' :
                query.message.delete()
                return user_data['lastFct'].pop()(uidTS)  # it is no uidTS but the chosen symbol..i was too lazy to use new variable ;-)
            
            elif command == '1':   # donations
                if len(args) > 0:
                    if exch == 'xxx':
                        # get all exchange names that list the chosen coin and ask user from where to withdraw
                        exchs = [ct.exchange.name for _,ct in user_data['trade'].items() if args[0] in ct.exchange.currencies]
                        buttons = [[InlineKeyboardButton(exch,callback_data='1|%s|%s|%s'%(exch.lower(),'xxx',args[0]))] for exch in sorted(exchs)] + [[InlineKeyboardButton('Cancel',callback_data='1|xxx|xxx|cancel')]]
                        query.edit_message_text('From which exchange listing %s do you want to donate?'%args[0],reply_markup=InlineKeyboardMarkup(buttons))
                        query.answer('')
                    else:
                        if response is not None:
                            if args[0] == 'BTC':
                                address = '17SfuTsJ3xpbzgArgRrjYSjvmzegMRcU3L'
                            elif args[0] == 'ETH':
                                address = '0xa86711B0a368E4ed3B01a48E79844f6941Af579f'
                            elif args[0] == 'NEO':
                                address = 'AaGRMPuwtGrudXR5s7F5n11cxK595hCWUg'  
                            try:
                                if response > 0:
                                    user_data['trade'][exch].exchange.withdraw(args[0], response, address)
                                    bot.send_message(user_data['chatId'],'Donation suceeded, thank you very much!!!')
                                else:
                                    bot.send_message(user_data['chatId'],'Amount <= 0 %s. Donation canceled =('%args[0])
                            except Exception as e:
                                bot.send_message(user_data['chatId'],'There was an error during withdrawing, thus donation failed! =( Please consider the following reasons:\n- Insufficient funds?\n-2FA authentication required?\n-API key has no withdrawing permission?\n\nServer response was:\n<i>%s</i>'%str(e),parse_mode='html')
                        else:
                            ct = user_data['trade'][exch]
                            balance = ct.exchange.fetch_balance()
                            if ct.exchange.fees['funding']['percentage']:
                                query.answer('')
                                bot.send_message(user_data['chatId'],'Error. Exchange using relative withdrawal fees. Not implemented, please contact developer.')
                            if balance['free'][args[0]] > ct.exchange.fees['funding']['withdraw'][args[0]]:
                                query.answer('')
                                bot.send_message(user_data['chatId'],'Your free balance is %.8g %s and withdrawing fee on %s is %.8g %s. How much do you want to donate (excluding fees)'%(balance['free'][args[0]],args[0],exch,ct.exchange.fees['funding']['withdraw'][args[0]],args[0])) 
                                user_data['lastFct'].append(lambda res : InlineButtonCallback(bot,update,user_data,query,res))
                                return NUMBER
                            else:
                                query.answer('%s has insufficient free %s. Choose another exchange!'%(exch,args[0])) 
                else:
                    buttons = [[InlineKeyboardButton("Donate BTC",callback_data='1|%s|%s|BTC'%('xxx','xxx')),InlineKeyboardButton("Donate ETH",callback_data='%s|%s|%d|ETH'%('xxx','xxx',1)),InlineKeyboardButton("Donate NEO",callback_data='1|%s|%s|NEO'%('xxx','xxx'))]] 
                    query.edit_message_text('Thank you very much for your intention to donate some crypto! Accepted coins are BTC, ETH and NEO.\nYou may either donate by sending coins manually to one of the addresses below, or more easily by letting the bot send coins (amount will be asked in a later step) from one of your exchanges by clicking the corresponding button below.\n\n*BTC address:*\n17SfuTsJ3xpbzgArgRrjYSjvmzegMRcU3L\n*ETH address:*\n0x2DdbDA69B27D36D0900970BCb8049546a9d621Ef\n*NEO address:*\nAaGRMPuwtGrudXR5s7F5n11cxK595hCWUg'  ,reply_markup=InlineKeyboardMarkup(buttons),parse_mode='markdown')
            elif command == 'chooseExch':
                query.answer('%s chosen'%exch)
                query.message.delete()
                return user_data['lastFct'].pop()(exch)
            else:  # trade set commands
                if exch not in user_data['trade'] or uidTS not in user_data['trade'][exch].tradeSets:
                    query.edit_message_reply_markup()
                    query.edit_message_text('This trade set is not found anymore. Probably it was deleted')
                else:
                    ct = user_data['trade'][exch]                
                    if command == '2':  # edit trade set
                        if 'back' in args:
                            query.edit_message_reply_markup(reply_markup=makeTSInlineKeyboard(exch,uidTS))
                            query.answer('')
                       
                        elif any(['BLD' in val for val in args]):    
                            ct.deleteBuyLevel(uidTS,int([re.search('(?<=^BLD)\d+',val).group(0) for val in args if isinstance(val,str) and 'BLD' in val][0]))
                            updateTStext(bot,update,user_data,uidTS,query)
                            query.answer('Deleted buy level')
                        
                        elif any(['SLD' in val for val in args]):    
                            ct.deleteSellLevel(uidTS,int([re.search('(?<=^SLD)\d+',val).group(0) for val in args if isinstance(val,str) and 'SLD' in val][0]))
                            updateTStext(bot,update,user_data,uidTS,query)
                            query.answer('Deleted sell level')
                        
                        elif 'buyAdd' in args:   
                            if response is None:
                                query.edit_message_reply_markup()
                                query.answer('Adding new buy level')
                                return askPos(bot,user_data,exch,uidTS,direction='buy',applyFct=lambda : InlineButtonCallback(bot,update,user_data,query,'continue'))
                            else:
                                ct.addBuyLevel(uidTS,user_data['tempTradeSet'][0],user_data['tempTradeSet'][1],user_data['tempTradeSet'][2])
                                user_data['tempTradeSet'] = [None,None,None]
                                updateTStext(bot,update,user_data,uidTS,query)
                        
                        elif 'sellAdd' in args:
                            if response is None:
                                query.edit_message_reply_markup()
                                query.answer('Adding new sell level')
                                return askPos(bot,user_data,exch,uidTS,direction='sell',applyFct=lambda : InlineButtonCallback(bot,update,user_data,query,'continue'))
                            else:
                                ct.addSellLevel(uidTS,user_data['tempTradeSet'][0],user_data['tempTradeSet'][1])
                                user_data['tempTradeSet'] = [None,None,None]
                                updateTStext(bot,update,user_data,uidTS,query)
                        
                        elif 'AIC' in args:
                            query.edit_message_reply_markup()
                            query.answer('Adding initial coins')
                            return addInitBalance(bot,user_data,exch,uidTS,inputType=None,response=None,fct = lambda :printTradeStatus(bot,update,user_data,uidTS))
                        
                        elif 'TSgo' in args:
                            ct.activateTradeSet(uidTS)
                            updateTStext(bot,update,user_data,uidTS,query)
                            query.answer('Trade set activated')
                            
                        elif 'TSstop' in args:
                            ct.deactivateTradeSet(uidTS,1)
                            updateTStext(bot,update,user_data,uidTS,query)
                            query.answer('Trade set deactivated!')
                            
                        elif 'SLBE' in args:
                            ans = ct.setSLBreakEven(uidTS)
                            if ans:
                                query.answer('SL set break even')
                            else:
                                query.answer('SL break even failed to set')
                            updateTStext(bot,update,user_data,uidTS,query)
                            
                        elif 'SLC' in args:
                            if response is None:
                                query.answer('Please enter the new SL (0 = no SL)')
                                user_data['lastFct'].append(lambda res : InlineButtonCallback(bot,update,user_data,query,res))
                                return NUMBER
                            else:
                                response = float(response)
                                if response == 0:
                                    response = None
                                ct.setSL(uidTS,response)
                                updateTStext(bot,update,user_data,uidTS,query)
                        else: 
                            buttons = buttonsEditTS(ct,uidTS,'full')
                            query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
                            query.answer('Choose an option')
                    elif command == '3':  # init trade set deletion
                        if 'ok' in args:
                            query.message.delete()
                            ct.deleteTradeSet(uidTS,sellAll='yes' in args)
                            query.answer('Trade Set deleted')
                        elif 'yes' in args or 'no' in args:
                            query.answer('Ok, and are you really sure to delete this trade set?')
                            query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data='3|%s|%s|ok|%s'%(exch,uidTS,'|'.join(args))),InlineKeyboardButton("Cancel",callback_data='3|%s|%s|cancel'%(exch,uidTS))]]))
                        else:
                            query.answer('Do you want to sell your remaining coins?')
                            query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data='3|%s|%s|yes'%(exch,uidTS)),InlineKeyboardButton("No", callback_data='3|%s|%s|no'%(exch,uidTS))]]))
    return MAINMENU

def clean_data(updater):
    delThese = []
    for user in updater.dispatcher.user_data:
        if not (user in __config__['telegramUserId'] and 'trade' in updater.dispatcher.user_data[user]):
            delThese.append(user)
    for k in delThese:
        updater.dispatcher.user_data.pop(k, None)

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
    clean_data(updater)
    # write user data
    with open('data.pickle', 'wb') as f:
        dill.dump(updater.dispatcher.user_data, f)
    logging.info('User data autosaved')
        
def load_data(filename='data.pickle'):
    # load latest user data
    if os.path.isfile(filename):
        try:
            with open(filename, 'rb') as f:
                logging.info('Loading user data')
                return dill.load(f)
        except Exception as e:
            raise(e)
    else:
        logging.error('No autosave file found')
        return defaultdict(dict)    
    
def startBot():
    global __config__
    global job_queue
    global updater
    #%% load bot configuration
    with open("botConfig.json", "r") as fin:
        __config__ = json.load(fin)
    if isinstance(__config__['telegramUserId'],str) or isinstance(__config__['telegramUserId'],int):
        __config__['telegramUserId'] = [int(__config__['telegramUserId'])]
    elif isinstance(__config__['telegramUserId'],list):
        __config__['telegramUserId'] = [int(val) for val in __config__['telegramUserId']]
    if isinstance(__config__['updateInterval'],str):
        __config__['updateInterval'] = int(__config__['updateInterval'])
    if 'minBalanceInBTC' not in __config__:
        __config__['minBalanceInBTC'] = 0.001
    if isinstance(__config__['minBalanceInBTC'],str):
        __config__['minBalanceInBTC'] = float(__config__['minBalanceInBTC'])
    
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
                SYMBOL:   [RegexHandler('\w+/\w+',receivedInfo,pass_user_data=True),
                            MessageHandler(Filters.text,wrongSymbolFormat),
                            CallbackQueryHandler(InlineButtonCallback,pass_user_data=True)],
                NUMBER:   [RegexHandler('^[\+,\-]?\d+\.?\d*$',receivedFloat,pass_user_data=True),
                           MessageHandler(Filters.text,unknownCmd),
                           CallbackQueryHandler(InlineButtonCallback,pass_user_data=True)],
                TIMING:   [CallbackQueryHandler(timingCallback,pass_user_data=True),
                           CallbackQueryHandler(InlineButtonCallback,pass_user_data=True)],
                INFO:     [RegexHandler('\w+',receivedInfo,pass_user_data=True)]
            },
            fallbacks=[CommandHandler('exit', doneCmd,pass_user_data=True)], allow_reentry = True)#, per_message = True)
    unknown_handler = MessageHandler(Filters.command, unknownCmd)
    
    #%% start telegram API, add handlers to dispatcher and start bot
    updater = Updater(token = __config__['telegramAPI'], request_kwargs={'read_timeout': 10})#, 'connect_timeout': 7})
    job_queue = updater.job_queue
    updater.dispatcher.add_handler(conv_handler)
    updater.dispatcher.add_handler(unknown_handler)
    
    updater.dispatcher.user_data = load_data()
    sdfs
    clean_data(updater)
    for user in __config__['telegramUserId']:
        if user in updater.dispatcher.user_data and len(updater.dispatcher.user_data[user]) > 0:
            time.sleep(2) # wait because of possibility of temporary exchange lockout
            addExchanges(updater.bot,None,updater.dispatcher.user_data[user])
    
    
    for user in __config__['telegramUserId']:
        try:
            updater.bot.send_message(user,'Bot was restarted.\n Please press /start to continue.',reply_markup=ReplyKeyboardMarkup([['/start']]),one_time_keyboard=True)
        except:
            pass
    # start a job updating the trade sets each minute
    updater.job_queue.run_repeating(updateTradeSets, interval=60*__config__['updateInterval'], first=60,context=updater)
    # start a job checking for updates once a  day
    updater.job_queue.run_repeating(checkForUpdates, interval=60*60*24, first=0,context=updater)
    # start a job checking every day 10 sec after midnight if any 'candleAbove' buys need to be initiated
    updater.job_queue.run_daily(checkCandle, datetime.time(0,0,10), context=updater)
    # start a job saving the user data each 5 minutes
    updater.job_queue.run_repeating(save_data, interval=5*60, first=60,context=updater)
    
    updater.start_polling()
    updater.idle()
    save_data(updater)  # last data save when finishing

# execute main if running as script
if __name__ == '__main__':
    startBot()
