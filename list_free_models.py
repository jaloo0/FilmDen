import requests
import json

import os

# --- Load Environment Variables ---
def load_env():
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    key, val = line.strip().split("=", 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")

load_env()

# --- Configuration ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_HOST = "openrouter.ai"

# Get list of models
url = f"https://{OPENROUTER_HOST}/api/v1/models"
headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json"
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    # Extract free models
    free_models = []
    for model in data.get('data', []):
        model_id = model.get('id', '')
        if ':free' in model_id:
            free_models.append(model_id)
    
    print("Free models available:")
    for model in sorted(free_models):
        print(f"  {model}")
        
except Exception as e:
    print(f"Error fetching models: {e}")