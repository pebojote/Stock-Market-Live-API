from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
import random

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
CORS(app)

# --- Cache Setup ---
api_cache = {
    "data": None,
    "last_updated": None
}
CACHE_DURATION = timedelta(minutes=5)

# --- Helper Functions (No Changes Here) ---

def format_volume(volume):
    if volume is None: return "N/A"
    if volume >= 1_000_000: return f"{volume / 1_000_000:.2f}M"
    if volume >= 1_000: return f"{volume / 1_000:.2f}K"
    return str(volume)

def get_rank(rsi):
    if rsi > 75: return 'Excellent'
    if rsi > 65: return 'Very Good'
    if rsi > 55: return 'Good'
    return 'Fair'
    
def get_risk_note():
    notes = [
        {'title': 'Profit-Taking Risk', 'reason': 'High RSI suggests a pullback as investors lock in gains.'},
        {'title': 'Overextended Technicals', 'reason': 'The price has moved very far, very fast, risking a reversal.'},
        {'title': 'High Expectations', 'reason': 'Stock is priced for perfection; any disappointment could cause a drop.'}
    ]
    return random.choice(notes)

def get_dynamic_tickers():
    try:
        url = "https://finance.yahoo.com/most-active"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', {'class': 'W(100%)'})
        tickers = [link.text for link in table.find_all('a', {'data-test': 'quoteLink'})[:25]]
        if not tickers: raise ValueError("Could not find any tickers from scraping.")
        logging.info(f"Dynamically fetched most active tickers: {tickers}")
        return tickers
    except Exception as e:
        logging.error(f"Failed to scrape tickers, using fallback list: {e}")
        return ['NVDA', 'TSLA', 'AAPL', 'SMCI', 'AVGO', 'GME', 'PLTR', 'AMD', 'LLY', 'DELL']

# --- Market Status Endpoint (No Changes Here) ---
@app.route('/api/market-status')
def get_market_status():
    try:
        market_ticker = yf.Ticker("^GSPC")
        info = market_ticker.info
        market_state = info.get('marketState', 'UNKNOWN').upper()
        status_description = {
            "PRE": "PRE-MARKET", "REGULAR": "REGULAR HOURS", "POST": "AFTER-HOURS",
            "PREPRE": "PRE-MARKET", "POSTPOST": "AFTER-HOURS", "CLOSED": "CLOSED"
        }.get(market_state, market_state)
        est = pytz.timezone('US/Eastern')
        current_time_est = datetime.now(est).strftime('%I:%M:%S %p EST')
        return jsonify({"status": f"Market is currently {status_description}", "time": current_time_est})
    except Exception as e:
        logging.error(f"Could not fetch market status: {e}")
        return jsonify({"status": "Market status is currently unavailable", "time": ""}), 500

