# -*- coding: utf-8 -*-
from __future__ import annotations

from loguru import logger
from pydantic import BaseModel, Field

from models import PromotionGame
from services.epic_games_service import EpicAgent, get_promotions


class CollectionSummary(BaseModel):
    all_promotions: list[PromotionGame] = Field(default_factory=list)
    newly_claimed_promotions: list[PromotionGame] = Field(default_factory=list)
    previously_claimed_promotions: list[PromotionGame] = Field(default_factory=list)
    unconfirmed_promotions: list[PromotionGame] = Field(default_factory=list)
    failed_promotions: list[PromotionGame] = Field(default_factory=list)
    error_message: str = ""


class EpicCollectionSummaryError(RuntimeError):
    def __init__(self, message: str, summary: CollectionSummary):
        super().__init__(message)
        self.summary = summary


def _promotion_key(promotion: PromotionGame) -> str:
    return promotion.namespace or promotion.id or promotion.url


def _unique_promotions(promotions: list[PromotionGame]) -> list[PromotionGame]:
    result: list[PromotionGame] = []
    keys: set[str] = set()
    for promotion in promotions:
        key = _promotion_key(promotion)
        if key in keys:
            continue
        result.append(promotion)
        keys.add(key)
    return result


def _promotions_in_namespaces(
    promotions: list[PromotionGame], namespaces: set[str]
) -> list[PromotionGame]:
    return _unique_promotions(
        [promotion for promotion in promotions if promotion.namespace in namespaces]
    )


def _promotions_missing_from_snapshot(
    promotions: list[PromotionGame], namespaces: set[str]
) -> list[PromotionGame]:
    return _unique_promotions(
        [
            promotion
            for promotion in promotions
            if not promotion.namespace or promotion.namespace not in namespaces
        ]
    )


async def collect_epic_games_with_summary(agent: EpicAgent) -> CollectionSummary:
    all_promotions = get_promotions()
    before_namespaces = await agent.refresh_order_namespaces()
    previously_claimed = _promotions_in_namespaces(all_promotions, before_namespaces)
    pending_promotions = _unique_promotions(
        [promotion for promotion in all_promotions if promotion.namespace not in before_namespaces]
    )

    try:
        await agent.collect_epic_games()
    except Exception as err:
        try:
            after_namespaces = await agent.refresh_order_namespaces()
        except Exception as snapshot_err:
            logger.warning(
                "Failed to refresh Epic order history after collection error | error_type={}",
                type(snapshot_err).__name__,
            )
            summary = CollectionSummary(
                all_promotions=all_promotions,
                previously_claimed_promotions=previously_claimed,
                unconfirmed_promotions=pending_promotions,
                error_message=str(err),
            )
        else:
            summary = CollectionSummary(
                all_promotions=all_promotions,
                newly_claimed_promotions=_promotions_in_namespaces(
                    all_promotions, after_namespaces - before_namespaces
                ),
                previously_claimed_promotions=previously_claimed,
                failed_promotions=_promotions_missing_from_snapshot(
                    pending_promotions, after_namespaces
                ),
                error_message=str(err),
            )
        raise EpicCollectionSummaryError(str(err), summary) from err

    try:
        after_namespaces = await agent.refresh_order_namespaces()
    except Exception as err:
        logger.warning(
            "Failed to refresh Epic order history after collection | error_type={}",
            type(err).__name__,
        )
        message = f"Failed to refresh Epic order history after collection: {type(err).__name__}"
        summary = CollectionSummary(
            all_promotions=all_promotions,
            previously_claimed_promotions=previously_claimed,
            unconfirmed_promotions=pending_promotions,
            error_message=message,
        )
        raise EpicCollectionSummaryError(message, summary) from err

    newly_claimed = _promotions_in_namespaces(all_promotions, after_namespaces - before_namespaces)
    unconfirmed_promotions = _promotions_missing_from_snapshot(pending_promotions, after_namespaces)

    return CollectionSummary(
        all_promotions=all_promotions,
        newly_claimed_promotions=newly_claimed,
        previously_claimed_promotions=previously_claimed,
        unconfirmed_promotions=unconfirmed_promotions,
    )
