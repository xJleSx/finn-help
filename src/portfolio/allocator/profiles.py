PROFILES = {
    "conservative": {
        "etf": {"weight": 0.50, "label": "БПИФ (ETF)", "max": 4},
        "dividend": {"weight": 0.20, "label": "Дивидендные акции", "max": 3},
        "bond": {"weight": 0.25, "label": "Облигации / ОФЗ", "max": 4},
        "growth": {"weight": 0.05, "label": "Акции роста", "max": 1},
    },
    "balanced": {
        "etf": {"weight": 0.40, "label": "БПИФ (ETF)", "max": 3},
        "dividend": {"weight": 0.30, "label": "Дивидендные акции", "max": 4},
        "bond": {"weight": 0.20, "label": "Облигации / ОФЗ", "max": 3},
        "growth": {"weight": 0.10, "label": "Акции роста", "max": 2},
    },
    "aggressive": {
        "etf": {"weight": 0.25, "label": "БПИФ (ETF)", "max": 3},
        "dividend": {"weight": 0.25, "label": "Дивидендные акции", "max": 3},
        "bond": {"weight": 0.10, "label": "Облигации / ОФЗ", "max": 2},
        "growth": {"weight": 0.40, "label": "Акции роста", "max": 4},
    },
}
