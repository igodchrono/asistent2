# emotional_analyzer_v2.py — совместимость со старым импортом
# Реальная реализация: emotion_analyzer.EmotionalAnalyzer
from emotion_analyzer import EmotionalAnalyzer as EmotionalAnalyzerV2
from emotion_analyzer import EmotionalAnalyzer

__all__ = ["EmotionalAnalyzerV2", "EmotionalAnalyzer"]
