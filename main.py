import os
import hmac
import json
import base64
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from random import choice, randint
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# Optional Stripe import (used if STRIPE_SECRET_KEY is configured)
try:
    import stripe  # type: ignore
except Exception:  # pragma: no cover
    stripe = None

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ISSUER = "flamez-signals"

app = FastAPI(title="Flamez Signals API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)


class BettingSignal(BaseModel):
    match: str
    league: str
    prediction: Literal["1X", "12", "X2", "GG", "NG", "Over 2.5", "Under 2.5"]
    confidence: int = Field(ge=0, le=100)
    risk: Literal["Low", "Medium", "High"]


class SignalsResponse(BaseModel):
    date: str
    betting_signals: List[BettingSignal]


class SegmentedSignalsResponse(BaseModel):
    date: str
    free: List[BettingSignal]
    vip: List[BettingSignal]


class VIPToken(BaseModel):
    token: str
    expires_at: str


@app.get("/", tags=["health"])
def read_root():
    return {"message": "Flamez Signals Backend running"}


@app.get("/api/hello", tags=["health"])
def hello():
    return {"message": "Hello from the Flamez Signals API!"}


@app.get("/test", tags=["health"])
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Used (no persistence required)",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    # Check environment variables
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


# -------- Minimal signed token utilities (no external deps) -------- #

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload_b64: str) -> str:
    digest = hmac.new(JWT_SECRET.encode(), payload_b64.encode(), sha256).digest()
    return _b64url(digest)


def create_vip_token(days: int = 7) -> VIPToken:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days)
    payload = {
        "iss": JWT_ISSUER,
        "sub": "vip",
        "scope": "vip:read",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig_b64 = _sign(payload_b64)
    token = f"{payload_b64}.{sig_b64}"
    return VIPToken(token=token, expires_at=exp.isoformat())


def verify_vip_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> bool:
    if not credentials or credentials.scheme.lower() != "bearer":
        return False
    token = credentials.credentials
    try:
        payload_b64, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(payload_b64)):
            return False
        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get("iss") != JWT_ISSUER or payload.get("scope") != "vip:read":
            return False
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            return False
        return True
    except Exception:
        return False


# -------- Betting Signals Generator (no external APIs) -------- #
TEAMS = {
    "England - Premier League": [
        "Manchester City", "Arsenal", "Liverpool", "Chelsea", "Tottenham",
        "Newcastle", "Manchester United", "Brighton", "Brentford", "Aston Villa"
    ],
    "Spain - La Liga": [
        "Barcelona", "Real Madrid", "Atletico Madrid", "Sevilla", "Real Sociedad",
        "Real Betis", "Villarreal", "Athletic Bilbao", "Valencia", "Girona"
    ],
    "Italy - Serie A": [
        "Inter", "AC Milan", "Juventus", "Napoli", "Roma", "Lazio", "Atalanta", "Fiorentina"
    ],
    "Germany - Bundesliga": [
        "Bayern Munich", "Borussia Dortmund", "RB Leipzig", "Bayer Leverkusen", "Eintracht Frankfurt",
        "Freiburg", "Hoffenheim", "Wolfsburg"
    ],
    "France - Ligue 1": [
        "PSG", "Monaco", "Lille", "Lyon", "Marseille", "Rennes", "Nice", "Montpellier"
    ],
    "Netherlands - Eredivisie": [
        "Ajax", "PSV", "Feyenoord", "AZ Alkmaar", "Twente", "Utrecht"
    ],
    "Portugal - Primeira Liga": [
        "Benfica", "Porto", "Sporting CP", "Braga", "Guimaraes"
    ]
}

PICKS = ["1X", "12", "X2", "GG", "NG", "Over 2.5", "Under 2.5"]


def make_signal(league: str, tier: Literal["free", "vip"] = "free") -> BettingSignal:
    teams = TEAMS[league]
    home = choice(teams)
    away = choice([t for t in teams if t != home])
    prediction = choice(PICKS)

    # Confidence bands balanced and realistic
    base = {
        "1X": (62, 78),
        "12": (58, 72),
        "X2": (60, 75),
        "GG": (60, 72),
        "NG": (55, 70),
        "Over 2.5": (60, 75),
        "Under 2.5": (55, 70),
    }[prediction]
    confidence = randint(base[0], base[1])

    # VIP tier skews slightly higher confidence
    if tier == "vip":
        confidence = min(90, confidence + randint(3, 7))

    risk = "Low" if confidence >= 72 else ("Medium" if confidence >= 60 else "High")

    # Small nudge: derby-like names increase GG/Over likelihood
    if ("Real" in home and "Real" in away) or ("AC" in home and "Inter" in away):
        if prediction in ["GG", "Over 2.5"]:
            confidence = min(92 if tier == "vip" else 80, confidence + 2)
            risk = "Low" if confidence >= 72 else risk

    return BettingSignal(
        match=f"{home} vs {away}",
        league=league,
        prediction=prediction,
        confidence=confidence,
        risk=risk,
    )


