import logging
import re
import urllib.request
import zipfile
from pathlib import Path
from typing import List

import geopandas as gpd
import requests
from pandas.core.arrays import base

from cloudfetch.base import PointCloudProvider, TileRecord
from cloudfetch.exceptions import ProviderFetchError
from cloudfetch.utils import download_file

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class IGNLidarHD(PointCloudProvider):
    """Provider for IGN LiDAR HD tiles in France.

    The provider queries the public WFS index and rewrites tile URLs to the
    OVH object storage mirror used for downloads.
    """

    name = "IGN_LIDAR_HD"
    crs = "EPSG:2154"
    file_type = "COPC"
    wfs_url = "https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle&OUTPUTFORMAT=application/json"

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[str]:
        # reproject AOI to match index CRS for accurate spatial querying
        if aoi_gdf.crs != self.crs:
            aoi_gdf = aoi_gdf.to_crs(self.crs)

        bounds = aoi_gdf.total_bounds
        crs_code = self.crs.split(":")[1]
        bbox_str = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]},urn:ogc:def:crs:EPSG::{crs_code}"

        request_url = f"{self.wfs_url}&BBOX={bbox_str}"
        index_gdf = gpd.read_file(request_url)
        if index_gdf.empty:
            return []

        urls = list(dict.fromkeys(index_gdf["url"].dropna().tolist()))
        rewritten_urls = [self._rewrite_to_ovh(url) for url in urls]
        return [TileRecord(url=url, crs=self.crs) for url in rewritten_urls if url]

    def _rewrite_to_ovh(self, url: str) -> str | None:
        OVH_BASE_URL = "https://storage.sbg.cloud.ovh.net/v1/AUTH_63234f509d6048bca3c9fd7928720ca1/ppk-lidar/"
        orig_filename = url.split("/")[-1]
        match = re.search(r"LAMB93_([A-Z]{2})_", url)
        subfolder = match.group(1) if match else ""

        for letter in ["O", "C"]:
            filename = orig_filename.replace("PTS_LAMB93", f"PTS_{letter}_LAMB93")
            test_url = f"{OVH_BASE_URL}{subfolder}/{filename}"
            try:
                response = requests.head(test_url, timeout=5)
                if response.status_code == 200:
                    return test_url
            except requests.RequestException:
                continue
        return None


