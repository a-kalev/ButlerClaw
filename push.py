import os
import json
from pywebpush import webpush, WebPushException
from dotenv import load_dotenv

load_dotenv()

VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY_PATH = os.path.join(os.path.dirname(__file__), "vapid_private.pem")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:amirk@gmail.com")
VAPID_CLAIMS = {"sub": VAPID_CLAIMS_EMAIL}

def send_push(subscription: dict, title: str, body: str, url: str = "/") -> bool:
    """
    Send a Web Push notification.
    subscription: the object saved from browser PushManager.subscribe()
    Returns True on success, False on failure.
    """
    if not subscription or not VAPID_PUBLIC_KEY:
        return False
    try:
        with open(VAPID_PRIVATE_KEY_PATH, "r") as f:
            private_key = f.read().strip()
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=private_key,
            vapid_claims=VAPID_CLAIMS
        )
        return True
    except WebPushException as e:
        print(f"[push] WebPushException: {e}")
        return False
    except Exception as e:
        print(f"[push] Error: {e}")
        return False

def get_public_key() -> str:
    return VAPID_PUBLIC_KEY or ""