@app.get("/api/predictions", response_model=SignalsResponse, tags=["predictions"])
def get_predictions(count: int = 6):
    """Generate exactly 6 betting signals for today's date.
    Any provided `count` is ignored to enforce the 6-item limit.
    """
    count = 6  # enforce fixed number of free tips

    leagues = list(TEAMS.keys())
    signals: List[BettingSignal] = []

    # Ensure variety by cycling leagues
    i = 0
    while len(signals) < count:
        league = leagues[i % len(leagues)]
        signals.append(make_signal(league, tier="free"))
        i += 1

    today = datetime.utcnow().strftime("%Y-%m-%d")
    return SignalsResponse(date=today, betting_signals=signals)


@app.get("/api/predictions/segmented", response_model=SegmentedSignalsResponse, tags=["predictions"])
def get_segmented_predictions(request: Request, free_count: int = 6, vip_count: int = 6, vip_ok: bool = Depends(verify_vip_token)):
    """Return separate sections for Free and VIP tips.
    Free: fixed at 6 items. VIP: 3-10 items (clamped) with slightly higher confidence.

    VIP tips are only returned when a valid Bearer token is supplied.
    Otherwise, VIP list is returned empty.
    """
    # Enforce exactly 6 free tips
    free_count = 6
    vip_count = max(3, min(10, vip_count))

    leagues = list(TEAMS.keys())

    def build(count: int, tier: Literal["free", "vip"]) -> List[BettingSignal]:
        out: List[BettingSignal] = []
        i = 0
        while len(out) < count:
            league = leagues[i % len(leagues)]
            out.append(make_signal(league, tier=tier))
            i += 1
        return out

    today = datetime.utcnow().strftime("%Y-%m-%d")

    free_list = build(free_count, "free")
    vip_list = build(vip_count, "vip") if vip_ok else []

    return SegmentedSignalsResponse(
        date=today,
        free=free_list,
        vip=vip_list,
    )


# -------- VIP Auth & Payments -------- #
@app.post("/api/vip/demo-activate", response_model=VIPToken, tags=["auth"])
def demo_activate_vip():
    """Issue a demo VIP token (no payment) valid for 7 days.
    Useful for development and preview environments.
    """
    return create_vip_token(days=7)


@app.post("/api/payments/checkout", tags=["payments"])
async def create_checkout_session(request: Request):
    """Create a Stripe Checkout Session and return its URL.
    Requires STRIPE_SECRET_KEY and STRIPE_PRICE_ID to be set. If not configured,
    returns 400 with guidance.
    """
    secret = os.getenv("STRIPE_SECRET_KEY")
    price_id = os.getenv("STRIPE_PRICE_ID")
    success_url = os.getenv("STRIPE_SUCCESS_URL") or f"{request.headers.get('origin','') or 'http://localhost:3000'}/?checkout=success"
    cancel_url = os.getenv("STRIPE_CANCEL_URL") or f"{request.headers.get('origin','') or 'http://localhost:3000'}/?checkout=cancel"

    if not secret or not price_id or stripe is None:
        raise HTTPException(status_code=400, detail="Stripe not configured. Use demo activation or set STRIPE_SECRET_KEY and STRIPE_PRICE_ID.")

    stripe.api_key = secret
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            allow_promotion_codes=True,
        )
        return {"url": session.url}
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(e))


# Optional webhook stub (records events in logs)
@app.post("/api/webhook/stripe", tags=["payments"])
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    if stripe is None or not endpoint_secret:
        # Accept silently in dev environments
        return {"received": True, "note": "Stripe not configured"}

    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=endpoint_secret)
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")

    # Handle completed checkout by issuing a token (stateless demo)
    if event.get("type") == "checkout.session.completed":
        # In a real app, link customer to your user and persist entitlement
        # Here, nothing to persist; clients should rely on success redirect to claim
        pass

    return {"received": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
