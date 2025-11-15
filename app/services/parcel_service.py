# app/services/parcel_service.py

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from app.services.geoai_config import GeoAIConfig

_logger = logging.getLogger(__name__)


class ParcelService:
    """지적도(필지) 데이터 조회 유틸리티.

    실제 서비스 환경에서는 시/도 단위의 SHP 파일을 로드해 사용하지만, 개발 머신에는
    해당 데이터가 없을 수 있으므로 최대한 관대한 실패 처리를 수행한다.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.cfg = GeoAIConfig()
        self.base_dir = Path(base_dir or self.cfg.parcel_base_dir)
        self.cache: Dict[str, gpd.GeoDataFrame] = {}  # 시도코드 → geodataframe
        self._is_loaded = False
        self._last_error: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        """로딩된 지적도 데이터가 있는지 여부."""

        return self._is_loaded and bool(self.cache)

    @property
    def last_error(self) -> Optional[str]:
        """마지막 로딩 시도 중 발생한 오류 메시지."""

        return self._last_error

    def _record_error(self, message: str) -> None:
        self._last_error = message
        _logger.warning(message)

    def load_parcels(self, sidocode: str) -> gpd.GeoDataFrame:
        """시/도 코드를 기준으로 SHP 파일을 로드한다."""

        if sidocode in self.cache:
            return self.cache[sidocode]

        folder = self.base_dir / sidocode
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"지적도 디렉터리를 찾을 수 없습니다: {folder}")

        shp_files = [f for f in os.listdir(folder) if f.endswith(".shp")]
        if not shp_files:
            raise FileNotFoundError(f"SHP 파일이 존재하지 않습니다: {folder}")

        shp_path = folder / shp_files[0]
        gdf = gpd.read_file(shp_path)
        gdf = gdf.to_crs(epsg=4326)

        self.cache[sidocode] = gdf
        if not gdf.empty:
            self._is_loaded = True
            self._last_error = None

        return gdf

    def _ensure_any_dataset(self) -> None:
        """최초 접근 시 사용 가능한 데이터셋을 하나라도 불러온다."""

        if self.cache:
            return

        if not self.base_dir.exists():
            self._record_error(f"지적도 기본 경로가 존재하지 않습니다: {self.base_dir}")
            return

        for entry in sorted(self.base_dir.iterdir()):
            if entry.is_dir():
                try:
                    self.load_parcels(entry.name)
                    return
                except Exception as exc:  # pragma: no cover - 파일 의존 오류
                    self._record_error(f"지적도 로드 실패({entry.name}): {exc}")
                    continue

        if not self.cache:
            self._record_error("사용 가능한 지적도 데이터가 없습니다.")

    def get_nearby_parcels(
        self, lat: float, lng: float, radius: float = 0.003
    ) -> gpd.GeoDataFrame:
        """지정 반경 내 필지 정보를 조회한다.

        데이터가 준비되지 않은 경우 빈 GeoDataFrame을 반환한다.
        """

        self._ensure_any_dataset()

        if not self.cache:
            # geopandas와 folium의 호환을 위해 geometry 컬럼만 있는 빈 DF 반환
            return gpd.GeoDataFrame(columns=["geometry"])

        search_point = Point(lng, lat)
        results = []

        for sidocode, gdf in self.cache.items():
            try:
                nearby = gdf[gdf.geometry.distance(search_point) <= radius]
            except Exception as exc:  # pragma: no cover - geometry 오류
                self._record_error(f"필지 거리 계산 실패({sidocode}): {exc}")
                continue

            if not nearby.empty:
                results.append(nearby)

        if not results:
            # 구조를 유지하기 위해 첫 번째 데이터프레임의 컬럼을 따름
            first_gdf = next(iter(self.cache.values()))
            return gpd.GeoDataFrame(columns=first_gdf.columns)

        concatenated = pd.concat(results, ignore_index=True)
        return gpd.GeoDataFrame(concatenated, geometry="geometry", crs=results[0].crs)


_parcel_service_instance: Optional[ParcelService] = None


def get_parcel_service() -> ParcelService:
    """ParcelService 싱글톤 인스턴스."""

    global _parcel_service_instance

    if _parcel_service_instance is None:
        _parcel_service_instance = ParcelService()

    return _parcel_service_instance
