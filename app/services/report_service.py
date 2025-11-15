"""LLM 기반 보고서 생성을 위한 서비스 모듈."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


class LLMReportService:
    """LLM을 활용해 주유소 보고서를 생성하는 서비스."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv(
            "LLM_API_URL", "https://api.openai.com/v1/chat/completions"
        )
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        try:
            default_timeout = float(os.getenv("LLM_TIMEOUT", "30"))
        except ValueError:
            default_timeout = 30.0
        self.timeout = timeout or default_timeout
        self.force_json_response = os.getenv("LLM_FORCE_JSON", "true").lower() != "false"
        try:
            self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
        except ValueError:
            self.temperature = 0.3
        self.routing_table = self._load_routing_table()

    def _load_routing_table(self) -> Dict[str, Dict[str, Any]]:
        raw_table = os.getenv("LLM_ROUTING_TABLE")
        data: Optional[Dict[str, Any]] = None

        if raw_table:
            try:
                parsed = json.loads(raw_table)
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError as exc:
                print(f"LLM 라우팅 테이블 파싱 실패: {exc}")

        if data is None:
            routing_file = os.getenv("LLM_ROUTING_FILE")
            if routing_file:
                try:
                    with Path(routing_file).expanduser().open("r", encoding="utf-8") as fp:
                        parsed = json.load(fp)
                    if isinstance(parsed, dict):
                        data = parsed
                except Exception as exc:
                    print(f"LLM 라우팅 파일 로드 실패: {exc}")

        if not data:
            return {}

        table: Dict[str, Dict[str, Any]] = {}
        for key, value in data.items():
            if isinstance(value, dict):
                table[str(key)] = value

        return table

    def _resolve_route(self, station_id: Optional[int]) -> Dict[str, Any]:
        defaults = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "force_json": self.force_json_response,
            "temperature": self.temperature,
        }

        if not self.routing_table:
            return defaults

        candidate: Optional[Dict[str, Any]] = None
        if station_id is not None:
            candidate = self.routing_table.get(str(station_id))

        if candidate is None:
            candidate = (
                self.routing_table.get("*")
                or self.routing_table.get("default")
                or self.routing_table.get("DEFAULT")
            )

        if not candidate:
            return defaults

        merged = defaults.copy()
        for key, value in candidate.items():
            if key in {"timeout", "temperature"}:
                try:
                    merged[key] = float(value)
                except (TypeError, ValueError):
                    continue
            elif key == "force_json":
                merged[key] = self._normalise_bool(value)
            else:
                merged[key] = value

        return merged

    @staticmethod
    def _normalise_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).lower() not in {"false", "0", "no"}

    async def generate_report(
        self,
        station: Dict[str, Any],
        recommendations: List[Dict[str, Any]],
        parcel_summary: Optional[Dict[str, Any]] = None,
        station_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """보고서에 포함할 요약/인사이트/실행항목을 반환한다."""

        route_config = self._resolve_route(station_id)
        llm_response = await self._request_llm(
            station,
            recommendations,
            parcel_summary,
            route_config,
            station_id,
        )
        if llm_response:
            parsed = self._parse_llm_response(llm_response)
            if parsed:
                return parsed

        return self._fallback_report(station, recommendations, parcel_summary)

    async def _request_llm(
        self,
        station: Dict[str, Any],
        recommendations: List[Dict[str, Any]],
        parcel_summary: Optional[Dict[str, Any]],
        route_config: Dict[str, Any],
        station_id: Optional[int],
    ) -> Optional[str]:
        """LLM API 호출. 실패 시 None."""

        api_key = route_config.get("api_key")
        if not api_key:
            return None

        station_summary = self._summarise_station(station)
        recommendation_summary = self._summarise_recommendations(recommendations)
        parcel_context = self._format_parcel_summary(parcel_summary)
        station_ref = station.get("상호") or station.get("name") or "해당 주유소"
        station_identifier = f"ID {station_id} - {station_ref}" if station_id is not None else station_ref

        user_prompt = (
            "당신은 도시 재생 및 부동산 활용 전략을 제시하는 컨설턴트입니다. 아래 주유소 정보를 분석하여 "
            "입지 특성 요약(2~3문장), 인사이트 3개, 권장 실행 항목 3개를 JSON으로만 응답하세요.\n"
            "JSON 키는 summary(문장), insights(문장 리스트), actions(문장 리스트)입니다.\n"
            "모든 문장은 한국어 비즈니스 보고서 어투로 작성하고, 다른 설명이나 마크다운은 포함하지 마세요.\n\n"
            f"[대상 주유소] {station_identifier}\n"
            f"[주유소 정보]\n{station_summary}\n\n"
            f"[추천 활용 방안]\n{recommendation_summary}\n"
            f"[반경 300m 필지 통계]\n{parcel_context}\n"
        )

        messages = [
            {
                "role": "system",
                "content": "도시 입지 분석을 수행하는 한국어 컨설턴트입니다.",
            },
            {"role": "user", "content": user_prompt},
        ]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": route_config.get("model", self.model),
            "messages": messages,
            "temperature": route_config.get("temperature", self.temperature),
        }
        if route_config.get("force_json", self.force_json_response):
            payload["response_format"] = {"type": "json_object"}

        try:
            timeout_value = route_config.get("timeout", self.timeout)
            async with httpx.AsyncClient(timeout=timeout_value) as client:
                response = await client.post(
                    route_config.get("base_url", self.base_url),
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content", "")
            return content.strip() or None
        except Exception as exc:  # pragma: no cover - 네트워크 예외 처리
            print(f"LLM 보고서 생성 실패: {exc}")
            return None

    def _parse_llm_response(self, content: str) -> Optional[Dict[str, Any]]:
        """LLM 응답을 JSON으로 파싱."""

        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").lstrip("json").strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return None

        summary = str(data.get("summary", "")).strip()
        insights = [str(item).strip() for item in data.get("insights", []) if str(item).strip()]
        actions = [str(item).strip() for item in data.get("actions", []) if str(item).strip()]

        if not summary and not insights and not actions:
            return None

        return {
            "summary": summary,
            "insights": insights,
            "actions": actions,
        }

    def _format_parcel_summary(self, summary: Optional[Dict[str, Any]]) -> str:
        if not summary:
            return "반경 내 필지 데이터가 충분하지 않습니다."

        bucket_counts = summary.get("bucket_counts", {})
        bucket_line = ", ".join(
            f"{label} {bucket_counts.get(label, 0)}개"
            for label in ["소형", "중형", "대형", "초대형"]
            if bucket_counts.get(label)
        )

        lines = [
            f"총 {summary.get('total_count', 0)}개 필지, 평균 면적 약 {summary.get('average_area', 0):.0f}㎡",
        ]
        if bucket_line:
            lines.append(f"면적 분포: {bucket_line}")

        top_land_uses = summary.get("top_land_uses") or []
        if top_land_uses:
            uses_text = ", ".join(
                f"{item.get('use')} {item.get('count')}개"
                for item in top_land_uses
                if item.get("use")
            )
            if uses_text:
                lines.append(f"주요 지목: {uses_text}")

        closest = summary.get("closest") or {}
        distance = closest.get("distance_m")
        if distance:
            label = closest.get("label") or "가장 인접 필지"
            lines.append(f"지도 중심과 {distance:.0f}m 거리의 {label}")

        return "\n".join(lines)

    def _fallback_report(
        self,
        station: Dict[str, Any],
        recommendations: List[Dict[str, Any]],
        parcel_summary: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """LLM 호출이 실패했을 때의 기본 보고서."""

        name = station.get("상호") or station.get("name") or "해당 주유소"
        address = station.get("주소") or station.get("address") or "-"
        land_use = station.get("용도지역") or station.get("토지용도") or station.get("지목") or "정보 없음"
        area = station.get("대지면적") or station.get("면적") or station.get("AREA")

        summary_parts = [
            f"{name}({address}) 부지에 대한 기초 입지 진단입니다.",
            f"주요 용도지역은 '{land_use}'로 파악되며 주변 토지이용과의 연계를 고려해야 합니다.",
        ]
        if area:
            summary_parts.append(f"확인된 대지 면적 정보: {area}.")

        parcel_phrase = self._describe_parcel_summary(parcel_summary)
        if parcel_phrase:
            summary_parts.append(parcel_phrase)

        insights: List[str] = []
        if recommendations:
            top_type = recommendations[0].get("type") or recommendations[0].get("usage_type")
            if top_type:
                insights.append(f"추천 데이터 상 우선 검토가 필요한 용도는 '{top_type}' 유형입니다.")
        insights.append("주변 상권 밀도와 교통 접근성을 정량 분석해 수요 포착 범위를 확장할 필요가 있습니다.")
        insights.append("지자체 개발계획 및 도시재생 사업과의 연계를 검토해 정책 수혜 가능성을 확보해야 합니다.")
        insights.append("기존 주유소 설비 전환 시 공사 기간·안전관리·환경영향을 체계적으로 관리할 필요가 있습니다.")

        actions = [
            "현장 실사를 통해 용도지역·지구단위계획 등 인허가 요건을 세부 확인합니다.",
            "추천 활용 방안 대비 수익성·투자비·수요를 시나리오별로 비교 분석합니다.",
            "지자체 및 인근 이해관계자와의 협력 방안을 마련해 추진 동력을 확보합니다.",
        ]

        return {
            "summary": " ".join(summary_parts),
            "insights": insights,
            "actions": actions,
        }

    def _describe_parcel_summary(
        self, parcel_summary: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        if not parcel_summary:
            return None

        total = parcel_summary.get("total_count")
        if not total:
            return None

        average_area = parcel_summary.get("average_area") or 0
        bucket_counts = parcel_summary.get("bucket_counts", {})
        small = bucket_counts.get("소형", 0)
        medium = bucket_counts.get("중형", 0)
        large = bucket_counts.get("대형", 0)
        xlarge = bucket_counts.get("초대형", 0)

        phrases = [
            f"반경 300m 내 필지 {total}개, 평균 면적 약 {average_area:.0f}㎡가 확인됩니다."
        ]

        distribution_bits = []
        if small:
            distribution_bits.append(f"소형 {small}개")
        if medium:
            distribution_bits.append(f"중형 {medium}개")
        if large:
            distribution_bits.append(f"대형 {large}개")
        if xlarge:
            distribution_bits.append(f"초대형 {xlarge}개")
        if distribution_bits:
            phrases.append("면적 분포는 " + ", ".join(distribution_bits) + " 수준입니다.")

        top_land_uses = parcel_summary.get("top_land_uses") or []
        if top_land_uses:
            lead = top_land_uses[0]
            if lead.get("use"):
                phrases.append(
                    f"주요 지목은 '{lead['use']}' 계열이 두드러집니다."
                )

        closest = parcel_summary.get("closest") or {}
        distance = closest.get("distance_m")
        label = closest.get("label")
        if distance:
            phrases.append(
                f"지도 중심과 약 {distance:.0f}m 거리에 위치한 {label or '인접 필지'}가 핵심 앵커로 활용될 수 있습니다."
            )

        return " ".join(phrases)

    def _summarise_station(self, station: Dict[str, Any]) -> str:
        """보고서 프롬프트에 활용할 핵심 정보 정리."""

        keys_of_interest = [
            "상호",
            "주소",
            "지번주소",
            "용도지역",
            "지목",
            "대지면적",
            "연면적",
            "주용도",
            "준공일자",
            "폐업일자",
        ]

        parts = []
        for key in keys_of_interest:
            value = station.get(key)
            if value:
                parts.append(f"{key}: {value}")

        lat = station.get("위도")
        lng = station.get("경도")
        if lat and lng:
            parts.append(f"위치: 위도 {lat}, 경도 {lng}")

        if not parts:
            return "제공된 세부 정보가 거의 없습니다."

        return " | ".join(parts)

    def _summarise_recommendations(self, recommendations: List[Dict[str, Any]]) -> str:
        if not recommendations:
            return "추천 결과 없음"

        lines = []
        for item in recommendations:
            usage = item.get("type") or item.get("usage_type") or "미정"
            score = item.get("score") or item.get("similarity") or item.get("rank")
            description = item.get("description")
            line = usage
            if score is not None:
                try:
                    line += f" (점수: {float(score):.3f})"
                except (TypeError, ValueError):
                    line += f" (점수: {score})"
            if description:
                line += f" - {description}"
            lines.append(line)

        return "\n".join(lines[:5])
