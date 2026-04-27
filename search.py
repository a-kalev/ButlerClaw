import requests
import os
from dotenv import load_dotenv

load_dotenv()

KROGER_CLIENT_ID = os.getenv("KROGER_CLIENT_ID")
KROGER_CLIENT_SECRET = os.getenv("KROGER_CLIENT_SECRET")

def get_kroger_token():
    response = requests.post(
        "https://api.kroger.com/v1/connect/oauth2/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": "product.compact"},
        auth=(KROGER_CLIENT_ID, KROGER_CLIENT_SECRET)
    )
    return response.json().get("access_token")

def get_nearest_store(zip_code, token):
    response = requests.get(
        "https://api.kroger.com/v1/locations",
        headers={"Authorization": f"Bearer {token}"},
        params={"filter.zipCode.near": zip_code, "filter.limit": 1}
    )
    locations = response.json().get("data", [])
    if locations:
        loc = locations[0]
        address = loc.get("address", {})
        return {
            "locationId": loc.get("locationId"),
            "name": loc.get("name", "Kroger"),
            "city": address.get("city", ""),
            "state": address.get("state", ""),
        }
    return {"locationId": None, "name": "Kroger", "city": "", "state": ""}

def get_front_image(images):
    for img in images:
        if img.get("perspective") == "front":
            for size in img.get("sizes", []):
                if size.get("size") == "thumbnail":
                    return size.get("url")
    return None

def search_kroger(term, zip_code="10001", limit=5, location_id=None):
    token = get_kroger_token()
    store = get_nearest_store(zip_code, token)
    if not location_id:
        location_id = store["locationId"]
    params = {"filter.term": term, "filter.limit": limit}
    if location_id:
        params["filter.locationId"] = location_id
    response = requests.get(
        "https://api.kroger.com/v1/products",
        headers={"Authorization": f"Bearer {token}"},
        params=params
    )
    results = []
    for item in response.json().get("data", []):
        prices = item.get("items", [{}])[0].get("price", {})
        page_uri = item.get("productPageURI", "")
        results.append({
            "name": item.get("description", "Unknown"),
            "brand": item.get("brand", ""),
            "regular_price": prices.get("regular", None),
            "sale_price": prices.get("promo", None),
            "url": f"https://www.kroger.com{page_uri}" if page_uri else None,
            "image": get_front_image(item.get("images", [])),
            "upc": item.get("upc", ""),
        })
    return {"store": store, "results": results}

def get_nearby_stores(zip_code, limit=3):
    token = get_kroger_token()
    response = requests.get(
        "https://api.kroger.com/v1/locations",
        headers={"Authorization": f"Bearer {token}"},
        params={"filter.zipCode.near": zip_code, "filter.limit": limit}
    )
    stores = []
    for loc in response.json().get("data", []):
        addr = loc.get("address", {})
        stores.append({
            "locationId": loc.get("locationId"),
            "name": loc.get("name"),
            "address": addr.get("addressLine1", ""),
            "city": addr.get("city", ""),
            "state": addr.get("state", ""),
        })
    return stores
def add_to_cart(upc, quantity=1, location_id=None, access_token=None):
    """Add item to Kroger cart using user OAuth token."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    body = {
        "items": [{
            "upc": upc,
            "quantity": quantity,
            "modality": "PICKUP"
        }]
    }
    if location_id:
        body["items"][0]["fulfillmentType"] = "PICKUP"
    response = requests.put(
        "https://api.kroger.com/v1/cart/add",
        headers=headers,
        json=body
    )
    return response.status_code, response.text
