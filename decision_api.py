"""API for the Sports Predictor Centro de Decisión."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from decision_engine import evaluate_decision

router = APIRouter(prefix="/api/v1/decision", tags=["Centro de Decisión"])


class DecisionEvaluationRequest(BaseModel):
    sport: Literal["MLB", "NFL", "NBA", "TENNIS"]
    model_probability: float = Field(gt=0, lt=1, description="Probabilidad del resultado elegido, de 0 a 1.")
    decimal_odds: float = Field(gt=1, le=1000)
    data_quality: int = Field(default=100, ge=0, le=100)
    risk_signals: list[str] = Field(default_factory=list, max_length=20)
    market_probability: float | None = Field(default=None, gt=0, lt=1, description="Probabilidad de mercado ya ajustada sin margen.")
    opponent_model_probability: float | None = Field(default=None, gt=0, lt=1)
    opponent_decimal_odds: float | None = Field(default=None, gt=1, le=1000)


@router.post("/evaluate")
def evaluate(request: DecisionEvaluationRequest):
    try:
        return evaluate_decision(
            sport=request.sport,
            model_probability=request.model_probability,
            decimal_odds=request.decimal_odds,
            data_quality=request.data_quality,
            risk_signals=request.risk_signals,
            market_probability=request.market_probability,
            opponent_model_probability=request.opponent_model_probability,
            opponent_decimal_odds=request.opponent_decimal_odds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
