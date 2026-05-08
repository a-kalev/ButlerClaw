from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
from contextlib import asynccontextmanager
from brain import understand_task, pick_best, build_greeting, extract_profile_updates, trim_history
from search import search_kroger, get_nearby_stores, refresh_kroger_token
from memory import (load_profile, save_profile, save_job, load_job, list_jobs,
                    get_usuals_products, add_usual_product, remove_usual_product,
                    get_unusuals, add_unusual, remove_unusual, clear_unusuals)
from claw import run_job, TASK_REGISTRY
from push import send_push, get_public_key
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import httpx
from urllib.parse import urlencode
import requests
import uuid as _uuid
import os

scheduler = BackgroundScheduler()

def run_daily_digest():
    """Runs at 18:00 UTC daily. Populated when sale_hunter and other
    background tasks are built."""
    print("[scheduler] Daily digest sweep running")

@asynccontextmanager
async def lifespan(app_instance):
    scheduler.add_job(
        run_daily_digest,
        CronTrigger(hour=18, minute=0),
        id="daily_digest",
        replace_existing=True
    )
    scheduler.start()
    print("[scheduler] APScheduler started")
    yield
    scheduler.shutdown()
    print("[scheduler] APScheduler stopped")

app = FastAPI(lifespan=lifespan)

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

class ContactRequest(BaseModel):
    user_id: str = "anonymous"
    message: str
    email: str = ""

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
    return FileResponse(os.path.join(os.path.dirname(__file__), "manifest.json"))

@app.get("/icon.png")
async def icon():
    return FileResponse(os.path.join(os.path.dirname(__file__), "icon.png"))

@app.get("/icon2.png")
async def icon2():
    return FileResponse(os.path.join(os.path.dirname(__file__), "icon2.png"))

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
        refresh_token = profile.get("kroger_refresh_token")
        if refresh_token:
            new_access, new_refresh = refresh_kroger_token(refresh_token)
            if new_access:
                profile["kroger_access_token"] = new_access
                if new_refresh:
                    profile["kroger_refresh_token"] = new_refresh
                save_profile(req.user_id, profile)
                access_token = new_access
            else:
                return {"status": "need_auth"}
        else:
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
        # Token expired — try refresh before asking user to re-auth
        refresh_token = profile.get("kroger_refresh_token")
        if refresh_token:
            new_access, new_refresh = refresh_kroger_token(refresh_token)
            if new_access:
                # Save new tokens and retry
                profile["kroger_access_token"] = new_access
                if new_refresh:
                    profile["kroger_refresh_token"] = new_refresh
                save_profile(req.user_id, profile)
                # Retry the cart add with new token
                status2, response_text2 = add_to_cart(
                    upc=req.upc,
                    quantity=req.quantity,
                    location_id=profile.get("location_id"),
                    access_token=new_access
                )
                if status2 in (200, 201, 204):
                    return {"status": "success"}
        # Refresh failed or no refresh token — ask user to re-auth
        profile.pop("kroger_access_token", None)
        save_profile(req.user_id, profile)
        return {"status": "need_auth"}
    else:
        return {"status": "error", "detail": response_text}

@app.post("/contact")
async def contact(req: ContactRequest):
    from memory import save_message
    if not req.message.strip():
        return {"status": "error", "detail": "Message cannot be empty"}
    save_message(
        user_id=req.user_id,
        message=req.message.strip(),
        email=req.email.strip() if req.email.strip() else None
    )
    return {"status": "success"}


# ── Claw Engine Endpoints ──────────────────────────────────────

class ClawRunRequest(BaseModel):
    user_id: str
    task_type: str
    payload: dict = {}

class PushSubscribeRequest(BaseModel):
    user_id: str
    subscription: dict
    timezone: str = "UTC"

@app.post("/claw/run")
async def claw_run(req: ClawRunRequest):
    if req.task_type not in TASK_REGISTRY:
        return {"status": "error", "detail": f"Unknown task: {req.task_type}"}
    job_id = str(_uuid.uuid4())[:8]
    result = run_job(job_id, req.user_id, req.task_type, req.payload)
    return {"job_id": job_id, "result": result.to_dict()}

