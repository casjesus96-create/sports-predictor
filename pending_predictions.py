
from fastapi import APIRouter, HTTPException

from repository import get_pending_predictions

router = APIRouter()


@router.get("/api/v1/predictions/pending")
def pending_predictions():
    try:
        records = get_pending_predictions()

        return {
            "success": True,
            "total": len(records),
            "predictions": records,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "PENDING_PREDICTIONS_ERROR",
                "message": "No se pudieron obtener las predicciones pendientes.",
                "details": str(exc),
            },
        )
