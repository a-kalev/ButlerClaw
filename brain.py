import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def understand_task(user_message, history=None, profile=None, strict=False):
    history = history or []
    profile = profile or {}
    profile_context = ""
    if profile.get("dietary"):
        profile_context += f"Dietary restrictions: {', '.join(profile['dietary'])}. "
    if profile.get("preferences"):
        profile_context += f"Preferences: {', '.join(profile['preferences'])}. "
    if profile.get("family"):
        profile_context += f"Family: {profile['family']}. "
    if profile.get("budget"):
        profile_context += f"Budget: ${profile['budget']}. "
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": f"""You are a Kroger shopping expert. Return specific product search terms that find real products on Kroger.com.
{profile_context}
Rules:
- Return ONLY a JSON array of specific product types. Nothing else.
- Every term must be a real product (e.g. "whole milk", "sourdough bread", "chicken breast", "bananas")
- NEVER return vague terms like "grocery list", "essentials", "items", "shopping", "list"
- NEVER return single words from the user message like "need", "make", "start", "with", "all"
- If user wants ready-made food: use bakery/deli terms ("bakery birthday cake", "rotisserie chicken", "fresh cupcakes")
- If user wants ingredients or produce: use specific product names ("whole milk", "large eggs", "roma tomatoes", "chicken breast")
- If request is vague (e.g. "groceries for the week"): return common weekly staples ["whole milk", "sourdough bread", "large eggs", "chicken breast", "bananas", "cheddar cheese"]
- If item was not found suggest other items from the SAME category (e.g., "white bread" if "italian bread" is not found). NEVER suggest items from different category as replacement 
- ALWAYS return a JSON array of strings like ["whole milk", "eggs"] UNLESS strict mode is active.
- If strict mode is active (current value: {strict}): you MUST return a JSON array of objects, NOT strings. Format: [{{"term": "skim milk", "quantity": 1}}, {{"term": "honey", "quantity": 1}}]. Respect quantities (e.g. "2 milks" → quantity 2). No additions, no duplicates.
- Scale quantity to request: single item = 1-2 terms, full meal = 3-5 terms, weekly shop = 6 terms max
- Use conversation history for follow-up requests (e.g. "make it chocolate" refers to previous item)
- Return ONLY valid JSON array, no explanation, no markdown fences"""
                },
                *[{"role": m["role"], "content": m["content"]} for m in history],
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.3
        }
    )
    content = response.json()["choices"][0]["message"]["content"].strip()
    content = content.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Groq returned non-JSON — extract the core noun from the message as fallback
        words = [w.strip('.,!?') for w in user_message.split() if len(w) > 3]
        return words[:3] if words else ["groceries"]

def pick_best(user_message, search_term, products, profile=None):
    profile = profile or {}
    profile_context = ""
    if profile.get("dietary"):
        profile_context += f"Dietary restrictions: {', '.join(profile['dietary'])}. "
    if profile.get("preferences"):
        profile_context += f"Preferences: {', '.join(profile['preferences'])}. "
    if profile.get("budget"):
        profile_context += f"Budget: ${profile['budget']}. "
    """Ask Groq to pick the best product from a list for this user's need."""
    if not products:
        return None
    product_list = "\n".join([
        f"{i}: {p['name']} | brand: {p['brand']} | ${p['regular_price']}"
        + (f" (sale: ${p['sale_price']})" if p['sale_price'] else "")
        for i, p in enumerate(products)
    ])
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": f"""You are a smart shopping assistant helping pick the best product.
{profile_context}
Given a user request and a numbered product list, return ONLY a JSON object like:
{{"index": 0, "reason": "Best value for the price"}}
Pick the best option respecting dietary restrictions and preferences. Keep reason under 10 words."""
                },
                {
                    "role": "user",
                    "content": f"User needs: {user_message}\nShopping for: {search_term}\n\nProducts:\n{product_list}"
                }
            ],
            "temperature": 0.3
        }
    )
    content = response.json()["choices"][0]["message"]["content"].strip()
    content = content.replace("```json", "").replace("```", "").strip()
    pick = json.loads(content)
    idx = pick.get("index", 0)
    if 0 <= idx < len(products):
        products[idx]["reason"] = pick.get("reason", "")
        return products[idx]
    return products[0]

def build_greeting(user_message, history=None, profile=None):
    history = history or []
    profile = profile or {}
    """Generate a short friendly opening line."""
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": "Write one warm, friendly sentence acknowledging the user's shopping request. Max 20 words. No lists."
                },
                *[{"role": m["role"], "content": m["content"]} for m in history],
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.7
        }
    )
    return response.json()["choices"][0]["message"]["content"].strip()
MAX_HISTORY = 10

def trim_history(history):
    """Keep first message + last MAX_HISTORY turns."""
    if len(history) <= MAX_HISTORY:
        return history
    return history[:1] + history[-(MAX_HISTORY - 1):]

def extract_profile_updates(history, current_profile):
    """Silently scan conversation and return updated profile."""
    history_text = "\n".join([
        f"{m['role'].upper()}: {m['content']}"
        for m in trim_history(history)
    ])
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": """You are a silent profile updater for a shopping assistant.
Given a conversation and current user profile, return an updated profile JSON.
Extract any learnable facts: family size, dietary restrictions, preferences, budget, zip code, usual items.
Rules:
- Later information always overrides earlier (if user says 2 kids after saying 4, use 2)
- Only update fields you have evidence for — leave others unchanged
- Keep dietary as a list e.g. ["lactose-free", "no nuts"]
- Keep preferences as a list e.g. ["organic", "budget-conscious"]
- Keep usuals as a list of product types e.g. ["whole milk", "sourdough bread"]
- budget should be a number or null
- family should be e.g. {"adults": 2, "kids": 3} or {}
- Return ONLY valid JSON, nothing else."""
                },
                {
                    "role": "user",
                    "content": f"Current profile:\n{json.dumps(current_profile, indent=2)}\n\nConversation:\n{history_text}\n\nReturn updated profile JSON:"
                }
            ],
            "temperature": 0.1
        }
    )
    content = response.json()["choices"][0]["message"]["content"].strip()
    content = content.replace("```json", "").replace("```", "").strip()
    updated = json.loads(content)
    # Always preserve user_id
    updated["user_id"] = current_profile["user_id"]
    return updated
def plan_meals(profile: dict) -> list:
    """One Groq call — returns list of 5 meal dicts with day, meal, ingredients, recipe."""
    profile_context = ""
    if profile.get("dietary"):
        profile_context += f"Dietary restrictions: {', '.join(profile['dietary'])}. STRICT — exclude these ingredients entirely."
    if profile.get("preferences"):
        profile_context += f" Preferences: {', '.join(profile['preferences'])}."
    if profile.get("family"):
        profile_context += f" Family: {profile['family']}."

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": f"""You are a meal planning expert. Plan 5 dinners.
{profile_context}
Return ONLY a JSON array of exactly 5 objects. No explanation, no markdown fences.
Each object must follow this exact shape:
{{
  "day": "Monday",
  "meal": "Lemon Herb Chicken",
  "ingredients": ["chicken breast", "lemon", "olive oil", "garlic", "fresh parsley"],
  "recipe": [
    "Juice lemon and mix with olive oil and minced garlic.",
    "Season chicken and coat with marinade, rest 10 minutes.",
    "Cook in skillet over medium-high heat 6 minutes per side.",
    "Garnish with fresh parsley and serve immediately."
  ]
}}
Rules:
- ingredients must be real Kroger-searchable product names (e.g. "chicken breast" not "protein")
- recipe must be exactly AT MOST 5 steps, plain English, no sub-bullets
- vary cuisines across the 5 meals — no two meals from the same cuisine
- no repeated main protein across meals
- days must be: Monday, Tuesday, Wednesday, Thursday, Friday
- Return ONLY valid JSON array, nothing else"""
                },
                {
                    "role": "user",
                    "content": "Plan 5 dinners for this family."
                }
            ],
            "temperature": 0.7
        }
    )
    content = response.json()["choices"][0]["message"]["content"].strip()
    content = content.replace("```json", "").replace("```", "").strip()
    try:
        meals = json.loads(content)
        if isinstance(meals, list) and len(meals) == 5:
            return meals
        return []
    except json.JSONDecodeError:
        return []
