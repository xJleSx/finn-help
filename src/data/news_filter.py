"""News filtering and garbage detection engine.

Filters out spam, press releases, and low-quality news using:
- Keyword blacklist
- Structural analysis
- LLM-based classification
"""

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Keywords indicating spam/low-quality content
SPAM_KEYWORDS = {
    "спам",
    "реклама",
    "объявление",
    "пресс-релиз",
    "press release",
    "купить",
    "продать",
    "займ",
    "кредит",
    "казино",
    "ставки",
    "лотерея",
    "розыгрыш",
}

# Keywords indicating press releases
PRESS_RELEASE_INDICATORS = {
    "пресс-релиз",
    "press release",
    "коммюнике",
    "сообщает компания",
    "сообщает пресс-служба",
    "официальное заявление",
    "от компании",
}

# Keywords indicating opinion/analysis (not news)
OPINION_INDICATORS = {
    "мнение",
    "мнения экспертов",
    "мой взгляд",
    "я считаю",
    "на мой взгляд",
    "колонка",
    "эссе",
    "комментарий",
    "опиния",
}

# Minimum quality thresholds
MIN_TITLE_LENGTH = 10
MIN_SUMMARY_LENGTH = 30
MIN_SENTENCE_COUNT = 2
MAX_HASHTAG_RATIO = 0.3  # More than 30% hashtags = likely spam


