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
CACHE_DURATION = timedelta(minutes=15)

# --- Gemini API Configuration ---
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={GEMINI_API_KEY}"

def get_gemini_analysis():
    """Calls the Gemini API with search grounding to get stock analysis."""
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API key is not configured.")

    est = pytz.timezone('US/Eastern')
    current_date = datetime.now(est).strftime('%Y-%m-%d')
    
    system_prompt = """
    You are a financial data API. Your task is to provide a detailed, real-time analysis for the top 10 trending day-gainer stocks.
    - You MUST use Google Search to get the latest, most accurate data for the current trading day.
    - First, find the top 100 day gainers from the DOW, Nasdaq, and S&P 500.
    - Then, for the TOP 10 of that list, provide the following details for each stock: Ticker, Price, Change, O/H/L, Volume, RSI (14), MACD HIST, EMA (10/50), Rank (Poor, Fair, Good, Very Good, Excellent), Action (Buy/Hold/Sell with target), a primary Risk Note with a brief reason, ATR Stop, and a Profit Target Zone.
    - Your entire response MUST be a single, valid JSON array of objects.
    - Do NOT include any introductory text, concluding text, markdown formatting like ```json, or any other characters outside of the main JSON array. The response must be parsable JSON and nothing else.
    """
    
    user_prompt = f"Provide the top 10 stock gainer analysis for today, {current_date}."
    
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            # This is the fix: We are removing the unsupported "response_mime_type"
            # and relying on the system prompt to ensure the output is valid JSON.
            "temperature": 0.5,
            "max_output_tokens": 8192,
        }
    }
    
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, data=json.dumps(payload), timeout=180)
        response.raise_for_status()
        
        response_json = response.json()
        # The text part of the response should now be a well-formatted JSON string
        json_string = response_json['candidates'][0]['content']['parts'][0]['text']
        
        return json.loads(json_string)

    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err}")
        logging.error(f"Error Response Body: {http_err.response.text}")
        raise

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
        
        api_cache["data"] = analysis_data
        api_cache["last_updated"] = datetime.utcnow()
        
        logging.info(f"Successfully processed and cached analysis for {len(analysis_data)} stocks.")
        return jsonify(analysis_data)

    except Exception as e:
        logging.error(f"A major error occurred while calling Gemini API: {e}")
        logging.error(traceback.format_exc())
        if api_cache["data"]:
            return jsonify(api_cache["data"])
        return jsonify({"error": "Could not fetch data from the AI model."}), 500


@app.route('/api/market-status')
def get_market_status():
    try:
        est = pytz.timezone('US/Eastern')
        current_time = datetime.now(est)
        current_time_str = current_time.strftime('%I:%M:%S %p EST')
        if current_time.weekday() < 5:
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

