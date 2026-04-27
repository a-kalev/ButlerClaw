# 🦞 ButlerClaw

> *"I want to make lasagna for 6 people"* → Compares prices across stores. Best options added to your cart. You just press pay.

**ButlerClaw is an open-source AI shopping agent for regular people.** Not a chatbot — a Claw. It searches, compares, decides, and executes. You describe what you need in plain English. The Claw finds it across multiple retailers, compares prices, picks the best value, and adds it to your cart automatically. You open your cart and press pay. That's it.

No app to install. No account to create. Built entirely on free APIs. Designed for the average mom and dad, not just developers.

**Live demo:** [https://butlerclaw.duckdns.org](https://butlerclaw.duckdns.org)

---

## ✨ What It Does

- **Understands natural language** — "birthday cake for my daughter" → finds bakery cakes, not cake mix
- **Searches and compares** — finds the best option across retailers, not just one store
- **Knows your store** — picks your nearest Kroger-affiliated store (Kroger, Harris Teeter, Ralphs, Fred Meyer, King Soopers, and more) and remembers it
- **Real products, real prices** — live data including sale prices, never made up
- **Silently learns you** — remembers your dietary restrictions, family size, preferences, and budget across sessions without ever asking
- **Conversational** — "make it chocolate" understands what "it" refers to
- **Actually executes** — one tap adds items directly to your cart via OAuth. You just press pay.

---

## 🎯 Who This Is For

**Users:** Anyone who shops at a Kroger-affiliated store and wants a smarter way to shop.

**Developers:** If you want to build AI agents that actually do useful things for regular people — not just chat — this is a clean, minimal codebase to learn from and extend.

---

## 🏗️ Architecture

```
Browser (butlerclaw.duckdns.org)
        ↓
Nginx (HTTPS, reverse proxy)
        ↓
FastAPI (Python) — main.py
        ↓
┌───────────────┬──────────────────┬─────────────────┐
│   brain.py    │   search.py      │   memory.py     │
│   Groq API    │   Kroger API     │   SQLite        │
│   Llama 3.1   │   Products +     │   User profiles │
│   (free)      │   Locations +    │   Silent learn  │
│               │   Cart           │                 │
└───────────────┴──────────────────┴─────────────────┘
```

**Stack:** Python 3.11, FastAPI, Groq (Llama 3.1 8B), Kroger Public API, SQLite, Nginx, Let's Encrypt

**Cost to run:** $0/month (Oracle Always Free tier + free APIs)

---

## 🚀 Run It Yourself (5 minutes)

### Prerequisites
- Python 3.11+
- A free [Groq API key](https://console.groq.com) (14,400 req/day free)
- A free [Kroger Developer account](https://developer.kroger.com) (10,000 req/day free)

### 1. Clone & Install
```bash
git clone https://github.com/YOUR_USERNAME/butlerclaw.git
cd butlerclaw
pip install fastapi uvicorn python-dotenv requests
```

### 2. Configure
```bash
cp .env.example .env
nano .env  # add your API keys
```

```env
GROQ_API_KEY=your_groq_key_here
KROGER_CLIENT_ID=your_kroger_client_id
KROGER_CLIENT_SECRET=your_kroger_client_secret
```

### 3. Kroger App Setup
In your Kroger Developer dashboard:
- App Name: anything (not "Kroger")
- Environment: Production
- API Products: Products, Locations, Cart
- Redirect URI: `http://localhost:8767/kroger-callback`

### 4. Run
```bash
python main.py
```

Open `http://localhost:8767` — you're live.

---

## 📁 Project Structure

```
butlerclaw/
├── main.py         # FastAPI server — all endpoints
├── brain.py        # Groq AI — understand tasks, pick products, learn profiles
├── search.py       # Kroger API — search products, find stores, add to cart
├── memory.py       # SQLite — anonymous user profiles, silent learning
├── ui.html         # Complete single-file web UI (no build system)
├── .env.example    # Environment variables template
└── README.md
```

---

## 🧠 How the AI Works

**1. Understand** — User says "I want to make lasagna for 6 people." Groq breaks this into specific Kroger search terms: `["ground beef", "lasagna noodles", "ricotta cheese", "mozzarella", "tomato sauce"]`

**2. Search** — Each term searched against Kroger's live product catalog for the user's saved store, with real prices.

**3. Pick** — Groq evaluates the 5 results per term and picks the best value option, respecting the user's dietary restrictions and preferences.

**4. Learn** — After every conversation, Groq silently scans the exchange and updates the user's anonymous profile: family size, dietary needs, budget, preferences. Later conversations get smarter automatically.

**5. Remember** — Profiles stored in SQLite, keyed by anonymous browser cookie. No login. No email. No tracking.

---

## 🔑 Key Design Decisions

**Why Groq instead of OpenAI?**
Free tier with 14,400 requests/day. Llama 3.1 8B is fast and good enough for shopping tasks. Zero cost to run.

**Why Kroger API instead of scraping?**
Official API = reliable, legal, real prices, no bot detection. Covers 2,700+ stores across Kroger, Harris Teeter, Ralphs, Fred Meyer, King Soopers, Smith's, Mariano's, and more.

**Why SQLite instead of Postgres?**
One file. Zero configuration. Perfect for a single-server prototype. Trivial to migrate later.

**Why a single HTML file?**
No build system, no npm, no webpack. A developer can read the entire frontend in 10 minutes. Easy to fork and reskin.

**Why anonymous cookies instead of accounts?**
Regular people don't create accounts for new apps. The butler learns who you are from what you say — silently, privately, without asking.

---

## 🗺️ Roadmap

### ✅ Done
- Natural language grocery search
- Real prices + sale detection from Kroger API
- Store picker (remembers your store forever)
- Short-term conversation memory
- Long-term silent profile learning (dietary, family, preferences, budget)
- Kroger OAuth — Add to Cart
- HTTPS deployment on Oracle Always Free

### 🔲 Up Next (Good first issues)
- [ ] **Price tracking** — alert user when their usual items go on sale
- [ ] **"My usuals" list** — one-tap reorder of frequently bought items
- [ ] **Multi-item cart** — "add all to cart" button for the whole recommendation set
- [ ] **Purchase history** — Kroger OAuth scope `purchases.history` to suggest reorders
- [ ] **Recipe mode** — paste a recipe URL, get all ingredients found automatically
- [ ] **Budget mode** — "keep it under $50" respected across the whole session
- [ ] **Telegram bot** — same brain, Telegram interface (one new file)
- [ ] **Additional retailers** — Best Buy API (electronics), Open Food Facts (nutrition data)
- [ ] **Token refresh** — auto-refresh Kroger OAuth tokens before expiry
- [ ] **Progressive Web App** — "Add to Home Screen" for near-native mobile experience

### 🔮 The Claw Vision — Where This Is Going

This is v1. Kroger only. One store. The vision is much bigger:

**Multi-retailer comparison** — you say "paper towels", the Claw checks Walmart, Amazon, Target, Costco and picks the best value. You don't choose the store. The Claw does.

**True execution** — not just "here are some options." The Claw searches, compares, decides, and adds to cart across all your retailers automatically. Your only job is to press pay.

**Beyond groceries** — "I'm renovating my bathroom" → the Claw researches fixtures, compares Home Depot vs Wayfair vs Amazon, builds your cart. "My kid needs school supplies" → done. Any life task, any category.

**We need retailers to open their APIs.** Walmart, Amazon, Target, Costco — if you're reading this, we're building the interface your customers deserve. We'll send you customers who are ready to buy. Open your cart APIs.

If you work at one of these companies or know someone who does — open an issue. Let's talk.

---

## 🤝 Contributing

This is built for regular people by a non-developer. If you can code, your contribution goes a long way.

**To contribute:**
1. Fork the repo
2. Pick an issue from the roadmap above
3. Open a PR with a clear description

**Principles:**
- Keep it simple — a parent should be able to use it
- Keep it free — no paid APIs, no subscriptions
- Keep it surgical — don't touch code that nobody asked you to change
- Test it — verify it works before submitting

---

## 📄 License

MIT — do whatever you want with it.

---

## 🙏 Acknowledgments

Built with [Groq](https://groq.com), [Kroger Public API](https://developer.kroger.com), [FastAPI](https://fastapi.tiangolo.com), and [Oracle Cloud Always Free](https://www.oracle.com/cloud/free/).

---

*ButlerClaw — your personal shopping butler. 🦞*
