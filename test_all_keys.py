import os
import json
import google.generativeai as genai
from pathlib import Path

def get_keys():
    keys = set()
    
    # 1. Env vars
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key:
        keys.add(env_key)
    
    env_keys = os.getenv("GEMINI_API_KEYS")
    if env_keys:
        for k in env_keys.split(","):
            if k.strip():
                keys.add(k.strip())
                
    # 2. Config files
    config_dir = Path("config")
    for filename in ["user_settings.json", "cli_settings.json"]:
        p = config_dir / filename
        if p.exists():
            try:
                with open(p, "r") as f:
                    data = json.load(f)
                    if data.get("gemini_api_key"):
                        keys.add(data["gemini_api_key"])
                    if data.get("gemini_api_keys"):
                        for k in data["gemini_api_keys"]:
                            keys.add(k)
            except:
                pass
    return sorted(list(keys))

def test_key(key):
    genai.configure(api_key=key)
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content("ping")
        return True, "Valid"
    except Exception as e:
        return False, str(e)

all_keys = get_keys()
print(f"Found {len(all_keys)} unique keys to test.\n")

for i, key in enumerate(all_keys, 1):
    print(f"[{i}/{len(all_keys)}] Testing key: {key[:10]}...{key[-5:]}")
    success, msg = test_key(key)
    if success:
        print(f"  Result: ✅ VALID")
    else:
        # Check for specific error types
        if "API key expired" in msg:
            print(f"  Result: ❌ EXPIRED")
        elif "API_KEY_INVALID" in msg:
            print(f"  Result: ❌ INVALID")
        else:
            print(f"  Result: ❌ ERROR: {msg[:100]}...")
    print("-" * 20)
