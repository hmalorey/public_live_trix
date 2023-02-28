#*****************
# Bot description
#*****************
# Code last update : 02 janvier 2023
# ETH / USDT on Binance
# H1 trading Trix
# Launch date = 07/01/2023

#*****************
# Import packages #
#*****************

# Packages à importer
import ta
from dotenv import load_dotenv
import telebot

# Packages standards
import pandas as pd
import json
import time
from math import *
from datetime import datetime
import os
import ccxt

#*********************
# Print execution time 
#*********************

now = datetime.now()
current_time = now.strftime("%d/%m/%Y %H:%M:%S")
print("--- Execution Time :", current_time, "---")

#*********************
# Load auth parameters 
#*********************

## Récupérer les variables d'environnement stockées dans .env
load_dotenv() # looks for a .env file and if it finds one it will load the env variables from the file and make them accessible to the project

# Initiate instance of API client -- we define the exchange object
exchange_id = 'binance'
exchange_class = getattr(ccxt, exchange_id)
exchange = exchange_class({
    'apiKey': os.getenv("BINANCE_API_KEY"),
    'secret': os.getenv("BINANCE_API_SECRET"),
    'timeout': 30000,
    'enableRateLimit': False
})

#*********************
# Telegram Auth #
#*********************

#Auth telegram bot -- private bot to send messages to Private Channel
private_bot = telebot.TeleBot(os.getenv("TELEGRAM_PRIVATE_BOT_API_KEY"), parse_mode='HTML') # parse_mode permet de formatter le texte
hugo_chatID = os.getenv("TELEGRAM_HUGO_CHAT_ID")

# Channel bot to send message to public channel
channel_bot = telebot.TeleBot(os.getenv("TELEGRAM_CHANNEL_BOT_API_KEY"), parse_mode='HTML') # parse_mode permet de formatter le texte
channel_chatID = os.getenv("TELEGRAM_CHANNEL_CHAT_ID")


#*********************
# Define traded pair 
#*********************

coinSymbol = 'ETH'
fiatSymbol = 'USDT'
pairSymbol = f"{coinSymbol}/{fiatSymbol}"

#*****************************************
# Define getBalance and truncate functions 
#*****************************************

# Définition d'une fonction qui renvoie la balance d'un coin spécifié pour un échange donné
def get_balance(myexchange, coin):
    balance = myexchange.fetch_balance()[coin]['free']
    return round(float(balance),4)


# Définition d'une fonction de troncature permettant de préciser le nbr de décimales souhaité
def truncate(x, decimals=0):
    r = floor(float(x)*10**decimals)/10**decimals
    return str(r)

tronc = 3 # Définit le nombre de chiffres apres la virgule pris en compte pour les ordres

#*************************************************************
# Get historical data and compute technical indicators 
#*************************************************************

t_frame = '1h'
lim = 450 # nombre de périodes récupérées dans le passé (lim)
raw_pricedata = None
raw_pricedata_df = None

