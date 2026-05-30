import requests
import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("ADOBE_CLIENT_ID")
CLIENT_SECRET = os.getenv("ADOBE_CLIENT_SECRET")
REDIRECT_URI = "https://localhost/" # Common default for local dev
SCOPES = "lr_partner_apis lr_partner_rendition_apis openid AdobeID offline_access"

def get_auth_url():
    url = (
        f"https://ims-na1.adobelogin.com/ims/authorize/v2"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={SCOPES}"
        f"&response_type=code"
    )
    return url

def get_tokens(auth_code):
    url = "https://ims-na1.adobelogin.com/ims/token/v3"
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": auth_code,
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: ADOBE_CLIENT_ID and ADOBE_CLIENT_SECRET must be set in .env")
        exit(1)

    print("Step 1: Open this URL in your browser and log in:")
    print(get_auth_url())
    print("\nStep 2: After logging in, you will be redirected to localhost.")
    print("Copy the 'code' parameter from the URL (e.g., https://localhost/?code=YOUR_CODE_HERE)")
    
    code = input("\nEnter the code: ").strip()
    
    try:
        tokens = get_tokens(code)
        print("\nSuccess! Add these to your .env file:")
        print(f"ADOBE_REFRESH_TOKEN={tokens['refresh_token']}")
    except Exception as e:
        print(f"\nError getting tokens: {e}")
