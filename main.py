from flask import Flask, jsonify
from flask_cors import CORS
import logging
from datetime import datetime, timedelta
import pytz
import os
import traceback
from polygon import RESTClient

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
CORS(app)

# --- API Key Setup ---
# CRUCIAL: Reads the API key from the environment variables you set in Render.
API_KEY = os.getenv("POLYGON_API_KEY")
if not API_KEY:
    logging.error("FATAL: POLYGON_API_KEY environment variable not set.")
    # This will cause the app to fail gracefully if the key is missing.

# Initialize the Polygon client
client = RESTClient(API_KEY)

# --- Cache Setup ---
api_cache = {
    "data": None,
    "last_updated": None
}
CACHE_DURATION = timedelta(minutes=5)

# --- Helper Functions ---
def format_volume(volume):
    if volume is None: return "N/A"
    try:
        volume = float(volume)
        if volume >= 1_000_000: return f"{volume / 1_000_000:.2f}M"
        if volume >= 1_000: return f"{volume / 1_000:.2f}K"
        return str(int(volume))
    except (ValueError, TypeError):
        return "N/A"

# --- Market Status Endpoint ---
@app.route('/api/market-status')
def get_market_status():
    if not API_KEY:
        return jsonify({"status": "API key not configured", "time": ""}), 500
    try:
        market_status = client.get_market_status()
        status_description = market_status.market.upper()
        
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

    logging.info("Cache is stale or empty. Fetching new data from Polygon.io.")
    
    if not API_KEY:
        return jsonify({"error": "API key is not configured on the server."}), 500
        
    try:
        # --- CORRECTED FUNCTION CALL ---
        # Added the required 'market_type' argument.
        gainers = client.get_snapshot_direction(market_type="stocks", direction="gainers")

        all_data = []
        if hasattr(gainers, 'tickers') and gainers.tickers:
            for stock in gainers.tickers:
                stock_data = {
                    "ticker": stock.ticker,
                    "price": f"{stock.last_trade.price:.2f}",
                    "change": f"{stock.todays_change:+.2f}",
                    "changePercent": f"{stock.todays_change_percent:+.2f}%",
                    "volume": format_volume(stock.day.volume),
                    "rsi": "N/A", 
                    "rank": "N/A"
                }
                all_data.append(stock_data)
        
        logging.info(f"Successfully processed {len(all_data)} gainers.")
        
        api_cache["data"] = all_data
        api_cache["last_updated"] = datetime.utcnow()
        return jsonify(all_data)

    except Exception as e:
        logging.error(f"A major error occurred: {e}")
        logging.error(traceback.format_exc())
        if api_cache["data"]:
            return jsonify(api_cache["data"])
        return jsonify({"error": "Could not fetch data from Polygon.io."}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)

