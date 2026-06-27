"""Sector mapping and instrument relations engine.

Maps:
- Sectors → Tickers
- News topics → Affected instruments
- Commodity dependencies
- Regional impacts
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Sector to commodity/resource mappings
SECTOR_COMMODITIES = {
    "energy": ["oil", "gas", "coal", "uranium"],
    "metals": ["iron", "copper", "gold", "silver", "aluminum"],
    "agriculture": ["wheat", "corn", "soybeans", "sugar"],
    "banking": ["interest_rate", "credit", "usd"],
    "retail": ["consumer_spending", "employment"],
    "tech": ["semiconductors", "rare_earth"],
    "healthcare": ["pharma_ingredients"],
    "transport": ["oil", "lithium"],
    "utilities": ["gas", "coal", "water"],
}

# Geographic/political regions and their economic impacts
GEOPOLITICAL_IMPACTS = {
    "russia": {
        "sectors": ["energy", "metals", "agriculture"],
        "impact_type": "direct",
    },
    "china": {
        "sectors": ["tech", "agriculture", "metals", "manufacturing"],
        "impact_type": "direct",
    },
    "europe": {
        "sectors": ["energy", "banking", "retail"],
        "impact_type": "direct",
    },
    "usa": {
        "sectors": ["tech", "banking", "defense"],
        "impact_type": "direct",
    },
    "middle_east": {"sectors": ["energy", "transport"], "impact_type": "direct"},
}

# News keywords to sector mappings
KEYWORD_SECTOR_MAP = {
    "nefty": "energy",
    "газ": "energy",
    "oil": "energy",
    "gas": "energy",
    "coal": "energy",
    "уголь": "energy",
    "медь": "metals",
    "copper": "metals",
    "железо": "metals",
    "iron": "metals",
    "золото": "metals",
    "gold": "metals",
    "серебро": "metals",
    "silver": "metals",
    "пшеница": "agriculture",
    "wheat": "agriculture",
    "кукуруза": "agriculture",
    "corn": "agriculture",
    "соя": "agriculture",
    "soybeans": "agriculture",
    "банк": "banking",
    "bank": "banking",
    "кредит": "banking",
    "ставка": "banking",
    "rate": "banking",
    "интернет": "tech",
    "tech": "tech",
    "технолог": "tech",
    "semiconductor": "tech",
    "чип": "tech",
    "розница": "retail",
    "retail": "retail",
    "магазин": "retail",
    "производство": "manufacturing",
    "manufacturing": "manufacturing",
    "автомобиль": "transport",
    "auto": "transport",
    "truck": "transport",
    "грузоперевозки": "transport",
}


class SectorMapper:
    """Maps news articles to sectors and instruments."""

    def __init__(self):
        """Initialize sector mapper."""
        self.sector_commodities = SECTOR_COMMODITIES
        self.geopolitical_impacts = GEOPOLITICAL_IMPACTS
        self.keyword_sector_map = KEYWORD_SECTOR_MAP

    def extract_sectors_from_text(self, text: str) -> list[str]:
        """Extract mentioned sectors from text.

        Args:
            text: Combined title + summary

        Returns:
            List of detected sectors
        """
        text_lower = text.lower()
        sectors = set()

        for keyword, sector in self.keyword_sector_map.items():
            if keyword in text_lower:
                sectors.add(sector)

        return list(sectors)

    def extract_geographic_context(self, text: str) -> list[str]:
        """Extract geographic/political context from text.

        Args:
            text: Combined title + summary

        Returns:
            List of mentioned regions
        """
        text_lower = text.lower()
        regions = []

        region_keywords = {
            "russia": ["россия", "russian", "рф", "москва", "санкт-петербург"],
            "china": ["китай", "chinese", "пекин", "shanghai"],
            "europe": ["европа", "european", "евросоюз", "eu"],
            "usa": ["usa", "american", "сша", "нью-йорк"],
            "middle_east": ["middle east", "иран", "саудовская аравия", "израиль"],
        }

        for region, keywords in region_keywords.items():
            if any(kw in text_lower for kw in keywords):
                regions.append(region)

        return regions

    def get_affected_sectors(self, category: str, subcategory: str, text: str) -> dict[str, Any]:
        """Determine which sectors are affected by a news event.

        Args:
            category: News category (MACRO, GEOPOLITICAL, SECTOR, COMPANY, MARKET)
            subcategory: News subcategory
            text: Combined title + summary

        Returns:
            Dict with affected sectors and impact details
        """
        affected = {}

        # Direct sector mentions
        mentioned_sectors = self.extract_sectors_from_text(text)

        # Impact by category
        if category == "SECTOR":
            # Direct sector impact
            for sector in mentioned_sectors:
                affected[sector] = {
                    "impact_type": "direct",
                    "intensity": 0.8,
                    "scope": "primary",
                }

        elif category == "GEOPOLITICAL":
            # Geopolitical news affects specific sectors
            regions = self.extract_geographic_context(text)

            for region in regions:
                if region in self.geopolitical_impacts:
                    for sector in self.geopolitical_impacts[region]["sectors"]:
                        if sector not in affected:
                            affected[sector] = {
                                "impact_type": "geopolitical",
                                "intensity": 0.6,
                                "scope": "regional",
                                "region": region,
                            }

            # Specific subcategory impacts
            if subcategory == "sanctions":
                # Sanctions typically hit energy, metals, banking
                for sector in ["energy", "metals", "banking"]:
                    affected[sector] = {
                        "impact_type": "sanctions",
                        "intensity": 0.9,
                        "scope": "severe",
                    }

            elif subcategory == "conflict":
                # Conflict affects energy, defense, transport
                for sector in ["energy", "tech", "transport"]:
                    affected[sector] = {
                        "impact_type": "conflict",
                        "intensity": 0.7,
                        "scope": "regional",
                    }

            elif subcategory == "trade_war":
                # Trade war affects tech, manufacturing, agriculture
                for sector in ["tech", "manufacturing", "agriculture"]:
                    affected[sector] = {
                        "impact_type": "trade_war",
                        "intensity": 0.6,
                        "scope": "broad",
                    }

        elif category == "MACRO":
            # Macro news affects most sectors but differently
            if subcategory in ["interest_rate", "monetary_policy"]:
                # Rate changes affect banking, retail, tech (high leverage)
                for sector in ["banking", "retail", "tech"]:
                    affected[sector] = {
                        "impact_type": "monetary",
                        "intensity": 0.5,
                        "scope": "broad",
                    }

            elif subcategory == "inflation":
                # Inflation affects commodities, energy, metals
                for sector in ["energy", "metals", "agriculture"]:
                    affected[sector] = {
                        "impact_type": "inflation",
                        "intensity": 0.6,
                        "scope": "broad",
                    }

        elif category == "COMPANY":
            # Company-specific news affects that sector
            for sector in mentioned_sectors:
                affected[sector] = {
                    "impact_type": "company_specific",
                    "intensity": 0.3,
                    "scope": "sector_wide",
                }

        return affected

    def map_to_instruments(
        self, sectors: list[str], db_session: Any
    ) -> list[int]:
        """Map sectors to instrument IDs.

        Args:
            sectors: List of sector names
            db_session: Database session

        Returns:
            List of instrument IDs in those sectors
        """
        from src.db.models import Instrument

        instrument_ids = []

        for sector in sectors:
            instruments = db_session.query(Instrument).filter_by(sector=sector).all()
            instrument_ids.extend([i.id for i in instruments])

        return list(set(instrument_ids))  # Remove duplicates

    def get_cascading_effects(self, primary_sectors: list[str]) -> dict[str, Any]:
        """Calculate cascading effects through commodity chains.

        Args:
            primary_sectors: List of directly affected sectors

        Returns:
            Dict with secondary and tertiary effects
        """
        cascade_effects = {}

        # Secondary effects through commodity links
        for sector in primary_sectors:
            if sector in self.sector_commodities:
                commodities = self.sector_commodities[sector]

                # Find other sectors using same commodities
                for other_sector, other_commodities in self.sector_commodities.items():
                    if other_sector != sector:
                        common = set(commodities) & set(other_commodities)
                        if common:
                            cascade_effects[other_sector] = {
                                "impact_type": "cascade",
                                "intensity": 0.4,  # Secondary effects are weaker
                                "common_commodities": list(common),
                                "via_sector": sector,
                            }

        return cascade_effects

    def analyze_sector_exposure(
        self, category: str, subcategory: str, text: str, db_session: Any
    ) -> dict[str, Any]:
        """Complete sector analysis for a news article.

        Args:
            category: News category
            subcategory: News subcategory
            text: Combined title + summary
            db_session: Database session

        Returns:
            Complete sector exposure analysis
        """
        primary_sectors = self.get_affected_sectors(category, subcategory, text)
        cascade_sectors = self.get_cascading_effects(list(primary_sectors.keys()))

        # Map to instruments
        primary_instruments = self.map_to_instruments(list(primary_sectors.keys()), db_session)
        cascade_instruments = self.map_to_instruments(
            list(cascade_sectors.keys()), db_session
        )

        return {
            "primary_sectors": primary_sectors,
            "cascade_sectors": cascade_sectors,
            "primary_instruments": primary_instruments,
            "cascade_instruments": cascade_instruments,
            "total_affected_instruments": len(
                set(primary_instruments + cascade_instruments)
            ),
        }
