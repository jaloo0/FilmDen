import requests
import json

# --- Configuration ---
OPENROUTER_API_KEY = "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"
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