@app.get("/claw/jobs")
async def claw_jobs(user_id: str):
    jobs = list_jobs(user_id)
    return {"jobs": jobs}

@app.get("/claw/job/{job_id}")
async def claw_job(job_id: str):
    job = load_job(job_id)
    if not job:
        return {"status": "error", "detail": "Job not found"}
    return job

@app.post("/push/subscribe")
async def push_subscribe(req: PushSubscribeRequest):
    profile = load_profile(req.user_id)
    profile["push_subscription"] = req.subscription
    profile["timezone"] = req.timezone
    save_profile(req.user_id, profile)
    return {"status": "ok"}

@app.get("/push/public-key")
async def push_public_key():
    return {"public_key": get_public_key()}

@app.get("/sw.js")
async def service_worker():
    resp = FileResponse(os.path.join(os.path.dirname(__file__), "sw.js"))
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp

class AddMealPlanRequest(BaseModel):
    user_id: str
    job_id: str

@app.post("/claw/add-meal-plan")
async def add_meal_plan(req: AddMealPlanRequest):
    """Adds all items from a meal plan job to cart."""
    from search import add_to_cart
    profile = load_profile(req.user_id)
    access_token = profile.get("kroger_access_token")

    if not access_token:
        from search import refresh_kroger_token
        refresh_token = profile.get("kroger_refresh_token")
        if refresh_token:
            new_access, new_refresh = refresh_kroger_token(refresh_token)
            if new_access:
                profile["kroger_access_token"] = new_access
                if new_refresh:
                    profile["kroger_refresh_token"] = new_refresh
                save_profile(req.user_id, profile)
                access_token = new_access
        if not access_token:
            return {"status": "need_auth"}

    job = load_job(req.job_id)
    if not job:
        return {"status": "error", "detail": "Job not found"}

    result = job.get("result", {})
    sections = result.get("sections", [])
    location_id = profile.get("location_id")

    added = 0
    failed = 0
    seen_upcs = set()

    for section in sections:
        for item in section.get("items", []):
            upc = item.get("upc")
            if not upc or upc in seen_upcs:
                continue
            seen_upcs.add(upc)
            status_code, _ = add_to_cart(
                upc=upc,
                quantity=1,
                location_id=location_id,
                access_token=access_token
            )
            if status_code in (200, 201, 204):
                added += 1
            else:
                failed += 1

    store_name = profile.get("store_name", "Kroger")
    return {
        "status": "success",
        "added": added,
        "failed": failed,
        "store_name": store_name
    }

# ── Usuals & Unusuals Endpoints ───────────────────────────────────────────────

class UsualProductRequest(BaseModel):
    user_id: str
    product: dict  # full product object — upc, name, brand, image, regular_price, sale_price, term

class RemoveUsualRequest(BaseModel):
    user_id: str
    upc: str

@app.get("/usuals")
async def get_usuals(user_id: str):
    products = get_usuals_products(user_id)
    unusuals = get_unusuals(user_id)
    profile = load_profile(user_id)
    autopilot = profile.get("claws", {}).get("weekly_autopilot", {})
    return {
        "usuals": products,
        "unusuals": unusuals,
        "autopilot": autopilot
    }

@app.post("/usuals/add")
async def add_usual(req: UsualProductRequest):
    updated = add_usual_product(req.user_id, req.product)
    return {"status": "ok", "usuals": updated}

@app.post("/usuals/remove")
async def remove_usual(req: RemoveUsualRequest):
    updated = remove_usual_product(req.user_id, req.upc)
    return {"status": "ok", "usuals": updated}

@app.post("/unusuals/add")
async def add_unusual_item(req: UsualProductRequest):
    updated = add_unusual(req.user_id, req.product)
    return {"status": "ok", "unusuals": updated}

