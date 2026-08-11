import logging
import re
import zipfile
from pathlib import Path
from typing import List

import geopandas as gpd
import requests

from cloudfetch.base import PointCloudProvider, TileRecord
from cloudfetch.exceptions import ProviderFetchError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def download_file(url: str, dest_path: Path, timeout: int = 15, chunk_size: int = 8192) -> Path:
    """
    Downloads a file safely using streaming to prevent memory overload.
    Cleans up the destination file if the download fails or is interrupted.

    Parameters
    ----------
    url : str
        URL of the file to download.
    dest_path : Path
        Path to save the downloaded file.
    timeout : int, optional
        Timeout for the download request.
    chunk_size : int, optional
        Size of the chunks to download.

    Returns
    -------
    Path
        Path to the downloaded file.

    """
    try:
        # stream=True ensures we don't load 300MB GPKG files into RAM
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()  # Fails immediately on 404, 500, etc.

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)

        return dest_path

    except requests.exceptions.RequestException as exc:
        # Delete the file if it partially downloaded before the connection died
        if dest_path.exists():
            dest_path.unlink()

        raise ProviderFetchError("Network", f"Failed to download {url}: {exc}") from exc


def get_index(provider_name: str, index_dir: Path, index_url: str, index_cache_name: str) -> Path:
    """Downloads and caches a GPKG index file, extracting it from a ZIP if necessary.

    Parameters
    ----------
    provider_name : str
        Name of the provider.
    index_dir : Path
        Directory to cache the index file.
    index_url : str
        URL of the index file.
    index_cache_name : str
        Name of the cached index file.

    Returns
    -------
    Path
        Path to the local GPKG index file.
    """
    local_path = index_dir / f"{index_cache_name}.gpkg"

    if not local_path.exists():
        logger.info(f"[{provider_name}] Downloading index: {index_cache_name}...")
        if index_url.endswith(".zip"):
            tmp_zip = index_dir / f"{index_cache_name}.tmp.zip"
            try:
                download_file(index_url, tmp_zip)
                with zipfile.ZipFile(tmp_zip) as zf:
                    gpkg_name = next((n for n in zf.namelist() if n.endswith(".gpkg")), None)
                    if not gpkg_name:
                        raise ProviderFetchError(provider_name, f"Index archive {index_url} contains no .gpkg file.")
                    local_path.write_bytes(zf.read(gpkg_name))
            finally:
                if tmp_zip.exists():
                    tmp_zip.unlink()
        else:
            download_file(index_url, local_path)

    return local_path


def get_spatial_intersections(index_path: Path, aoi_gdf: gpd.GeoDataFrame, layer: str | None = None) -> gpd.GeoDataFrame:
    """Loads an index and performs a spatial intersection against an AOI.

    Parameters
    ----------
    index_path : Path
        Path to the index file.
    aoi_gdf : gpd.GeoDataFrame
        GeoDataFrame representing the AOI.
    layer : str, optional
        Optional layer name to filter the index.

    Returns
    -------
    gpd.GeoDataFrame
        GeoDataFrame of intersecting tiles.
    """
    target_crs = aoi_gdf.crs
    if not target_crs:
        raise ValueError("The provided AOI GeoDataFrame must have a valid CRS assigned.")

    index_gdf = gpd.read_file(
        index_path,
        layer=layer if layer else None,  # permissive for files with any number of layers
        mask=aoi_gdf,
    )

    if index_gdf.crs != target_crs:
        index_gdf = index_gdf.to_crs(target_crs)

    aoi_geom = gpd.GeoDataFrame(geometry=aoi_gdf.geometry, crs=target_crs)  # isolate geometry to avoid polluting columns

    joined_gdf = gpd.sjoin(index_gdf, aoi_geom, how="inner", predicate="intersects")

    if "index_right" in joined_gdf.columns:  # don't crash on empty intersection
        joined_gdf.drop(columns=["index_right"], inplace=True)

    return joined_gdf


class IGNLidarHD(PointCloudProvider):
    """Provider for IGN LiDAR HD tiles in France.
    The provider queries the public Géoplateforme WFS API
    and uses the official data.geopf.fr download endpoints.
    """

    name = "IGN_LIDAR_HD"
    crs = "EPSG:2154"
    file_type = "COPC"
    wfs_url = "https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle&OUTPUTFORMAT=application/json"

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[TileRecord]:
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
        return [TileRecord(url=url, crs=self.crs) for url in urls if url]


class OfficialAHNBase(PointCloudProvider):
    """Base class for official AHN COPC tiles."""

    crs = "EPSG:28992"
    file_type = "COPC"
    index_url = "https://basisdata.nl/hwh-ahn/AUX/bladwijzer_AHN6.gpkg"
    index_cache_name = "index_waterschapshuis"
    layer = "bladindeling_aoi"
    version: int

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[TileRecord]:
        """AHN 1x1 km tiles are named by their lower-left corner coordinates, so we query the index for intersecting tiles and construct URLs directly.

        Parameters
        ----------
        aoi_gdf : gpd.GeoDataFrame
            AOI geometries to query against the tile index.

        Returns
        -------
        List[TileRecord]
            List of tile URLs intersecting the AOI.

        """
        index_path = get_index(provider_name=self.name, index_dir=self.index_dir, index_url=self.index_url, index_cache_name=self.index_cache_name,)

        hits = get_spatial_intersections(index_path=index_path, aoi_gdf=aoi_gdf, layer=self.layer)

        if hits.empty:
            return []

        records: dict[str, TileRecord] = {}
        for row in hits.itertuples():
            # While Python's round() normally returns an int, calling it on a NumPy float 
            # returns a float (e.g. 123456.0). The int() cast strips the trailing .0
            x = str(int(round(row.left))).zfill(6)  # noqa: RUF046
            y = str(int(round(row.bottom))).zfill(6)  # noqa: RUF046

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
class AHN6(OfficialAHNBase):
    name = "AHN6"
    version = 6


class AHN5(OfficialAHNBase):
    name = "AHN5"
    version = 5


class AHN4(OfficialAHNBase):
    name = "AHN4"
    version = 4


class AHN3(OfficialAHNBase):
    name = "AHN3"
    version = 3


class AHN2(OfficialAHNBase):
    name = "AHN2"
    version = 2


class GeotilesAHNBase(PointCloudProvider):
    """Base class for Geotiles RGBI datasets."""

    crs = "EPSG:28992"
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
        index_path = get_index(
            provider_name=self.name,
            index_dir=self.index_dir,
            index_url=self.index_url,
            index_cache_name=self.index_cache_name,
        )

        hits = get_spatial_intersections(index_path=index_path, aoi_gdf=aoi_gdf, layer=self.layer)

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
class GeotilesAHN5(GeotilesAHNBase):
    name = "Geotiles_AHN5_RGBI"
    version = 5


class GeotilesAHN4(GeotilesAHNBase):
    name = "Geotiles_AHN4_RGBI"
    version = 4


class GeotilesAHN3(GeotilesAHNBase):
    name = "Geotiles_AHN3_RGBI"
    version = 3


class GeotilesAHN2(GeotilesAHNBase):
    name = "Geotiles_AHN2_RGBI"
    version = 2


class GeotilesAHN1(GeotilesAHNBase):
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
        index_path = get_index(
            provider_name=self.name,
            index_dir=self.index_dir,
            index_url=self.index_url,
            index_cache_name="nrcan_tile_index",
        )

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
                aoi_for_join[["geometry"]],  # type: ignore
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