class NewsFilter:
    """Filters out spam, low-quality news, and non-news content."""

    def __init__(self, llm_classifier: Optional[Any] = None):
        """Initialize news filter.

        Args:
            llm_classifier: Optional LLM function for classification.
                           Should take (title, summary) and return {'category': str}
        """
        self.llm_classifier = llm_classifier

    def check_content_quality(self, title: str, summary: str) -> dict[str, Any]:
        """Structural analysis of content quality.

        Args:
            title: Article title
            summary: Article summary/content

        Returns:
            Dict with quality metrics
        """
        issues = []

        # Check title
        if not title or len(title) < MIN_TITLE_LENGTH:
            issues.append("title_too_short")

        # Check summary
        if not summary or len(summary) < MIN_SUMMARY_LENGTH:
            issues.append("summary_too_short")

        # Check sentence count
        sentences = re.split(r"[.!?]+", summary or "")
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) < MIN_SENTENCE_COUNT:
            issues.append("too_few_sentences")

        # Check for excessive hashtags
        text = f"{title} {summary}".lower()
        hashtag_count = len(re.findall(r"#\w+", text))
        word_count = len(text.split())
        if word_count > 0 and hashtag_count / word_count > MAX_HASHTAG_RATIO:
            issues.append("too_many_hashtags")

        # Check for URLs (excessive linking = often spam)
        url_count = len(re.findall(r"http[s]?://\S+", text))
        if url_count > 3:
            issues.append("too_many_urls")

        return {
            "quality_score": 1.0 - (len(issues) * 0.2),  # 0-1 score
            "issues": issues,
            "is_quality": len(issues) == 0,
        }

    def check_keyword_blacklist(self, title: str, summary: str) -> dict[str, Any]:
        """Check against spam keyword blacklist.

        Args:
            title: Article title
            summary: Article summary/content

        Returns:
            Dict with blacklist check results
        """
        text = f"{title} {summary}".lower()
        found_keywords = []

        for keyword in SPAM_KEYWORDS:
            if keyword in text:
                found_keywords.append(keyword)

        return {
            "is_spam": len(found_keywords) > 0,
            "spam_keywords": found_keywords,
            "spam_score": len(found_keywords) * 0.1,  # 0-1 scale
        }

    def detect_press_release(self, title: str, summary: str) -> dict[str, Any]:
        """Detect if content is a press release.

        Args:
            title: Article title
            summary: Article summary/content

        Returns:
            Dict with press release detection results
        """
        text = f"{title} {summary}".lower()
        found_indicators = []

        for indicator in PRESS_RELEASE_INDICATORS:
            if indicator in text:
                found_indicators.append(indicator)

        return {
            "is_press_release": len(found_indicators) > 0,
            "indicators": found_indicators,
            "confidence": min(len(found_indicators) * 0.4, 1.0),  # 0-1 scale
        }

    def detect_opinion(self, title: str, summary: str) -> dict[str, Any]:
        """Detect if content is opinion/analysis rather than news.

        Args:
            title: Article title
            summary: Article summary/content

        Returns:
            Dict with opinion detection results
        """
        text = f"{title} {summary}".lower()
        found_indicators = []

        for indicator in OPINION_INDICATORS:
            if indicator in text:
                found_indicators.append(indicator)

        return {
            "is_opinion": len(found_indicators) > 0,
            "indicators": found_indicators,
            "confidence": min(len(found_indicators) * 0.3, 1.0),  # 0-1 scale
        }

    def classify_with_llm(self, title: str, summary: str) -> dict[str, Any]:
        """Use LLM to classify content type.

        Args:
            title: Article title
            summary: Article summary/content

        Returns:
            Dict with LLM classification results
        """
        if not self.llm_classifier:
            return {"type": "unknown", "confidence": 0.0}

        try:
            result = self.llm_classifier(
                prompt=f"""Classify this news article into one category:
- news: factual news report
- spam: advertising, spam, or low-quality content
- press_release: official press release from a company
- opinion: opinion piece, analysis, or commentary

Title: {title}
Summary: {summary}

Return JSON with 'type' (news/spam/press_release/opinion) and 'confidence' (0-1).
"""
            )
            return result or {"type": "unknown", "confidence": 0.0}
        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")
            return {"type": "unknown", "confidence": 0.0}

    def evaluate_article(self, title: str, summary: str) -> dict[str, Any]:
        """Comprehensive evaluation of article quality and type.

        Args:
            title: Article title
            summary: Article summary/content

        Returns:
            Dict with complete evaluation including relevance score (0-1)
        """
        quality = self.check_content_quality(title, summary)
        blacklist = self.check_keyword_blacklist(title, summary)
        press_release = self.detect_press_release(title, summary)
        opinion = self.detect_opinion(title, summary)
        llm_classification = self.classify_with_llm(title, summary)

        # Determine final classification and relevance
        is_relevant = True
        article_type = "news"
        type_confidence = 0.0

        if blacklist["is_spam"]:
            is_relevant = False
            article_type = "spam"
            type_confidence = min(blacklist["spam_score"], 1.0)
        elif press_release["is_press_release"]:
            is_relevant = False
            article_type = "press_release"
            type_confidence = press_release["confidence"]
        elif opinion["is_opinion"]:
            is_relevant = True  # Keep opinions for now (can be informative)
            article_type = "opinion"
            type_confidence = opinion["confidence"]
        elif not quality["is_quality"]:
            is_relevant = False
            article_type = "low_quality"
            type_confidence = 1.0 - quality["quality_score"]
        elif llm_classification["type"] != "unknown":
            article_type = llm_classification["type"]
            type_confidence = llm_classification["confidence"]
            is_relevant = article_type == "news"

        # Calculate overall relevance score (0-1)
        relevance_score = (
            quality["quality_score"] * 0.3
            + (1.0 - blacklist["spam_score"]) * 0.3
            + (1.0 - press_release["confidence"]) * 0.2
            + (1.0 - opinion["confidence"]) * 0.2
        )

        return {
            "is_relevant": is_relevant,
            "relevance_score": max(0, min(1, relevance_score)),
            "article_type": article_type,
            "type_confidence": type_confidence,
            "quality": quality,
            "blacklist": blacklist,
            "press_release": press_release,
            "opinion": opinion,
            "llm_classification": llm_classification,
        }

    def filter_articles(self, articles: list[dict[str, Any]], db_session: Any) -> dict[str, Any]:
        """Filter a batch of articles and update database.

        Args:
            articles: List of article dicts with 'id', 'title', 'summary' keys
            db_session: Database session

        Returns:
            Stats dict with filtering results
        """
        from src.db.models import News

        stats = {
            "total": len(articles),
            "kept": 0,
            "spam": 0,
            "press_release": 0,
            "opinion": 0,
            "low_quality": 0,
        }

        for article in articles:
            try:
                evaluation = self.evaluate_article(
                    article.get("title", ""), article.get("summary", "")
                )

                # Update database
                news_obj = db_session.query(News).filter(News.id == article.get("id")).first()
                if news_obj:
                    news_obj.is_relevant = evaluation["is_relevant"]

                # Count by type
                if not evaluation["is_relevant"]:
                    article_type = evaluation["article_type"]
                    stats[article_type] = stats.get(article_type, 0) + 1
                else:
                    stats["kept"] += 1

            except Exception as e:
                logger.warning(f"Error filtering article {article.get('id')}: {e}")
                continue

        db_session.commit()
        logger.info(f"Filtering complete: {stats}")

        return stats
