from __future__ import annotations

import pytest


class TestMacroCollector:
    @pytest.mark.asyncio
    async def test_latest_values_from_db(self, db_session):
        from datetime import date

        from src.collectors.macro import MacroCollector
        from src.db.models import MacroIndicator

        db_session.add(MacroIndicator(date=date.today(), indicator_type="imoex", value=3200.0))
        db_session.commit()

        values = MacroCollector.latest_values(db_session)
        assert isinstance(values, dict)
        assert values.get("imoex") == 3200.0

    def test_macro_types_constant(self):
        from src.collectors.macro import MACRO_TYPES

        assert "brent" in MACRO_TYPES
        assert "key_rate" in MACRO_TYPES
        assert "usd_rate" in MACRO_TYPES
        assert "imoex" in MACRO_TYPES
        assert "cpi" in MACRO_TYPES
        assert "ofz_10y" in MACRO_TYPES
        assert "m2" in MACRO_TYPES
