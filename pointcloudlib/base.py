import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

import geopandas as gpd
from shapely.geometry import Polygon

from .exceptions import PDALExecutionError, ProviderFetchError
from .utils import status_spinner, timed

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class PointCloudProvider(ABC):
    """Abstract base class for all point cloud datasets."""

    name: str
    crs: str
    file_type: str

    def __init__(self, data_dir: Path | str | None = None):
        self.data_dir = Path(data_dir) if data_dir else Path.cwd() / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> list[str]:
        """Returns a list of downloadable tile URLs."""
        pass

    def _execute_pdal(
        self,
        tile_urls: list[str],
        aoi: Polygon,
        output_path: Path,
        resolution: float | Literal["full"] = "full",
    ) -> Path:
        """Execute the PDAL pipeline to crop, merge, and write output data.

        Parameters
        ----------
        tile_urls : list[str]
            URLs or local paths to source point cloud tiles.
        aoi : Polygon
            Area-of-interest polygon in the provider CRS.
        output_path : Path
            Destination path for the COPC output.
        resolution : float | Literal["full"], default="full"
            Minimum point spacing for Poisson thinning in coordinate units.
            When provided, a ``filters.sample`` stage is injected after merge
            and before writing COPC output.

        Returns
        -------
        Path
            The output path written by PDAL.
        """
        try:
            import pdal  # type: ignore
        except ImportError as exc:
            raise PDALExecutionError(self.name, "PDAL Python bindings are required. Install PDAL via the project's pixi environment.") from exc

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

        pipeline = stages + [{"type": "filters.merge", "inputs": merge_inputs}]

        if resolution != "full":
            pipeline.append({"type": "filters.sample", "radius": resolution})

        pipeline.append(
            {
                "type": "writers.copc",
                "filename": str(output_path),
                "forward": "all",
                "offset_x": "auto",
                "offset_y": "auto",
                "offset_z": "auto",
            }
        )

        try:
            with status_spinner(f"Processing {self.name} with PDAL ..."):
                count = pdal.Pipeline(json.dumps(pipeline)).execute()
        except Exception as exc:
            raise PDALExecutionError(self.name, f"PDAL pipeline execution failed: {exc}") from exc

        logger.info(f"[{self.name}] Processed {count} points from {len(tile_urls)} tiles into {output_path.name}")
        return output_path

    @timed("Pointcloud query")
    def fetch(
        self,
        aoi: Polygon,
        output_path: Path | str | None = None,
        aoi_crs: str = "EPSG:28992",
        resolution: float | Literal["full"] = "full",
    ) -> Path | None:
        """Fetch point cloud data for an area of interest.

        Parameters
        ----------
        aoi : Polygon
            Area-of-interest geometry to query.
        output_path : Path | str | None, default=None
            Optional output file path for the resulting COPC file.
        aoi_crs : str, default="EPSG:28992"
            CRS of ``aoi``.
        resolution : float | Literal["full"], default="full"
            Minimum point spacing for Poisson thinning in coordinate units.
            When provided, fetch applies PDAL ``filters.sample`` before writing.

        Returns
        -------
        Path | None
            Output path if data was fetched, otherwise ``None`` when no tiles
            intersect the AOI.
        """
        if output_path is None:
            output_path = self.data_dir / f"{self.name}_output.copc.laz"
        else:
            output_path = Path(output_path)

        gdf_aoi = gpd.GeoDataFrame(geometry=[aoi], crs=aoi_crs).to_crs(self.crs)
        tile_urls = self.get_index(gdf_aoi)

        if not tile_urls:
            logger.warning(f"[{self.name}] No intersecting tiles found.")
            return None

        logger.info(f"[{self.name}] Found {len(tile_urls)} tiles. Downloading...")
        try:
            return self._execute_pdal(tile_urls, gdf_aoi.geometry.iloc[0], output_path, resolution=resolution)
        except Exception:
            if output_path.exists():
                output_path.unlink()
            raise


class ProviderChain(PointCloudProvider):
    """
    A composite provider that tries multiple providers in sequence
    until one successfully fetches the data.
    """

    # Give the chain its own required class attributes
    name = "ProviderChain"
    crs = "Multiple"
    file_type = "Mixed"

    def __init__(self, providers: list[PointCloudProvider], data_dir: Path | str | None = None):
        super().__init__(data_dir=data_dir)
        self.providers = providers

    def get_index(self, aoi_gdf: gpd.GeoDataFrame) -> list[str]:
        # A chain doesn't have a single index, so we can raise a NotImplementedError.
        raise NotImplementedError("Call fetch() directly on a ProviderChain.")

    def fetch(
        self,
        aoi: Polygon,
        output_path: Path | str | None = None,
        aoi_crs: str = "EPSG:28992",
        resolution: float | Literal["full"] = "full",
    ) -> Path | None:
        """Try providers in sequence until one fetch succeeds.

        Parameters
        ----------
        aoi : Polygon
            Area-of-interest geometry to query.
        output_path : Path | str | None, default=None
            Optional output file path for the resulting COPC file.
        aoi_crs : str, default="EPSG:28992"
            CRS of ``aoi``.
        resolution : float | Literal["full"], default="full"
            Minimum point spacing for Poisson thinning in coordinate units.
            Forwarded to child provider fetch calls.

        Returns
        -------
        Path | None
            Output path of the first successful provider, otherwise ``None``.
        """
        target_path = Path(output_path) if output_path is not None else None
        target_dir = target_path.parent if target_path is not None else self.data_dir
        failures: list[str] = []

        for provider in self.providers:
            # Sync the child provider's data directory with the chain's target
            provider.data_dir = target_dir

            try:
                result = provider.fetch(aoi=aoi, output_path=target_path, aoi_crs=aoi_crs, resolution=resolution)
            except Exception as exc:
                failures.append(str(exc))
                continue

            if result and result.exists():
                return result

        if failures:
            raise ProviderFetchError(self.name, "All providers failed: " + " | ".join(failures))

        return None
