import os
import google.generativeai as genai

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("Error: GEMINI_API_KEY environment variable not set.")
    exit(1)

genai.configure(api_key=api_key)

try:
    # Use a lightweight model for testing
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content("Say 'API Key Working'")
    print(f"Response: {response.text}")
    print("Success: API Key is working!")
except Exception as e:
    print(f"Error: {e}")
    exit(1)
