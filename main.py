from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
CORS(app)

# --- Helper Functions ---

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
        {'title': 'Profit-Taking', 'reason': 'High RSI suggests a pullback as investors lock in gains.'},
        {'title': 'Overextended Technicals', 'reason': 'Price has moved too far, too fast, risking a reversal.'},
        {'title': 'High Expectations', 'reason': 'Priced for perfection; any disappointment could cause a drop.'}
    ]
    import random
    return random.choice(notes)

def get_dynamic_tickers():
    try:
        url = "https://finance.yahoo.com/most-active"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', {'class': 'W(100%)'})
        tickers = [link.text for link in table.find_all('a', {'data-test': 'quoteLink'})[:25]]
        if not tickers: raise ValueError("Could not find any tickers.")
        logging.info(f"Dynamically fetched most active tickers: {tickers}")
        return tickers
    except Exception as e:
        logging.error(f"Failed to scrape tickers: {e}")
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
    try:
        active_tickers = get_dynamic_tickers()
        tickers = yf.Tickers(' '.join(active_tickers))
        all_data = []

        for symbol in active_tickers:
            try:
                info = tickers.tickers[symbol].info
                hist = tickers.tickers[symbol].history(period="3mo")
                if hist.empty: continue

                # --- NEW ACCURACY LOGIC ---
                market_state = info.get('marketState', 'UNKNOWN').upper()
                price_type = "REGULAR"
                
                # Base values from the regular session
                regular_price = info.get('regularMarketPrice', info.get('currentPrice', 0))
                prev_close = info.get('previousClose', 1)
                
                # Main change is always based on the regular session
                change = regular_price - prev_close
                if change <= 0: continue # Only process gainers
                change_percent = (change / prev_close) * 100 if prev_close else 0

                # Determine the final price to display and calculate market-specific change
                display_price = regular_price
                market_change_str = "" # Extra string for pre/post market changes

                if market_state in ["PRE", "PREPRE"] and 'preMarketPrice' in info and info['preMarketPrice']:
                    display_price = info['preMarketPrice']
                    price_type = "PRE"
                    pre_market_change = display_price - regular_price
                    pre_market_percent = (pre_market_change / regular_price) * 100 if regular_price else 0
                    market_change_str = f" ({pre_market_change:+.2f}, {pre_market_percent:+.2f}%)"
                elif market_state in ["POST", "POSTPOST", "CLOSED"] and 'postMarketPrice' in info and info['postMarketPrice']:
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
                    "marketChangeStr": market_change_str, # New field for market-specific change
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
            except Exception as e:
                logging.error(f"Could not process data for {symbol}: {e}")
        
        top_10_gainers = sorted(all_data, key=lambda x: float(x['change']), reverse=True)[:10]
        return jsonify(top_10_gainers)

    except Exception as e:
        logging.error(f"An error occurred in get_top_gainers_data: {e}")
        return jsonify({"error": "Could not fetch data from Yahoo Finance."}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)

