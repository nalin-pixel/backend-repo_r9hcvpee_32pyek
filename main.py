import os
from datetime import datetime
from random import choice, randint
from typing import List, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Flamez Signals API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BettingSignal(BaseModel):
    match: str
    league: str
    prediction: Literal["1X", "12", "X2", "GG", "NG", "Over 2.5", "Under 2.5"]
    confidence: int = Field(ge=0, le=100)
    risk: Literal["Low", "Medium", "High"]


class SignalsResponse(BaseModel):
    date: str
    betting_signals: List[BettingSignal]


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


def make_signal(league: str) -> BettingSignal:
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

    risk = "Low" if confidence >= 72 else ("Medium" if confidence >= 60 else "High")

    # Small nudge: derby-like names increase GG/Over likelihood
    if ("Real" in home and "Real" in away) or ("AC" in home and "Inter" in away):
        if prediction in ["GG", "Over 2.5"]:
            confidence = min(80, confidence + 2)
            risk = "Low" if confidence >= 72 else risk

    return BettingSignal(
        match=f"{home} vs {away}",
        league=league,
        prediction=prediction,
        confidence=confidence,
        risk=risk,
    )


@app.get("/api/predictions", response_model=SignalsResponse, tags=["predictions"])
def get_predictions(count: int = 12):
    """Generate 10-15 balanced betting signals for today's date.
    Use `count` query param to adjust (defaults to 12, clamped to [10,15]).
    """
    count = max(10, min(15, count))

    leagues = list(TEAMS.keys())
    signals: List[BettingSignal] = []

    # Ensure variety by cycling leagues
    i = 0
    while len(signals) < count:
        league = leagues[i % len(leagues)]
        signals.append(make_signal(league))
        i += 1

    today = datetime.utcnow().strftime("%Y-%m-%d")
    return SignalsResponse(date=today, betting_signals=signals)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
