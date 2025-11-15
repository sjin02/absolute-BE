"""
API 공통 의존성 (싱글톤 패턴)
"""

from fastapi import Depends
from app.services.recommend_service import RecommendationService
from app.services.geo_service import GeoService
from app.services.report_service import LLMReportService


# 싱글톤 인스턴스 저장
_recommendation_service_instance = None
_geo_service_instance = None
_report_service_instance = None


def get_recommendation_service() -> RecommendationService:
    """추천 서비스 의존성 (싱글톤)"""
    global _recommendation_service_instance
    
    if _recommendation_service_instance is None:
        print("🔥 RecommendationService 최초 초기화 중...")
        _recommendation_service_instance = RecommendationService()
        print("✅ 초기화 완료 - 이후 모든 요청에서 재사용")
    
    return _recommendation_service_instance


def get_geo_service() -> GeoService:
    """지리 정보 서비스 의존성 (싱글톤)"""
    global _geo_service_instance

    if _geo_service_instance is None:
        print("🔥 GeoService 최초 초기화 중...")
        _geo_service_instance = GeoService()
        print("✅ 초기화 완료 - 이후 모든 요청에서 재사용")

    return _geo_service_instance


def get_report_service() -> LLMReportService:
    """LLM 보고서 서비스 의존성 (싱글톤)"""

    global _report_service_instance

    if _report_service_instance is None:
        print("🤖 LLMReportService 최초 초기화 중...")
        _report_service_instance = LLMReportService()
        print("✅ LLMReportService 초기화 완료")

    return _report_service_instance
