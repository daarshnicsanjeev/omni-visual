import socket
import httpx
import os
from dotenv import load_dotenv

# Load from the correct .env file location
env_path = r"c:\Users\daars\.gemini\antigravity\scratch\omni-visual\.env"
load_dotenv(env_path)

print(f"Loading env from: {env_path}")
api_key = os.getenv('GOOGLE_MAPS_API_KEY')
print(f"Key loaded: {'Yes' if api_key else 'No'}")

try:
    print("Resolving maps.googleapis.com...")
    ip = socket.gethostbyname("maps.googleapis.com")
    print(f"Resolved to: {ip}")
except Exception as e:
    print(f"DNS Resolution failed: {e}")

try:
    print("Testing HTTPS connection...")
    # Use the actual key if available to get a real 200/400 response, otherwise dummy
    key_to_use = api_key if api_key else "TEST"
    
    # Simple static map request
    params = {
        "key": key_to_use, 
        "center": "0,0", 
        "zoom": "1", 
        "size": "1x1"
    }
    
    resp = httpx.get("https://maps.googleapis.com/maps/api/staticmap", params=params)
    print(f"HTTP Status: {resp.status_code}")
    if resp.status_code == 200:
        print("Success: Connected and retrieved image.")
    elif resp.status_code == 403:
        print("Success: Connected (API key likely invalid or billing issue, but network works).")
    else:
        print(f"Response: {resp.text[:200]}")
        
except Exception as e:
    print(f"HTTP Request failed: {e}")