raw_pricedata = exchange.fetch_ohlcv(pairSymbol, timeframe=t_frame, limit=lim) # limit = nombre de périodes dans le passé
raw_pricedata_df = pd.DataFrame(raw_pricedata, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

##Convert TIME and set timestamp as index
raw_pricedata_df = raw_pricedata_df.set_index(raw_pricedata_df['timestamp'])
raw_pricedata_df.index = pd.to_datetime(raw_pricedata_df.index, unit='ms')
del raw_pricedata_df['timestamp']

# Setup d'un nouveau data frame pour calculer les indicateurs de façon clean
pricedata_df = None
pricedata_df = raw_pricedata_df.copy()

## -- Trix Indicator --##
trixLength = 26
trixSignal = 18

pricedata_df['TRIX'] = ta.trend.ema_indicator(ta.trend.ema_indicator(ta.trend.ema_indicator(close=pricedata_df['close'], window=trixLength), window=trixLength), window=trixLength) #calcul d'une triple EMA
pricedata_df['TRIX_PCT'] = pricedata_df["TRIX"].pct_change()*100 #calcule le % de variation p/r a la ligne précédente / example: data = [[10, 18, 11], [20, 15, 8], [30, 20, 3]] df = pd.DataFrame(data) print(df.pct_change())
pricedata_df['TRIX_SIGNAL'] = ta.trend.sma_indicator(pricedata_df['TRIX_PCT'],trixSignal) #calcule une moyenne mobile simple du Trix percentage qui sert d'indicateur long / short au croisement
pricedata_df['TRIX_HISTO'] = pricedata_df['TRIX_PCT'] - pricedata_df['TRIX_SIGNAL'] #calcule la différence entre Trix PCT et Signal, si positif = croisement haussier = long sinon croisement baisser = short

## -- Stoch RSI --##
stochWindow = 10
stochTop = 0.82
stochBottom = 0.20
pricedata_df['STOCH_RSI'] = ta.momentum.stochrsi(close=pricedata_df['close'], window=stochWindow)
### ta.momentum.stochrsi renvoie le stoch RSI pas du tout smoothé, donc les paramèrtes smooth1 et smooth2 sont inutiles
### Pour retrouver le même résultat sur Pandas TA mettre k=1 et d=1 et afficher STOCHRSIk
### Sur TradingView, mettre k=1, d=1 et n'afficher que la courbe de K et pas celle de D. Mettre RSI Lenght = Stoch Length = window

# Avec le package ta, pour obtenir %K, il faut faire ta.momentum.stochrsi_k
## -- Moving averages -- ##
smaShort = 40
smaLong = 400
pricedata_df['SHORT_SMA'] = ta.trend.sma_indicator(pricedata_df['close'], smaShort)
pricedata_df['LONG_SMA'] = ta.trend.sma_indicator(pricedata_df['close'], smaLong)

print(pricedata_df.tail(5))
# La donnée renvoyée par l'API est UTC, donc il faut ajouter 2 heures (en été) à ces heures pour aller checker la bonne heure sur Trading View (UTC +2)

#**********************************
# Get Exchange Account Live Data #
#**********************************

actualPrice = pricedata_df['close'].iloc[-1] # sélectionne dans la colonne close, la dernière valeur (la plus à jour sur le timeframe défini)
fiatBalance = get_balance(exchange, fiatSymbol)
coinBalance = get_balance(exchange, coinSymbol)
minCoin = 15 / actualPrice # permet de définir le minimum de token a avoir pour (ré)investir. Ici il est défini comme étant 15 USD de ce coin

#**********************************
# Define buy and sell conditions #
#**********************************

# -- Condition to SPOT BUY -- #
def buyCondition(row):
  if row['TRIX_HISTO'] > 0 and row['STOCH_RSI'] < stochTop and row['SHORT_SMA'] > row['LONG_SMA']:
    return True
  else:
    return False

# -- Condition to SPOT SELL --  #
def sellCondition(row):
  if row['TRIX_HISTO'] < 0 and row['STOCH_RSI'] > stochBottom:
    return True
  else:
    return False


#**********************************************************************##
#### -- TRADING BOT SPOT MARKET ORDER EXECUTION -- ####
##*********************************************************************##

# Passer en argument la donnée non pas du dernier prix mais de l'avant dernier prix, car on ne peut pas calculer les indicateurs sur la période en cours (elle n'est pas terminée)
# Donc on passe pricedata_df.iloc[-2] à cette fonction non iloc[-1]

if buyCondition(pricedata_df.iloc[-2]):
    if float(fiatBalance) > 15:
        buyAmount = truncate(float(fiatBalance)/actualPrice, tronc)
        buyOrder = exchange.create_market_buy_order(pairSymbol, buyAmount)
        
        #-Messaging-#
        private_message = f"🚀 Trix is LONG. Opening a new position.\n✔️ Market bought {buyOrder['filled']} {coinSymbol} at {buyOrder['average']} {fiatSymbol} for {round(buyOrder['cost'],2)} {fiatSymbol}."
        public_message = f"🚀 Strategy is LONG. Opening a new position.\n✔️ Market bought {buyOrder['filled']} {coinSymbol} at {buyOrder['average']} {fiatSymbol} for {round(buyOrder['cost'],2)} {fiatSymbol}."
        print(private_message)
        private_bot.send_message(hugo_chatID, private_message) # send private message
        channel_bot.send_message(channel_chatID, public_message) # send channel message

    else:
        #-Messaging-#
        private_message = f"✅ Trix is LONG.\nPORTFOLIO: \n{coinBalance} {coinSymbol} at {actualPrice} / coin \n{truncate(fiatBalance,2)} {fiatSymbol} \nTotal: {truncate(coinBalance*actualPrice + fiatBalance,2)} {fiatSymbol}"
        public_message = f"✅ Strategy is LONG.\nPORTFOLIO: \n{coinBalance} {coinSymbol} at {actualPrice} / coin \n{truncate(fiatBalance,2)} {fiatSymbol} \nTotal: {truncate(coinBalance*actualPrice + fiatBalance,2)} {fiatSymbol}"
        print(private_message)
        private_bot.send_message(hugo_chatID, private_message) # send private message
        channel_bot.send_message(channel_chatID, public_message) # send channel message

elif sellCondition(pricedata_df.iloc[-2]):
    if float(coinBalance) > minCoin:
        sellAmount = truncate(coinBalance, tronc)
        sellOrder = exchange.create_market_sell_order(pairSymbol, sellAmount)

        #-Messaging-#
        private_message = f"❌ Trix is SHORT. Closing current position.\n✔️ Market sold {sellOrder['filled']} {coinSymbol} at {sellOrder['average']} {fiatSymbol} for {round(sellOrder['cost'],2)} {fiatSymbol}."
        public_message = f"❌ Strategy is SHORT. Closing current position.\n✔️ Market sold {sellOrder['filled']} {coinSymbol} at {sellOrder['average']} {fiatSymbol} for {round(sellOrder['cost'],2)} {fiatSymbol}."
        print(private_message)
        private_bot.send_message(hugo_chatID, private_message) # send private message
        channel_bot.send_message(channel_chatID, public_message) # send channel message
        
    else:
         #-Messaging-#
        private_message = f"👉 Trix is SHORT. Waiting for opportunity.\n💰 <b>Portfolio</b> 💰\n{coinBalance} {coinSymbol} at {actualPrice} {fiatSymbol} / coin \n{truncate(fiatBalance,2)} {fiatSymbol} \nTotal: {truncate(coinBalance*actualPrice + fiatBalance,2)} {fiatSymbol}"
        public_message = f"👉 Waiting for opportunity.\n💰 <b>Portfolio</b> 💰\n{coinBalance} {coinSymbol} at {actualPrice} {fiatSymbol} / coin \n{truncate(fiatBalance,2)} {fiatSymbol} \nTotal: {truncate(coinBalance*actualPrice + fiatBalance,2)} {fiatSymbol}"
        print(private_message)
        private_bot.send_message(hugo_chatID, private_message) # send private message
        channel_bot.send_message(channel_chatID, public_message) # send channel message

else :
    #-Messaging-#
    private_message = f"👉 Waiting for opportunity.\n💰 <b>Portfolio</b> 💰\n{coinBalance} {coinSymbol} at {actualPrice} {fiatSymbol} / coin \n{truncate(fiatBalance,2)} {fiatSymbol} \nTotal: {truncate(coinBalance*actualPrice + fiatBalance,2)} {fiatSymbol}"
    public_message = f"👉 Waiting for opportunity.\n💰 <b>Portfolio</b> 💰\n{coinBalance} {coinSymbol} at {actualPrice} {fiatSymbol} / coin \n{truncate(fiatBalance,2)} {fiatSymbol} \nTotal: {truncate(coinBalance*actualPrice + fiatBalance,2)} {fiatSymbol}"
    print(private_message)
    private_bot.send_message(hugo_chatID, private_message) # send private message
    channel_bot.send_message(channel_chatID, public_message) # send channel message