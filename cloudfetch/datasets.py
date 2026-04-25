import logging
import re
import urllib.request
import zipfile
from pathlib import Path
from typing import List

import geopandas as gpd
import requests

from .base import PointCloudProvider
from .exceptions import ProviderFetchError
from .utils import download_file

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class IGNLidarHD(PointCloudProvider):
    name = "IGN_LIDAR_HD"
    crs = "EPSG:2154"
    file_type = "COPC"
    wfs_url = "https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle&OUTPUTFORMAT=application/json"

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[str]:
        bounds = aoi_gdf.total_bounds
        crs_code = self.crs.split(":")[1]
        bbox_str = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]},urn:ogc:def:crs:EPSG::{crs_code}"

        request_url = f"{self.wfs_url}&BBOX={bbox_str}"
        index_gdf = gpd.read_file(request_url)
        if index_gdf.empty:
            return []

        urls = list(dict.fromkeys(index_gdf["url"].dropna().tolist()))
        return [self._rewrite_to_ovh(url) for url in urls if self._rewrite_to_ovh(url)]

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
    """Internal base class for Dutch AHN datasets to handle GPKG downloads."""

    index_url: str
    index_cache_name: str
    layer: str
    crs = "EPSG:28992"

    def _download_index(self) -> Path:
        local_path = self.data_dir / f"{self.index_cache_name}.gpkg"
        if not local_path.exists():
            logger.info(f"Downloading index: {self.index_cache_name}...")
            if self.index_url.endswith(".zip"):
                tmp_zip = self.data_dir / "tmp_index.zip"
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


class AHN6(AHNProvider):
    name = "AHN6"
    file_type = "COPC"
    index_url = "https://basisdata.nl/hwh-ahn/AUX/bladwijzer_AHN6.gpkg"
    index_cache_name = "index_waterschapshuis"
    layer = "bladindeling"
    base_url = "https://fsn1.your-objectstorage.com/hwh-ahn/AHN6/01_LAZ/"

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[str]:
        hits = self._get_intersecting_hits(aoi_gdf)
        if hits.empty:
            return []

        urls = []
        for _, row in hits.iterrows():
            x = str(int(row["left"])).zfill(6)
            y = str(int(row["bottom"])).zfill(6)
            urls.append(f"{self.base_url}AHN6_2025_C_{x}_{y}.COPC.LAZ")
        return list(dict.fromkeys(urls))


class AHNArchive(AHNProvider):
    """Dynamic class for older AHN archives (1-5)."""

    file_type = "LAS"
    index_url = "https://static.fwrite.org/2022/01/index_sheets.gpkg_.zip"
    index_cache_name = "index_geotiles"
    layer = "AHN_subunits"

    def __init__(self, version: int, **kwargs):
        super().__init__(**kwargs)
        self.name = f"AHN{version}"
        self.base_url = f"https://geotiles.citg.tudelft.nl/AHN{version}_T"

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[str]:
        hits = self._get_intersecting_hits(aoi_gdf)
        if hits.empty:
            return []

        valid_urls = []
        for tile in dict.fromkeys(hits["GT_AHNSUB"]):
            url = f"{self.base_url}/{tile}.LAZ"
            try:
                # Protect PDAL from crashing on HTML 404 pages
                if requests.head(url, timeout=5).status_code == 200:
                    valid_urls.append(url)
            except requests.RequestException:
                pass

        return valid_urls


# Expose clean wrappers for the user
class AHN5(AHNArchive):
    def __init__(self, **kwargs):
        super().__init__(version=5, **kwargs)


class AHN4(AHNArchive):
    def __init__(self, **kwargs):
        super().__init__(version=4, **kwargs)


class AHN3(AHNArchive):
    def __init__(self, **kwargs):
        super().__init__(version=3, **kwargs)


class AHN2(AHNArchive):
    def __init__(self, **kwargs):
        super().__init__(version=2, **kwargs)


class AHN1(AHNArchive):
    def __init__(self, **kwargs):
        super().__init__(version=1, **kwargs)


class CanElevation(PointCloudProvider):
    """
    Provider for Canadian Elevation Point Clouds (NRCan).
    Uses the master TILE index and UTM Zone 18N for Ottawa/Eastern Canada.
    """

    name = "CanElevation"
    # Setting this to 2959 ensures the fetch() method reprojects
    # the AOI into the correct UTM meters for the PDAL crop.
    crs = "EPSG:2959"
    file_type = "COPC"
    index_url = "https://canelevation-lidar-point-clouds.s3-ca-central-1.amazonaws.com/pointclouds_nuagespoints/Index_LiDARtiles_tuileslidar.gpkg"

    def _download_index(self) -> Path:
        """Downloads the master tile index."""
        local_path = self.data_dir / "nrcan_tile_index.gpkg"

        if not local_path.exists():
            logger.info(f"[{self.name}] Downloading master TILE index...")
            download_file(self.index_url, local_path)

        return local_path

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[str]:
        index_path = self._download_index()
        aoi_for_join = aoi_gdf.to_crs("EPSG:4617")

        logger.info(f"[{self.name}] Querying tile index for AOI...")
        index_gdf = gpd.read_file(index_path, mask=aoi_for_join)

        if index_gdf.empty:
            logger.warning(f"[{self.name}] No tiles found for this AOI.")
            return []

        if "Year" in index_gdf.columns:
            index_gdf = index_gdf.sort_values("Year", ascending=False)

        url_col = "URL" if "URL" in index_gdf.columns else "url"
        if url_col not in index_gdf.columns:
            raise ProviderFetchError(self.name, "NRCan index missing URL column.")

        urls = index_gdf[url_col].dropna().unique().tolist()
        return [u for u in urls if u.lower().endswith((".laz", ".copc"))]
