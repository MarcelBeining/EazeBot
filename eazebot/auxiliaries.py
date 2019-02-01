# -*- coding: utf-8 -*-
"""
Created on Fri Feb  1 08:43:48 2019

@author: beiningm
"""
import os
import logging 
import dill
from copy import deepcopy
from shutil import copy2
from collections import defaultdict
import time

def copyJSON(folderName=os.getcwd(),force=0):
    if force == 0 and os.path.isfile(os.path.join(folderName,'botConfig.json')):
        print('Warning: botConfig.json already exists in\n%s\nUse copyJSON(targetfolder,force=1) or copyJSON(force=1) to overwrite both (!) JSONs'%folderName)
    else:
        copy2(os.path.join(os.path.dirname(__file__),'botConfig.json'),folderName)
    if force == 0 and os.path.isfile(os.path.join(folderName,'APIs.json')):
        print('Warning: APIs.json already exists in\n%s\nUse copyJSON(targetfolder,force=1) or copyJSON(force=1) to overwrite both (!) JSONs'%folderName)
    else:  
        copy2(os.path.join(os.path.dirname(__file__),'APIs.json'),folderName)
    copy2(os.path.join(os.path.dirname(__file__),'startBotScript.py'),folderName)
    copy2(os.path.join(os.path.dirname(__file__),'startBot.bat'),folderName)
    copy2(os.path.join(os.path.dirname(__file__),'updateBot.bat'),folderName)
    print('botConfig.json and APIs.json successfully copied to\n%s\nPlease open and configure these files before running the bot'%folderName)

def clean_data(user_data, allowed_users = None):
    delThese = []
    for user in user_data:
        # discard unknown users
        if not ((allowed_users is None or user in allowed_users) and 'trade' in user_data[user]):
            delThese.append(user)
        else: # discard cached messages
            if 'messages' in user_data[user]:
                typ = list(user_data[user]['messages'].keys())
                for t in typ:
                    user_data[user]['messages'][t] = []
    for k in delThese:
        user_data.pop(k, None)
    return user_data

def save_data(*arg):
    if len(arg) == 1:
        user_data = deepcopy(arg[0])
    else:
        bot,job = arg
        user_data = deepcopy(job.context.dispatcher.user_data)
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
    clean_data(user_data)
    # write user data
    with open('data.pickle', 'wb') as f:
        dill.dump(user_data, f)
    logging.info('User data autosaved')
        
def backup_data(*arg):
    if len(arg) == 1:
        user_data = deepcopy(arg[0])
    else:
        bot,job = arg
        user_data = deepcopy(job.context.dispatcher.user_data)
        
    clean_data(user_data)
    # write user data
    if not os.path.isdir('backup'):
        os.makedir('backup')
    with open(os.path.join('backup',time.strftime('%Y_%m_%d_data.pickle')), 'wb') as f:
        dill.dump(user_data, f)
    logging.info('User data backuped')   
    
    
def convert_data(from_='linux',to_='win',filename='data.pickle',filenameout='data.pickle.new'):
    with open(filename, 'rb') as fi:
        byteContent = fi.read()
        with open(filenameout, 'wb') as fo:
            if 'linux' in from_ and 'win' in to_:
                byteContent = byteContent.replace(b'cdill._dill', b'cdill.dill')
            elif 'win' in from_ and 'linux' in to_:
                byteContent = byteContent.replace(b'cdill.dill',b'cdill._dill')
            if 'git' not in from_ and 'git' in to_:
                byteContent = byteContent.replace(b'ceazebot.tradeHandler', b'ctradeHandler')
                byteContent = byteContent.replace(b'ceazebot.EazeBot', b'cEazeBot')
            elif 'git' in from_ and 'git' not in to_:
                byteContent = byteContent.replace(b'ctradeHandler', b'ceazebot.tradeHandler')
                byteContent = byteContent.replace(b'cEazeBot', b'ceazebot.EazeBot')
            fo.write(byteContent)
        
        
def load_data(filename='data.pickle'):
    # load latest user data
    if os.path.isfile(filename):
        if os.path.getmtime(filename) < time.time() - 60*60*24*14:
            answer = input('WARNING! The tradeSet data you want to load is older than 2 weeks! Are you sure you want to load it? (y/n): ')
            if answer != 'y':
                os.rename('data.pickle', 'data.old')
        try:
            with open(filename, 'rb') as f:
                logging.info('Loading user data')
                return dill.load(f)
        except Exception as e:
            raise(e)
    else:
        logging.error('No autosave file found')
        return defaultdict(dict)    
    