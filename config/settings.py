import os
from dotenv import load_dotenv

load_dotenv()

# === API Keys ===
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CURRENTS_API_KEY = os.getenv("CURRENTS_API_KEY", "")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY", "")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///news_agent.db")

# === Timezone ===
TIMEZONE = "Asia/Kolkata"

# === Schedule ===
MORNING_HOUR = 8
MORNING_MINUTE = 0
EVENING_HOUR = 22
EVENING_MINUTE = 0
FETCH_INTERVAL_MINUTES = 15

# === Watched Tickers ===
WATCHED_TICKERS = [
    # US Market
    "NVDA", "TSLA", "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    # Crypto
    "BTC", "ETH",
    # Indian Market (NSE)
    "RELIANCE", "INFY", "TCS",
]

# === Ticker Aliases (Indirect Resolution) ===
TICKER_ALIASES = {
    "apple": ["AAPL"], "iphone maker": ["AAPL"], "tim cook": ["AAPL"],
    "microsoft": ["MSFT"], "redmond giant": ["MSFT"], "satya nadella": ["MSFT"],
    "nvidia": ["NVDA"], "jensen huang": ["NVDA"],
    "tesla": ["TSLA"], "elon musk": ["TSLA"],
    "google": ["GOOGL"], "alphabet": ["GOOGL"], "sundar pichai": ["GOOGL"],
    "amazon": ["AMZN"], "jeff bezos": ["AMZN"], "andy jassy": ["AMZN"],
    "meta": ["META"], "facebook": ["META"], "mark zuckerberg": ["META"],
    "bitcoin": ["BTC"], "ethereum": ["ETH"],
    "reliance": ["RELIANCE"], "mukesh ambani": ["RELIANCE"],
    "infosys": ["INFY"], "tcs": ["TCS"], "tata consultancy": ["TCS"]
}

# === News Categories ===
NEWS_CATEGORIES = [
    "AI & Tech",
    "Finance & Stocks",
    "Geo-Politics",
    "Startups",
    "Leadership",
]

# === Category Keywords (for filtering relevance) ===
CATEGORY_KEYWORDS = {
    "AI & Tech": [
        "ai", "artificial intelligence", "llm", "gpt", "claude", "gemini",
        "openai", "anthropic", "deepmind", "machine learning", "deep learning",
        "neural network", "transformer", "diffusion", "stable diffusion",
        "midjourney", "copilot", "chatbot", "automation", "robotics",
        "autonomous", "computer vision", "nlp", "hugging face", "ollama",
        "langchain", "vector database", "rag", "fine-tuning", "open source ai",
    ],
    "Finance & Stocks": [
        "stock", "market", "earnings", "revenue", "profit", "loss",
        "ipo", "acquisition", "merger", "buyback", "dividend",
        "fed", "federal reserve", "rbi", "sebi", "inflation", "interest rate",
        "gdp", "recession", "bull", "bear", "nasdaq", "s&p", "dow",
        "nifty", "sensex", "nse", "bse", "bitcoin", "ethereum", "crypto",
        "etf", "bond", "yield", "forex",
    ] + [t.lower() for t in WATCHED_TICKERS],
    "Geo-Politics": [
        "war", "conflict", "sanction", "treaty", "nato", "un",
        "nuclear", "missile", "military", "troops", "ceasefire",
        "election", "referendum", "coup", "protest", "embargo",
        "diplomacy", "summit", "bilateral", "tariff", "trade war",
        "china", "russia", "ukraine", "israel", "gaza", "iran",
        "north korea", "taiwan", "eu", "brexit",
    ],
    "Startups": [
        "startup", "funding", "seed round", "series a", "series b",
        "series c", "venture capital", "vc", "angel investor",
        "unicorn", "valuation", "accelerator", "incubator",
        "y combinator", "techstars", "pivot", "bootstrap",
        "saas", "fintech", "edtech", "healthtech",
    ],
    "Leadership": [
        "ceo", "cto", "cfo", "founder", "executive", "board",
        "leadership", "management", "strategy", "vision",
        "culture", "innovation", "disruption", "transformation",
        "mentor", "coach", "growth mindset",
    ],
}

# === RSS Feeds ===
RSS_SOURCES = {
    "AI & Tech": [
        "https://news.ycombinator.com/rss",
        "http://export.arxiv.org/rss/cs.AI",
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://www.wired.com/feed/rss",
    ],
    "Finance & Stocks": [
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://www.moneycontrol.com/rss/latestnews.xml",
        "https://economictimes.indiatimes.com/rssfeedsdefault.cms",
        "https://www.federalreserve.gov/feeds/press_all.xml",
    ],
    "Geo-Politics": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://foreignpolicy.com/feed/",
        "https://feeds.feedburner.com/ndtvnews-world-news",
    ],
    "Startups": [
        "https://techcrunch.com/category/startups/feed/",
        "https://www.livemint.com/rss/news",
    ],
    "Leadership": [
        "https://hbr.org/resources/rss",
    ],
}

# === Reddit Subreddits ===
REDDIT_SUBS = [
    "MachineLearning",
    "investing",
    "geopolitics",
    "startups",
    "IndianStockMarket",
]

# === Calendar Colors ===
CALENDAR_COLORS = {
    "AI & Tech": "9",         # Blueberry
    "Finance & Stocks": "2",  # Sage
    "Geo-Politics": "11",     # Tomato
    "Startups": "3",          # Grape
    "Leadership": "5",        # Banana
}

# === Verification ===
CONFIDENCE_THRESHOLD_CALENDAR = 40   # Min confidence to save to calendar
CONFIDENCE_THRESHOLD_BREAKING = 85   # Min confidence for breaking alert
MAX_ITEMS_PER_DIGEST = 10            # 5-10 high quality items
BREAKING_CATEGORIES = ["Finance & Stocks", "Geo-Politics"]
