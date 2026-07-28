from __future__ import annotations

from src.data.sector_mapper import SectorMapper


class TestSectorMapper:
    def test_init(self):
        mapper = SectorMapper()
        assert mapper is not None

    def test_extract_sectors_from_text_no_keywords(self):
        mapper = SectorMapper()
        result = mapper.extract_sectors_from_text("some random text")
        assert result == []

    def test_extract_sectors_from_text_with_keyword(self):
        mapper = SectorMapper()
        result = mapper.extract_sectors_from_text("oil price and energy markets")
        assert isinstance(result, list)

    def test_extract_sectors_from_text_empty_string(self):
        mapper = SectorMapper()
        result = mapper.extract_sectors_from_text("")
        assert result == []

    def test_extract_geographic_context(self):
        mapper = SectorMapper()
        result = mapper.extract_geographic_context("россия and market")
        assert "russia" in result

    def test_extract_geographic_context_no_match(self):
        mapper = SectorMapper()
        result = mapper.extract_geographic_context("some random text")
        assert result == []

    def test_get_affected_sectors(self):
        mapper = SectorMapper()
        result = mapper.get_affected_sectors("MACRO", "oil", "oil prices rising")
        assert isinstance(result, dict)
