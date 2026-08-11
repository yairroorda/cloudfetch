from pathlib import Path

import geopandas as gpd
import pandas as pd

from cloudfetch.datasets import CanElevation, OfficialAHNBase


class DummyAHNProvider(OfficialAHNBase):
    """Concrete subclass of OfficialAHNBase for testing URL generation."""

    name = "ahn5"
    version = 5
    layer = "01_LAZ"
    index_dir = ""
    index_url = ""
    index_cache_name = ""


def test_can_elevation_get_index_extracts_urls(dummy_aoi_gdf, tmp_path: Path, monkeypatch) -> None:
    provider = CanElevation(data_dir=tmp_path)
    monkeypatch.setattr("cloudfetch.datasets.get_index", lambda *args, **kwargs: tmp_path / "nrcan_tile_index.gpkg")
    fake_index = gpd.GeoDataFrame(
        {
            "URL": ["https://fake.laz", "https://fake2.laz"],
            "Year": [2020, 2019],
        },
        geometry=[dummy_aoi_gdf.geometry.iloc[0], dummy_aoi_gdf.geometry.iloc[0]],
        crs="EPSG:4617",
    )

    monkeypatch.setattr(gpd, "read_file", lambda *args, **kwargs: fake_index)

    records = provider.get_index(dummy_aoi_gdf)

    urls = [record.url for record in records]
    assert urls == ["https://fake.laz", "https://fake2.laz"]


def test_can_elevation_resolve_record_crs_from_utm_zone(tmp_path: Path) -> None:
    provider = CanElevation(data_dir=tmp_path)

    crs = provider._resolve_record_crs(
        "AB_Edmonton2018_20180426_NAD83CSRS_UTMZ12_1km_E3790_N58940_CLASS",
        "https://example.test/AB_Edmonton2018_20180426_NAD83CSRS_UTMZ12_1km_E3790_N58940_CLASS.copc.laz",
    )

    assert crs == "EPSG:2956"


def test_can_elevation_resolve_record_crs_from_longitude_fallback(tmp_path: Path) -> None:
    provider = CanElevation(data_dir=tmp_path)

    crs = provider._resolve_record_crs(
        "1km173230465902017LLAKEERIE",
        "https://example.test/pointcloud.copc.laz",
        longitude=-113.49,
    )

    # The tile name doesn't contain UTM zone info, so it should fall back to longitude-based CRS resolution.
    # Given the longitude of -113.49, it should resolve to UTM zone 12N, which corresponds to EPSG:2956.
    assert crs == "EPSG:2956"


def test_ahn_tile_url_integer_coordinates(dummy_aoi_gdf, monkeypatch) -> None:
    """Test that AHN tile URL coordinates are formatted as integers without trailing .0 floats."""
    monkeypatch.setattr("cloudfetch.datasets.get_index", lambda *args, **kwargs: "dummy_path")

    # Simulate a pandas row where coordinates come through as floats (e.g., 168000.0, 427000.0)
    mock_hits = pd.DataFrame({
        "left": [168000.0],
        "bottom": [427000.0],
    })
    monkeypatch.setattr("cloudfetch.datasets.get_spatial_intersections", lambda *args, **kwargs: mock_hits)

    provider = DummyAHNProvider()
    records = provider.get_index(dummy_aoi_gdf)

    assert len(records) == 1
    expected_url = "https://basisdata.nl/hwh-ahn/AHN5_KM/01_LAZ/AHN5_C_168000_427000.COPC.LAZ"

    assert records[0].url == expected_url
    assert ".0_" not in records[0].url
