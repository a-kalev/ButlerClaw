from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
from brain import understand_task, pick_best, build_greeting, extract_profile_updates, trim_history
from search import search_kroger, get_nearby_stores
from memory import load_profile, save_profile
import httpx
from urllib.parse import urlencode
import requests
import os

app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    zip_code: str = "10001"
    user_id: str = "anonymous"
    history: List[Dict] = []

class StoreSelectRequest(BaseModel):
    user_id: str
    zip_code: str
    message: str
    history: List[Dict] = []
    location_id: str
    store_name: str
    store_city: str
    store_state: str

async def run_search(message, zip_code, user_id, history, location_id, store):
    """Core search logic — reused by both /chat and /select-store."""
    profile = load_profile(user_id)
    history = trim_history(history)

    items = understand_task(message, history, profile)

    recommendations = []
    for term in items:
        data = search_kroger(term, zip_code=zip_code, location_id=location_id)
        best = pick_best(message, term, data["results"], profile)
        if best:
            recommendations.append({"category": term, "product": best})

    greeting = build_greeting(message, history, profile)

    # Silently update profile
    new_history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": greeting}
    ]
    updated_profile = extract_profile_updates(new_history, profile)
    updated_profile["zip_code"] = zip_code
    save_profile(user_id, updated_profile)

    return {
        "greeting": greeting,
        "store": store,
        "recommendations": recommendations
    }

@app.post("/chat")
async def chat(req: ChatRequest):
    profile = load_profile(req.user_id)

    # Use saved zip if none provided
    zip_code = req.zip_code
    if zip_code == "10001" and profile.get("zip_code"):
        zip_code = profile["zip_code"]

    # If no saved store — return store picker
    if not profile.get("location_id"):
        stores = get_nearby_stores(zip_code)
        return {
            "stores": stores,
            "zip_code": zip_code
        }

    # Has saved store — run search directly
    store = {
        "locationId": profile["location_id"],
        "name": profile.get("store_name", "Kroger"),
        "city": profile.get("store_city", ""),
        "state": profile.get("store_state", "")
    }
    return await run_search(
        req.message, zip_code, req.user_id,
        req.history, profile["location_id"], store
    )

@app.post("/select-store")
async def select_store(req: StoreSelectRequest):
    # Save store to profile
    profile = load_profile(req.user_id)
    profile["location_id"] = req.location_id
    profile["store_name"] = req.store_name
    profile["store_city"] = req.store_city
    profile["store_state"] = req.store_state
    profile["zip_code"] = req.zip_code
    save_profile(req.user_id, profile)

    store = {
        "locationId": req.location_id,
        "name": req.store_name,
        "city": req.store_city,
        "state": req.store_state
    }

    # Immediately run the original search
    return await run_search(
        req.message, req.zip_code, req.user_id,
        req.history, req.location_id, store
    )

@app.get("/get-profile")
async def get_profile(user_id: str = "anonymous"):
    profile = load_profile(user_id)
    return {"zip_code": profile.get("zip_code")}

@app.get("/")
async def root():
    return FileResponse("ui.html")

@app.get("/manifest.json")
async def manifest():
    return FileResponse("/home/ubuntu/butlerclaw2/manifest.json")

@app.get("/icon.png")
async def icon():
    return FileResponse("/home/ubuntu/butlerclaw2/icon.png")

class AddToCartRequest(BaseModel):
    user_id: str
    upc: str
    product_name: str
    quantity: int = 1

@app.get("/kroger-login")
async def kroger_login(user_id: str, upc: str, product_name: str):
    # Save pending item to profile so we can add it after OAuth
    profile = load_profile(user_id)
    profile["pending_upc"] = upc
    profile["pending_product_name"] = product_name
    save_profile(user_id, profile)

    params = {
        "client_id": os.getenv("KROGER_CLIENT_ID"),
        "redirect_uri": "https://butlerclaw.duckdns.org/kroger-callback",
        "response_type": "code",
        "scope": "cart.basic:write",
        "state": user_id  # pass user_id through OAuth flow
    }
    kroger_auth_url = "https://api.kroger.com/v1/connect/oauth2/authorize?" + urlencode(params)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(kroger_auth_url)

@app.get("/kroger-callback")
async def kroger_callback(code: str, state: str = "anonymous"):
    from fastapi.responses import RedirectResponse
    import base64

    user_id = state
    profile = load_profile(user_id)

    # Exchange code for token
    client_id = os.getenv("KROGER_CLIENT_ID")
    client_secret = os.getenv("KROGER_CLIENT_SECRET")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    token_response = requests.post(
        "https://api.kroger.com/v1/connect/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}"
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://butlerclaw.duckdns.org/kroger-callback"
        }
    )

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    if not access_token:
        return RedirectResponse("/?error=auth_failed")

    # Save tokens to profile
    profile["kroger_access_token"] = access_token
    profile["kroger_refresh_token"] = refresh_token
    save_profile(user_id, profile)

    # Add the pending item if there is one
    pending_upc = profile.get("pending_upc")
    pending_name = profile.get("pending_product_name", "item")
    if pending_upc:
        from search import add_to_cart
        status, _ = add_to_cart(
            upc=pending_upc,
            quantity=1,
            location_id=profile.get("location_id"),
            access_token=access_token
        )
        # Clear pending item
        profile.pop("pending_upc", None)
        profile.pop("pending_product_name", None)
        save_profile(user_id, profile)

        if status in (200, 201, 204):
            return RedirectResponse(f"/?cart_success={pending_name}")
        else:
            return RedirectResponse(f"/?cart_error=add_failed")

    return RedirectResponse("/")

@app.post("/add-to-cart")
async def add_to_cart_endpoint(req: AddToCartRequest):
    from search import add_to_cart
    profile = load_profile(req.user_id)
    access_token = profile.get("kroger_access_token")

    if not access_token:
        return {"status": "need_auth"}

    status, response_text = add_to_cart(
        upc=req.upc,
        quantity=req.quantity,
        location_id=profile.get("location_id"),
        access_token=access_token
    )

    if status in (200, 201, 204):
        return {"status": "success"}
    elif status == 401:
        # Token expired — clear it, tell UI to re-auth
        profile.pop("kroger_access_token", None)
        save_profile(req.user_id, profile)
        return {"status": "need_auth"}
    else:
        return {"status": "error", "detail": response_text}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8767)