# --- Main API Endpoint (Now with Improved Logging and Resilience) ---
@app.route('/api/top-gainers')
def get_top_gainers_data():
    global api_cache

    if api_cache["data"] and datetime.utcnow() - api_cache["last_updated"] < CACHE_DURATION:
        logging.info("Returning data from cache.")
        return jsonify(api_cache["data"])

    logging.info("Cache is stale or empty. Fetching new data.")
    
    try:
        active_tickers = get_dynamic_tickers()
        all_data = []

        for symbol in active_tickers:
            try:
                # --- NEW: More detailed logging ---
                logging.info(f"--- Processing symbol: {symbol} ---")
                
                # --- NEW: Fetch data individually for better error isolation ---
                ticker_obj = yf.Ticker(symbol)
                
                info = ticker_obj.info
                # --- NEW: Check if the info dictionary is valid and has price data ---
                if not info or 'regularMarketPrice' not in info or info.get('regularMarketPrice') is None:
                    logging.warning(f"Skipping {symbol}: Missing critical price data in '.info'.")
                    continue

                hist = ticker_obj.history(period="3mo")
                if hist.empty:
                    logging.warning(f"Skipping {symbol}: History data was empty.")
                    continue

                market_state = info.get('marketState', 'UNKNOWN').upper()
                price_type = "REGULAR"
                
                regular_price = info.get('regularMarketPrice', 0)
                prev_close = info.get('previousClose', 1)
                
                change = regular_price - prev_close
                
                # We will keep the filter disabled for now to see all data
                # if change <= 0: continue
                
                change_percent = (change / prev_close) * 100 if prev_close else 0

                display_price = regular_price
                market_change_str = ""

                if market_state in ["PRE", "PREPRE"] and info.get('preMarketPrice'):
                    display_price = info['preMarketPrice']
                    price_type = "PRE"
                    pre_market_change = display_price - regular_price
                    pre_market_percent = (pre_market_change / regular_price) * 100 if regular_price else 0
                    market_change_str = f" ({pre_market_change:+.2f}, {pre_market_percent:+.2f}%)"
                elif market_state in ["POST", "POSTPOST", "CLOSED"] and info.get('postMarketPrice'):
                    display_price = info['postMarketPrice']
                    price_type = "POST"
                    post_market_change = display_price - regular_price
                    post_market_percent = (post_market_change / regular_price) * 100 if regular_price else 0
                    market_change_str = f" ({post_market_change:+.2f}, {post_market_percent:+.2f}%)"
                
                hist.ta.ema(length=10, append=True)
                hist.ta.ema(length=50, append=True)
                hist.ta.rsi(length=14, append=True)
                hist.ta.macd(fast=12, slow=26, signal=9, append=True)
                hist.ta.atr(length=14, append=True)
                latest = hist.iloc[-1]
                
                stock_data = {
                    "ticker": symbol,
                    "price": f"{display_price:.2f}",
                    "priceType": price_type,
                    "marketChangeStr": market_change_str,
                    "change": f"{change:+.2f}",
                    "changePercent": f"{change_percent:+.2f}%",
                    "ohl": f"{info.get('open', 0):.2f}/{info.get('dayHigh', 0):.2f}/{info.get('dayLow', 0):.2f}",
                    "volume": format_volume(info.get('volume', 0)),
                    "rsi": f"{latest.get('RSI_14', 0):.2f}",
                    "macdHist": f"{latest.get('MACDh_12_26_9', 0):.2f}",
                    "ema_10_50": f"{latest.get('EMA_10', 0):.2f} / {latest.get('EMA_50', 0):.2f}",
                    "rank": get_rank(latest.get('RSI_14', 0)),
                    "action": "Consider" if get_rank(latest.get('RSI_14', 0)) in ['Good', 'Fair'] else "Watch",
                    "riskNotes": get_risk_note(),
                    "atrStop": f"{(regular_price - (2 * latest.get('ATRr_14', 0))):.2f}",
                    "profitTarget": f"{(regular_price + (2 * latest.get('ATRr_14', 0))):.2f} - {(regular_price + (3 * latest.get('ATRr_14', 0))):.2f}"
                }
                all_data.append(stock_data)
                logging.info(f"Successfully processed and added {symbol}.") # NEW
            except Exception as e:
                logging.error(f"An unexpected error occurred for {symbol}: {e}")
        
        logging.info(f"Finished processing. Found {len(all_data)} stocks to return.") # NEW
        top_10_stocks = sorted(all_data, key=lambda x: float(x['change']), reverse=True)[:10]

        api_cache["data"] = top_10_stocks
        api_cache["last_updated"] = datetime.utcnow()

        return jsonify(top_10_stocks)

    except Exception as e:
        logging.error(f"A critical error occurred in get_top_gainers_data: {e}")
        if api_cache["data"]:
            logging.warning("Returning stale data due to a critical error.")
            return jsonify(api_cache["data"])
        return jsonify({"error": "Could not fetch data and no cache is available."}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)