@app.post("/unusuals/remove")
async def remove_unusual_item(req: RemoveUsualRequest):
    updated = remove_unusual(req.user_id, req.upc)
    return {"status": "ok", "unusuals": updated}

class AutopilotSettingsRequest(BaseModel):
    user_id: str
    enabled: bool
    mode: str = "remind"   # "auto" | "remind"
    day: str = "sunday"
    time: str = "18:00"

@app.post("/usuals/autopilot")
async def set_autopilot(req: AutopilotSettingsRequest):
    profile = load_profile(req.user_id)
    if "claws" not in profile:
        profile["claws"] = {}
    profile["claws"]["weekly_autopilot"] = {
        "enabled": req.enabled,
        "mode": req.mode,
        "day": req.day,
        "time": req.time
    }
    save_profile(req.user_id, profile)
    return {"status": "ok"}

@app.post("/usuals/run")
async def run_usuals_now(user_id: str):
    """Immediately runs the usuals order — adds all usuals + unusuals to cart."""
    from search import add_to_cart
    profile = load_profile(user_id)
    access_token = profile.get("kroger_access_token")

    if not access_token:
        refresh_token = profile.get("kroger_refresh_token")
        if refresh_token:
            new_access, new_refresh = refresh_kroger_token(refresh_token)
            if new_access:
                profile["kroger_access_token"] = new_access
                if new_refresh:
                    profile["kroger_refresh_token"] = new_refresh
                save_profile(user_id, profile)
                access_token = new_access
        if not access_token:
            return {"status": "need_auth"}

    location_id = profile.get("location_id")
    all_items = profile.get("usuals_products", []) + profile.get("unusuals", [])

    added = 0
    failed = 0
    seen_upcs = set()

    for item in all_items:
        upc = item.get("upc")
        if not upc or upc in seen_upcs:
            continue
        seen_upcs.add(upc)
        status_code, _ = add_to_cart(
            upc=upc,
            quantity=1,
            location_id=location_id,
            access_token=access_token
        )
        if status_code == 401:
            refresh_token = profile.get("kroger_refresh_token")
            if refresh_token:
                new_access, new_refresh = refresh_kroger_token(refresh_token)
                if new_access:
                    profile["kroger_access_token"] = new_access
                    if new_refresh:
                        profile["kroger_refresh_token"] = new_refresh
                    save_profile(user_id, profile)
                    access_token = new_access
                    status_code, _ = add_to_cart(upc=upc, quantity=1,
                                                  location_id=location_id,
                                                  access_token=access_token)
        if status_code in (200, 201, 204):
            added += 1
        else:
            failed += 1

    store_name = profile.get("store_name", "Kroger")
    return {"status": "success", "added": added, "failed": failed, "store_name": store_name}

# ── Product Search Endpoint ───────────────────────────────────────────────────

class SearchRequest(BaseModel):
    user_id: str
    term: str
    limit: int = 3

@app.post("/search")
async def search_products(req: SearchRequest):
    """Natural language → understand_task() → Kroger searches → product options."""
    profile = load_profile(req.user_id)
    zip_code = profile.get("zip_code", "10001")
    location_id = profile.get("location_id")

    if not location_id:
        return {"status": "error", "detail": "No store selected"}

    # Translate natural language to specific search terms
    terms = understand_task(req.term, history=[], profile=profile)

    # Cap at 4 terms to stay token/request efficient
    terms = terms[:4]

    results = []
    for term in terms:
        if isinstance(term, dict):
            term = term.get("term", "")
        if not term:
            continue
        data = search_kroger(term, zip_code=zip_code, location_id=location_id, limit=req.limit)
        for p in data.get("results", []):
            if not p.get("upc"):
                continue
            results.append({
                "upc": p["upc"],
                "name": p.get("name", ""),
                "brand": p.get("brand", ""),
                "image": p.get("image"),
                "regular_price": p.get("regular_price"),
                "sale_price": p.get("sale_price"),
                "term": term
            })

    return {"status": "ok", "results": results}
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("APP_PORT", "8767"))
    uvicorn.run(app, host="0.0.0.0", port=port)
