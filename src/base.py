import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

import geopandas as gpd
from shapely.geometry import Polygon

from .utils import get_logger, status_spinner, timed

logger = get_logger(name="Query")


class PointCloudProvider(ABC):
    """Abstract base class for all point cloud datasets."""

    name: str
    crs: str
    file_type: str

    def __init__(self, data_dir: Optional[Path | str] = None, fallback: Optional[List["PointCloudProvider"]] = None):
        self.data_dir = Path(data_dir) if data_dir else Path.cwd() / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.fallback = fallback or []

    @abstractmethod
    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> List[str]:
        """Returns a list of downloadable tile URLs."""
        pass

    def _execute_pdal(self, tile_urls: List[str], aoi: Polygon, output_path: Path) -> Path:
        try:
            import pdal  # type: ignore
        except ImportError as exc:
            raise RuntimeError("PDAL Python bindings are required to fetch point clouds. Install PDAL via the project's pixi environment.") from exc

        reader_type = "readers.copc" if self.file_type == "COPC" else "readers.las"
        stages = []
        merge_inputs = []

        for i, url in enumerate(tile_urls):
            reader_tag = f"reader_{i}"
            reader = {"type": reader_type, "filename": url, "tag": reader_tag}

            if self.file_type == "COPC":
                reader["polygon"] = aoi.wkt
                reader["requests"] = 64
                stages.append(reader)
                merge_inputs.append(reader_tag)
            else:
                crop_tag = f"crop_{i}"
                crop = {"type": "filters.crop", "polygon": aoi.wkt, "inputs": [reader_tag], "tag": crop_tag}
                stages.extend([reader, crop])
                merge_inputs.append(crop_tag)

        pipeline = stages + [
            {"type": "filters.merge", "inputs": merge_inputs},
            {"type": "writers.copc", "filename": str(output_path), "forward": "all", "offset_x": "auto", "offset_y": "auto", "offset_z": "auto"},
        ]

        with status_spinner(f"Processing {self.name} with PDAL ..."):
            count = pdal.Pipeline(json.dumps(pipeline)).execute()

        logger.info(f"[{self.name}] Processed {count} points from {len(tile_urls)} tiles into {output_path.name}")
        return output_path

    @timed("Pointcloud query")
    def fetch(self, aoi: Polygon, output_path: Optional[Path | str] = None, aoi_crs: str = "EPSG:28992") -> Optional[Path]:
        if output_path is None:
            output_path = self.data_dir / f"{self.name}_output.copc.laz"
        else:
            output_path = Path(output_path)

        gdf_aoi = gpd.GeoDataFrame(geometry=[aoi], crs=aoi_crs).to_crs(self.crs)

        # 1. Try the primary dataset
        try:
            tile_urls = self.get_index(gdf_aoi)
            if tile_urls:
                logger.info(f"[{self.name}] Found {len(tile_urls)} tiles. Downloading...")
                return self._execute_pdal(tile_urls, gdf_aoi.geometry.iloc[0], output_path)
            else:
                logger.warning(f"[{self.name}] No intersecting tiles found.")
        except Exception as exc:
            logger.warning(f"[{self.name}] failed: {exc}")
            if output_path.exists():
                output_path.unlink()

        # 2. Try the fallback chain
        if self.fallback:
            logger.info(f"[{self.name}] Initiating fallback chain...")
            for fallback_provider in self.fallback:
                # Sync the fallback's output directory to match the primary's
                if not getattr(fallback_provider, "_user_set_dir", False):
                    fallback_provider.data_dir = self.data_dir

                result = fallback_provider.fetch(aoi, output_path, aoi_crs)
                if result and result.exists():
                    return result

        logger.error("Primary dataset and all fallbacks failed.")
        return None
