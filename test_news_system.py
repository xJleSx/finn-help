"""Test all imports and basic functionality"""

import sys

def test_imports():
    """Test all module imports"""
    errors = []
    success = []
    
    modules = [
        ("NewsFilter", "src.data.news_filter", "NewsFilter"),
        ("NewsClassifier", "src.data.news_classifier", "NewsClassifier"),
        ("NewsDeduplicator", "src.data.news_processor", "NewsDeduplicator"),
        ("SectorMapper", "src.data.sector_mapper", "SectorMapper"),
        ("ImpactMatrix", "src.data.impact_matrix", "ImpactMatrix"),
        ("SectorImpactEngine", "src.data.sector_impact_engine", "SectorImpactEngine"),
        ("CompanyRiskAggregator", "src.data.company_risk_aggregator", "CompanyRiskAggregator"),
        ("GeopoliticalRiskEngine", "src.data.geopolitical_risk_engine", "GeopoliticalRiskEngine"),
        ("EventDetector", "src.data.event_detector", "EventDetector"),
        ("SentimentDivergenceDetector", "src.data.event_detector", "SentimentDivergenceDetector"),
        ("SignalFusionIntegration", "src.data.signal_fusion_integration", "SignalFusionIntegration"),
        ("DashboardDataProvider", "src.data.dashboard_provider", "DashboardDataProvider"),
        ("NewsBatchProcessor", "src.data.batch_processor", "NewsBatchProcessor"),
    ]
    
    for name, module, cls in modules:
        try:
            mod = __import__(module, fromlist=[cls])
            getattr(mod, cls)
            success.append(name)
            print(f"OK: {name}")
        except Exception as e:
            errors.append((name, str(e)))
            print(f"ERROR: {name} - {e}")
    
    return success, errors

def test_db_models():
    """Test database ORM models"""
    from src.db.models import (
        News, NewsEvent, NewsInstrument,
        NewsSectorImpact, NewsCompanyImpact,
        SectorRiskHistory, CompanyRiskHistory,
        GeopoliticalRiskHistory
    )
    
    models = [
        News, NewsEvent, NewsInstrument,
        NewsSectorImpact, NewsCompanyImpact,
        SectorRiskHistory, CompanyRiskHistory,
        GeopoliticalRiskHistory
    ]
    
    print("\nDatabase models:")
    for model in models:
        print(f"OK: {model.__name__} (table: {model.__tablename__})")
    
    return True

if __name__ == "__main__":
    print("="*60)
    print("TESTING NEWS SYSTEM")
    print("="*60)
    
    print("\n1. Testing module imports...")
    success, errors = test_imports()
    
    print(f"\nSummary: {len(success)} OK, {len(errors)} ERRORS")
    
    if errors:
        print("\nFailed imports:")
        for name, error in errors:
            print(f"  - {name}: {error}")
    
    print("\n2. Testing database models...")
    try:
        test_db_models()
        print("\nAll ORM models OK!")
    except Exception as e:
        print(f"DB models error: {e}")
    
    print("\n" + "="*60)
    if not errors:
        print("ALL TESTS PASSED!")
    else:
        print(f"FAILED: {len(errors)} issues found")
        sys.exit(1)
    print("="*60)