class AHNProvider(PointCloudProvider):
    """Base class for Dutch AHN datasets backed by a GPKG tile index.

    Subclasses define the dataset-specific index location and tile naming
    scheme.
    """

    index_url: str
    index_cache_name: str
    layer: str
    crs = "EPSG:28992"

    def _download_index(self) -> Path:
        local_path = self.index_dir / f"{self.index_cache_name}.gpkg"
        if not local_path.exists():
            logger.info(f"Downloading index: {self.index_cache_name}...")
            if self.index_url.endswith(".zip"):
                tmp_zip = self.index_dir / "tmp_index.zip"
                urllib.request.urlretrieve(self.index_url, tmp_zip)
                with zipfile.ZipFile(tmp_zip) as zf:
                    gpkg_name = next(n for n in zf.namelist() if n.endswith(".gpkg"))
                    local_path.write_bytes(zf.read(gpkg_name))
                tmp_zip.unlink()
            else:
                urllib.request.urlretrieve(self.index_url, local_path)
        return local_path

    def _get_intersecting_hits(self, aoi_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        index_path = self._download_index()
        kwargs = {"layer": self.layer} if self.layer else {}
        index_gdf = gpd.read_file(index_path, **kwargs)

        if index_gdf.crs != aoi_gdf.crs:
            index_gdf = index_gdf.to_crs(aoi_gdf.crs)

        return gpd.sjoin(index_gdf, aoi_gdf[["geometry"]], how="inner", predicate="intersects")


class _OfficialAHNBase(AHNProvider):
    """Base class for official AHN COPC tiles."""

    file_type = "COPC"
    index_url = "https://basisdata.nl/hwh-ahn/AUX/bladwijzer_AHN6.gpkg"
    index_cache_name = "index_waterschapshuis"
    layer = "bladindeling_aoi"
    version: int

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[TileRecord]:
        """AHN6 tiles are named by their lower-left corner coordinates, so we query the index for intersecting tiles and construct URLs directly.

        Parameters
        ----------
        aoi_gdf : gpd.GeoDataFrame
            AOI geometries to query against the tile index.

        Returns
        -------
        List[TileRecord]
            List of tile URLs intersecting the AOI.

        """
        hits = self._get_intersecting_hits(aoi_gdf)
        if hits.empty:
            return []

        records: dict[str, TileRecord] = {}
        for _, row in hits.iterrows():
            x = str(int(row["left"])).zfill(6)
            y = str(int(row["bottom"])).zfill(6)
            # Dynamically build the URL via basisdata.nl proxy
            if self.version == 6:
                url = f"https://basisdata.nl/hwh-ahn/AHN6/01_LAZ/AHN6_2025_C_{x}_{y}.COPC.LAZ"
            else:
                url = f"https://basisdata.nl/hwh-ahn/AHN{self.version}_KM/01_LAZ/AHN{self.version}_C_{x}_{y}.COPC.LAZ"

            # Validate that the tile actually exists on the server before passing to PDAL
            if url not in records:
                try:
                    # Allow redirects since basisdata proxies to object storage
                    if requests.head(url, timeout=5, allow_redirects=True).status_code == 200:
                        records[url] = TileRecord(url=url, crs=self.crs)
                except requests.RequestException:
                    pass

        return list(records.values())


# Official AHN COPC (Uncolored)
class AHN6(_OfficialAHNBase):
    name = "AHN6"
    version = 6


class AHN5(_OfficialAHNBase):
    name = "AHN5"
    version = 5


class AHN4(_OfficialAHNBase):
    name = "AHN4"
    version = 4


class AHN3(_OfficialAHNBase):
    name = "AHN3"
    version = 3


class AHN2(_OfficialAHNBase):
    name = "AHN2"
    version = 2


class _GeotilesAHNBase(AHNProvider):
    """Base class for Geotiles RGBO datasets.

    Parameters
    ----------
    version : int
        AHN archive version number used to build the dataset name and base
        URL.
    """

    file_type = "LAS"
    index_url = "https://static.fwrite.org/2022/01/index_sheets.gpkg_.zip"
    index_cache_name = "index_geotiles"
    layer = "AHN_subunits"
    version: int

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[TileRecord]:
        """AHN 1-5 archive tiles are indexed by their GT_AHNSUB sheet name, which we can use to construct LAZ URLs directly.

        Parameters
        ----------
        aoi_gdf : gpd.GeoDataFrame
            AOI geometries to query against the tile index.

        Returns
        -------
        List[TileRecord]
            List of tile URLs intersecting the AOI.

        """
        hits = self._get_intersecting_hits(aoi_gdf)
        if hits.empty:
            return []

        valid_urls = []
        base_url = f"https://geotiles.citg.tudelft.nl/AHN{self.version}_T"
        for tile in dict.fromkeys(hits["GT_AHNSUB"]):
            url = f"{base_url}/{tile}.LAZ"
            try:
                # Protect PDAL from crashing on HTML 404 pages
                if requests.head(url, timeout=5).status_code == 200:
                    valid_urls.append(url)
            except requests.RequestException:
                pass

        return [TileRecord(url=url, crs=self.crs) for url in valid_urls]


# Geotiles AHN LAZ (RGBI Colored)
class GeotilesAHN5(_GeotilesAHNBase):
    name = "Geotiles_AHN5_RGBI"
    version = 5


class GeotilesAHN4(_GeotilesAHNBase):
    name = "Geotiles_AHN4_RGBI"
    version = 4


class GeotilesAHN3(_GeotilesAHNBase):
    name = "Geotiles_AHN3_RGBI"
    version = 3


class GeotilesAHN2(_GeotilesAHNBase):
    name = "Geotiles_AHN2_RGBI"
    version = 2


class GeotilesAHN1(_GeotilesAHNBase):
    name = "Geotiles_AHN1_RGBI"
    version = 1


class CanElevation(PointCloudProvider):
    """
    Provider for Canadian Elevation Point Clouds (NRCan).
    Uses the master TILE index and UTM Zone 18N for Ottawa/Eastern Canada.
    """

    name = "CanElevation"
    # The NRCan index is geographic NAD83(CSRS). Individual point-cloud
    # projects are often in different projected CRSs (commonly UTM zones),
    # so crop CRS must be resolved per tile/project.
    crs = "EPSG:4617"
    file_type = "COPC"
    index_url = "https://canelevation-lidar-point-clouds.s3-ca-central-1.amazonaws.com/pointclouds_nuagespoints/Index_LiDARtiles_tuileslidar.gpkg"
    _utm_epsg_map: dict[int, str] | None = None

    def _download_index(self) -> Path:
        """Downloads the master tile index."""
        local_path = self.index_dir / "nrcan_tile_index.gpkg"

        if not local_path.exists():
            logger.info(f"[{self.name}] Downloading master TILE index...")
            download_file(self.index_url, local_path)

        return local_path

    @staticmethod
    def _build_nad83_csrs_utm_epsg_map() -> dict[int, str]:
        """Build mapping for NAD83(CSRS) UTM zone -> EPSG code."""
        from pyproj.database import query_crs_info

        mapping: dict[int, str] = {}
        for info in query_crs_info(auth_name="EPSG"):
            match = re.fullmatch(r"NAD83\(CSRS\) / UTM zone (\d{1,2})N", info.name)
            if match:
                mapping[int(match.group(1))] = f"EPSG:{info.code}"
        return mapping

    @classmethod
    def _get_nad83_csrs_utm_epsg(cls, zone: int) -> str | None:
        if cls._utm_epsg_map is None:
            cls._utm_epsg_map = cls._build_nad83_csrs_utm_epsg_map()
        return cls._utm_epsg_map.get(zone)

    @staticmethod
    def _extract_utm_zone(text: str) -> int | None:
        # Handles patterns like UTMZ12 and UTM17
        match = re.search(r"UTM(?:Z|_)?(\d{1,2})(?!\d)", text, flags=re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _utm_zone_from_longitude(lon: float) -> int | None:
        if lon < -180 or lon > 180:
            return None
        return int((lon + 180) // 6) + 1  # 60 UTM zones of 6 degrees each globally

    def _resolve_record_crs(self, tile_name: str, url: str, longitude: float | None = None) -> str:
        # Gather potential zone integer sources in order of preference
        potential_zones = (
            self._extract_utm_zone(tile_name or ""),  # try to extract zone from tile name
            self._extract_utm_zone(url or ""),  # try to extract zone from URL
            self._utm_zone_from_longitude(longitude) if longitude is not None else None,  # try to infer zone from longitude if available
        )

        # Lazily get the first valid zone
        zone = next((z for z in potential_zones if z is not None), None)

        # Perform EPSG lookup for the zone if found
        if zone is not None:
            epsg = self._get_nad83_csrs_utm_epsg(zone)
            if epsg:
                return epsg

        # If we can't resolve a specific projected CRS, log a warning and default to the master index CRS.
        logger.warning(f"[{self.name}] Could not resolve CRS for record (tile_name='{tile_name}', url='{url}'). Defaulting to master index CRS {self.crs}.")
        return self.crs

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[TileRecord]:
        index_path = self._download_index()
        aoi_for_join = aoi_gdf.to_crs("EPSG:4617")

        logger.info(f"[{self.name}] Querying tile index for AOI...")
        index_gdf = gpd.read_file(index_path, layer="index_lidartiles_tuileslidar", mask=aoi_for_join)

        # Match AOI CRS to the exact index CRS object to avoid false-positive
        # CRS mismatch warnings when equivalent definitions use different text.
        if not index_gdf.empty and index_gdf.crs is not None:
            aoi_for_join = aoi_for_join.to_crs(index_gdf.crs)

        # `mask` is a coarse pre-filter at IO level; apply exact geometry
        # intersection to remove occasional false positives.
        if not index_gdf.empty:
            index_gdf = gpd.sjoin(
                index_gdf,
                aoi_for_join[["geometry"]],
                how="inner",
                predicate="intersects",
            )
            index_gdf = index_gdf.drop(columns=["index_right"], errors="ignore")
        else:
            logger.warning(f"[{self.name}] No tiles found for this AOI.")
            return []

        if "Year" in index_gdf.columns:
            index_gdf = index_gdf.sort_values("Year", ascending=False)

        url_col = "URL" if "URL" in index_gdf.columns else "url"
        if url_col not in index_gdf.columns:
            raise ProviderFetchError(self.name, "NRCan index missing URL column.")

        tile_name_col = "Tile_name" if "Tile_name" in index_gdf.columns else "tile_name"

        unique_records: dict[str, TileRecord] = {}

        for _, row in index_gdf.iterrows():
            url = row.get(url_col)
            # Skip if URL is missing or doesn't look like a point cloud file
            if not isinstance(url, str) or not url.lower().endswith((".laz", ".copc")):
                continue

            # Skip if we already processed this URL
            if url in unique_records:
                continue

            tile_name = str(row.get(tile_name_col, ""))

            # Safe centroid calculation
            record_lon = None
            if row.geometry and not row.geometry.is_empty:
                record_lon = float(row.geometry.centroid.x)

            unique_records[url] = TileRecord(
                url=url,
                crs=self._resolve_record_crs(tile_name, url, longitude=record_lon),
            )

        return list(unique_records.values())
