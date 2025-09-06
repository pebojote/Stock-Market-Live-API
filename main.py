from flask import Flask, jsonify
from flask_cors import CORS
import logging
from datetime import datetime, timedelta
import pytz
import os
import traceback
import requests
import json

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
CORS(app)

# --- API Key Setup ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logging.error("FATAL: GEMINI_API_KEY environment variable not set.")

# --- Cache Setup ---
api_cache = {
    "data": None,
    "last_updated": None
}
CACHE_DURATION = timedelta(minutes=15) # LLM calls can be slow, cache for longer

# --- Gemini API Configuration ---
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={GEMINI_API_KEY}"

# --- JSON Schema for Gemini's Output ---
# This forces the AI to return data in a structured format we can use.
STOCK_ANALYSIS_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "ticker": {"type": "STRING"},
            "price": {"type": "STRING"},
            "change": {"type": "STRING"},
            "ohl": {"type": "STRING", "description": "Open/High/Low prices for the day, formatted as 'O/H/L'"},
            "volume": {"type": "STRING"},
            "rsi_14": {"type": "STRING", "description": "14-day Relative Strength Index"},
            "macd_hist": {"type": "STRING", "description": "MACD Histogram value"},
            "ema_10_50": {"type": "STRING", "description": "10-day and 50-day Exponential Moving Averages, formatted as 'EMA10 / EMA50'"},
            "rank": {"type": "STRING", "enum": ["Poor", "Fair", "Good", "Very Good", "Excellent"]},
            "action": {"type": "STRING", "description": "Suggested action: Buy, Hold, Watch, or Sell, including a target price or percentage."},
            "risk_notes": {
                "type": "OBJECT",
                "properties": {
                    "factor": {"type": "STRING", "description": "The most likely risk factor."},
                    "reason": {"type": "STRING", "description": "A brief explanation of why this is a risk."}
                }
            },
            "atr_stop": {"type": "STRING", "description": "Calculated ATR Stop Loss price"},
            "profit_target_zone": {"type": "STRING", "description": "A calculated price range for taking profits."}
        },
        "required": ["ticker", "price", "change", "ohl", "volume", "rsi_14", "macd_hist", "ema_10_50", "rank", "action", "risk_notes", "atr_stop", "profit_target_zone"]
    }
}


def get_gemini_analysis():
    """Calls the Gemini API with search grounding and a JSON schema to get stock analysis."""
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API key is not configured.")

    est = pytz.timezone('US/Eastern')
    current_date = datetime.now(est).strftime('%Y-%m-%d')
    
    system_prompt = """
    You are an expert financial analyst. Your task is to provide detailed, real-time analysis for the top 10 trending day-gainer stocks.
    You MUST use Google Search to get the latest, most accurate data for the current trading day.
    Perform all calculations for technical indicators based on the real-time data you find.
    Provide a concise, expert opinion for the 'action' and 'risk_notes' fields.
    You must strictly adhere to the provided JSON schema for your response.
    """
    
    user_prompt = f"""
    Based on the latest pre-market, regular, or after-hours trading data for today, {current_date}, please identify the top 100 trending day gainers from the Dow Jones, Nasdaq Composite, and S&P 500.
    From that list, provide a detailed analysis for the top 10 stocks.
    I need the Ticker, current Price, day's Change, Open/High/Low (O/H/L), Volume, 14-day RSI, MACD Histogram, 10-day/50-day EMA, Rank, a recommended Action, the most likely short-term Risk Note with a brief reason, the ATR Stop, and a Profit Target Zone.
    """
    
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "responseSchema": STOCK_ANALYSIS_SCHEMA,
            "temperature": 0.5
        }
    }
    
    headers = {'Content-Type': 'application/json'}
    response = requests.post(GEMINI_API_URL, headers=headers, data=json.dumps(payload), timeout=120)
    response.raise_for_status() # Will raise an exception for HTTP errors
    
    response_json = response.json()
    # Extract the JSON string from the response and parse it
    json_string = response_json['candidates'][0]['content']['parts'][0]['text']
    return json.loads(json_string)


@app.route('/api/top-gainers')
def get_top_gainers_data():
    global api_cache
    if api_cache["data"] and datetime.utcnow() - api_cache["last_updated"] < CACHE_DURATION:
        logging.info("Returning data from cache.")
        return jsonify(api_cache["data"])

    logging.info("Cache is stale. Fetching new analysis from Gemini API.")
    
    if not GEMINI_API_KEY:
        return jsonify({"error": "API key is not configured on the server."}), 500
        
    try:
        analysis_data = get_gemini_analysis()
        
        # The data from Gemini is already the final list of 10
        api_cache["data"] = analysis_data
        api_cache["last_updated"] = datetime.utcnow()
        
        logging.info(f"Successfully processed and cached analysis for {len(analysis_data)} stocks.")
        return jsonify(analysis_data)

    except Exception as e:
        logging.error(f"A major error occurred while calling Gemini API: {e}")
        logging.error(traceback.format_exc())
        # Return stale data if available, otherwise return a clear error
        if api_cache["data"]:
            return jsonify(api_cache["data"])
        return jsonify({"error": "Could not fetch data from the AI model."}), 500


@app.route('/api/market-status')
def get_market_status():
    """
    Note: This is a simplified market status.
    A more robust solution would also use an official API for this.
    """
    try:
        est = pytz.timezone('US/Eastern')
        current_time = datetime.now(est)
        current_time_str = current_time.strftime('%I:%M:%S %p EST')
        # Simple check based on time and weekday
        if current_time.weekday() < 5: # Monday to Friday
            if current_time.hour >= 16 or current_time.hour < 4:
                status = "CLOSED (AFTER-HOURS TRADING MAY OCCUR)"
            elif current_time.hour < 9 or (current_time.hour == 9 and current_time.minute < 30):
                status = "PRE-MARKET"
            else:
                status = "REGULAR HOURS"
        else:
            status = "CLOSED"
        
        return jsonify({"status": f"Market is currently {status}", "time": current_time_str})
    except Exception as e:
        logging.error(f"Could not fetch market status: {e}")
        return jsonify({"status": "Market status is currently unavailable", "time": ""}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)

