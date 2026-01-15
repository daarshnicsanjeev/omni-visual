"""Script to list available Gemini models."""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from google import genai

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("ERROR: GOOGLE_API_KEY not set in environment")
    sys.exit(1)

client = genai.Client(api_key=api_key)

print("Fetching available models...")
print("=" * 50)

try:
    models = list(client.models.list())
    gemini_models = [m.name for m in models if "gemini" in m.name.lower()]
    
    print(f"Found {len(gemini_models)} Gemini models:\n")
    
    # Filter for Gemini 3 models
    gemini3 = [m for m in gemini_models if "gemini-3" in m.lower()]
    if gemini3:
        print("Gemini 3 models:")
        for m in gemini3:
            print(f"  {m}")
        print()
    
    # Filter for Gemini 2 models  
    gemini2 = [m for m in gemini_models if "gemini-2" in m.lower()]
    if gemini2:
        print("Gemini 2 models:")
        for m in gemini2:
            print(f"  {m}")

except Exception as e:
    print(f"Error: {e}")
