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
import time # Import the time module
import traceback # Import traceback for detailed error logging

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

# --- Helper Functions ---

def safe_format_float(value):
    """Safely formats a value to a float string or returns 'N/A'."""
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return "N/A"

def format_volume(volume):
    if volume is None: return "N/A"
    try:
        volume = float(volume)
        if volume >= 1_000_000: return f"{volume / 1_000_000:.2f}M"
        if volume >= 1_000: return f"{volume / 1_000:.2f}K"
        return str(int(volume))
    except (ValueError, TypeError):
        return "N/A"

def get_rank(rsi):
    if rsi is None: return 'N/A'
    try:
        rsi = float(rsi)
        if rsi > 75: return 'Excellent'
        if rsi > 65: return 'Very Good'
        if rsi > 55: return 'Good'
        return 'Fair'
    except (ValueError, TypeError):
        return 'N/A'

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

# --- Market Status Endpoint ---
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

# --- Main API Endpoint ---
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
            logging.info(f"--- Processing symbol: {symbol} ---")
            try:
                # Fetch data for a single ticker
                ticker_data = yf.Ticker(symbol)
                info = ticker_data.info
                hist = ticker_data.history(period="3mo")

                if hist.empty or not info or 'regularMarketPrice' not in info:
                    logging.warning(f"Skipping {symbol}: History or info data was empty or invalid.")
                    continue

                regular_price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')
                prev_close = info.get('previousClose')

                if regular_price is None or prev_close is None:
                    logging.warning(f"Skipping {symbol}: Missing critical price data.")
                    continue

                change = regular_price - prev_close
                if change <= 0:
                    logging.info(f"Skipping {symbol}: Not a gainer (change: {change:.2f}).")
                    continue
                
                change_percent = (change / prev_close) * 100

                # --- Calculate indicators ---
                hist.ta.ema(length=10, append=True)
                hist.ta.ema(length=50, append=True)
                hist.ta.rsi(length=14, append=True)
                hist.ta.macd(fast=12, slow=26, signal=9, append=True)
                hist.ta.atr(length=14, append=True)
                latest = hist.iloc[-1]
                
                stock_data = {
                    "ticker": symbol,
                    "price": safe_format_float(info.get('regularMarketPrice')),
                    "change": f"{change:+.2f}",
                    "changePercent": f"{change_percent:+.2f}%",
                    "volume": format_volume(info.get('volume')),
                    "rsi": safe_format_float(latest.get('RSI_14')),
                    "rank": get_rank(latest.get('RSI_14'))
                }
                all_data.append(stock_data)
                logging.info(f"Successfully processed and added {symbol}.")

            except Exception:
                logging.error(f"An unexpected error occurred for {symbol}:")
                logging.error(traceback.format_exc()) # Log the full error
            
            # --- IMPORTANT: Wait for 1 second to avoid being rate-limited ---
            logging.info("Waiting for 1 second...")
            time.sleep(1)
        
        top_10_gainers = sorted(all_data, key=lambda x: float(x['change']), reverse=True)[:10]

        api_cache["data"] = top_10_gainers
        api_cache["last_updated"] = datetime.utcnow()
        return jsonify(top_10_gainers)

    except Exception as e:
        logging.error(f"A major error occurred in get_top_gainers_data: {e}")
        if api_cache["data"]:
            return jsonify(api_cache["data"])
        return jsonify({"error": "Could not fetch data and no cache is available."}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)

