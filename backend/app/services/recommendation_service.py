"""Recommendation orchestration boundary.

The legacy CoachService still owns most ranking logic.  This service is the
target seam for migrating request-time orchestration out of CoachService.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class RecommendationService:
    def __init__(self, coach_service):
        self.coach_service = coach_service

    def get_today_recommendations(
        self,
        user_id: str = "default",
        risk_level: str = "medium",
        max_count: int = 30,
        cached_only: bool = False,
    ) -> Dict[str, Any]:
        if cached_only:
            return self.coach_service.get_cached_today_picks(max_count=max_count, user_id=user_id) or {
                "status": "empty",
                "picks": [],
            }
        return self.coach_service.get_today_picks(max_count=max_count, user_id=user_id, risk_level=risk_level)

    def get_pick_detail(
        self,
        pick_id: str,
        user_id: str = "default",
        risk_level: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.coach_service.get_pick_detail(pick_id=pick_id, user_id=user_id, risk_level=risk_level)
