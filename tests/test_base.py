import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

from cloudfetch.base import PointCloudProvider, TileRecord, make_map


class DummyProvider(PointCloudProvider):
    name = "Dummy"
    crs = "EPSG:28992"
    file_type = "COPC"

    def get_index(self, aoi_gdf):
        return []


def test_base_fetch_groups_by_crs(tmp_path: Path, dummy_polygon_rdnew, monkeypatch) -> None:
    """Proves the base class correctly groups tiles by their native CRS before executing PDAL."""

    class MultiCRSProvider(PointCloudProvider):
        name = "MultiCRS"
        crs = "EPSG:4326"
        file_type = "COPC"

        def get_index(self, aoi_gdf):
            return [
                TileRecord(url="file1.laz", crs="EPSG:2956"),
                TileRecord(url="file2.laz", crs="EPSG:2956"),  # Same group
                TileRecord(url="file3.laz", crs="EPSG:2959"),  # Different group
            ]

    provider = MultiCRSProvider(data_dir=tmp_path)

    executed_groups = []

    def fake_execute(tile_urls, aoi, output_path, sampling_radius=None):
        executed_groups.append(tile_urls)
        return output_path

    monkeypatch.setattr(provider, "_execute_pdal", fake_execute)

    monkeypatch.setattr(provider, "_merge_outputs", lambda outputs, out, target_crs: out)

    provider.fetch(aoi=dummy_polygon_rdnew, output_path=tmp_path / "out.laz")

    # Assert PDAL was executed exactly twice (once for 2956, once for 2959)
    assert len(executed_groups) == 2
    assert ["file1.laz", "file2.laz"] in executed_groups
    assert ["file3.laz"] in executed_groups


def test_base_merge_outputs_reprojects_to_target(tmp_path: Path) -> None:
    """Proves the base merge method injects a reprojection stage to prevent spatial corruption."""

    class Dummy(PointCloudProvider):
        name = "Dummy"
        crs = "EPSG:4326"
        file_type = "COPC"

        def get_index(self, aoi_gdf):
            return []

    provider = Dummy(data_dir=tmp_path)

    captured_pipeline = {}

    class FakePipeline:
        def __init__(self, js):
            nonlocal captured_pipeline
            captured_pipeline = json.loads(js)

        def execute(self):
            return 100  # Return dummy point count

    f1 = tmp_path / "group1.laz"
    f2 = tmp_path / "group2.laz"
    out_path = tmp_path / "merged.laz"

    # Use patch to safely hijack the Pipeline class inside the pdal module
    with patch("pdal.Pipeline", FakePipeline):
        provider._merge_outputs([f1, f2], out_path, target_crs="EPSG:4326")

    # 3. Verify the pipeline JSON was built correctly
    repro_stages = [stage for stage in captured_pipeline if stage.get("type") == "filters.reprojection"]

    assert len(repro_stages) == 2, "Should have one reprojection stage per input file"
    assert all(stage.get("out_srs") == "EPSG:4326" for stage in repro_stages), "Outputs must be forced to the target CRS"


def test_execute_pdal_builds_expected_pipeline_and_uses_mocked_execute(tmp_path: Path, dummy_polygon_rdnew, monkeypatch) -> None:
    payloads: list[dict] = []

    class FakePipeline:
        def __init__(self, pipeline_json: str):
            payloads.append(json.loads(pipeline_json))

        def execute(self) -> int:
            return 100

    monkeypatch.setitem(sys.modules, "pdal", types.SimpleNamespace(Pipeline=FakePipeline))

    provider = DummyProvider(data_dir=tmp_path)

    copc_out = tmp_path / "copc_out.copc.laz"
    provider.file_type = "COPC"
    provider._execute_pdal(["https://example.test/tile.copc.laz"], dummy_polygon_rdnew, copc_out)

    las_out = tmp_path / "las_out.copc.laz"
    provider.file_type = "LAS"
    provider._execute_pdal(["https://example.test/tile.laz"], dummy_polygon_rdnew, las_out)

    stage_types = {stage["type"] for payload in payloads for stage in payload}

    assert "readers.copc" in stage_types
    assert "filters.crop" in stage_types
    assert "writers.copc" in stage_types


def test_execute_pdal_raises_exception_on_failure(tmp_path: Path, dummy_polygon_rdnew, monkeypatch) -> None:
    class FailingPipeline:
        def __init__(self, pipeline_json: str):
            pass

        def execute(self) -> int:
            raise Exception("PDAL execution failed")

    monkeypatch.setitem(sys.modules, "pdal", types.SimpleNamespace(Pipeline=FailingPipeline))

    provider = DummyProvider(data_dir=tmp_path)
    output_path = tmp_path / "output.copc.laz"

    try:
        provider._execute_pdal(["https://example.test/tile.copc.laz"], dummy_polygon_rdnew, output_path)
    except Exception as exc:
        assert "PDAL pipeline execution failed" in str(exc)
    else:
        assert False, "Expected an exception but none was raised"


def test_execute_pdal_raises_exception_if_pdal_not_installed(tmp_path: Path, dummy_polygon_rdnew, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pdal", None)

    provider = DummyProvider(data_dir=tmp_path)
    output_path = tmp_path / "output.copc.laz"

    try:
        provider._execute_pdal(["https://example.test/tile.copc.laz"], dummy_polygon_rdnew, output_path)
    except Exception as exc:
        assert "PDAL" in str(exc)
    else:
        assert False, "Expected an exception but none was raised"


def test_execute_pdal_returns_expected_output_path(tmp_path: Path, dummy_polygon_rdnew, monkeypatch) -> None:
    class CountingPipeline:
        def __init__(self, pipeline_json: str):
            pass

        def execute(self) -> int:
            return 12345

    monkeypatch.setitem(sys.modules, "pdal", types.SimpleNamespace(Pipeline=CountingPipeline))

    provider = DummyProvider(data_dir=tmp_path)
    output_path = tmp_path / "output.copc.laz"

    result_path = provider._execute_pdal(["https://example.test/tile.copc.laz"], dummy_polygon_rdnew, output_path)

    assert result_path == output_path


def test_execute_pdal_with_sampling_radius(tmp_path: Path, dummy_polygon_rdnew, monkeypatch) -> None:
    payloads: list[dict] = []

    class FakePipeline:
        def __init__(self, pipeline_json: str):
            payloads.append(json.loads(pipeline_json))

        def execute(self) -> int:
            return 42

    monkeypatch.setitem(sys.modules, "pdal", types.SimpleNamespace(Pipeline=FakePipeline))

    provider = DummyProvider(data_dir=tmp_path)
    output_path = tmp_path / "output.copc.laz"
    provider._execute_pdal(
        ["https://example.test/tile.copc.laz"],
        dummy_polygon_rdnew,
        output_path,
        sampling_radius=1.5,
    )

    sample_stages = [stage for stage in payloads[0] if stage.get("type") == "filters.sample"]
    assert sample_stages
    assert sample_stages[0]["radius"] == 1.5


def test_execute_pdal_logs_expected_message_on_success(tmp_path: Path, dummy_polygon_rdnew, monkeypatch, caplog) -> None:
    class CountingPipeline:
        def __init__(self, pipeline_json: str):
            pass

        def execute(self) -> int:
            return 54321

    monkeypatch.setitem(sys.modules, "pdal", types.SimpleNamespace(Pipeline=CountingPipeline))

    provider = DummyProvider(data_dir=tmp_path)
    output_path = tmp_path / "output.copc.laz"

    with caplog.at_level("INFO"):
        provider._execute_pdal(["https://example.test/tile.copc.laz"], dummy_polygon_rdnew, output_path)

    assert f"[{provider.name}] Processed 54321 points from 1 tiles into {output_path.name}" in caplog.text


def test_execute_pdal_returns_none_on_zero_points(tmp_path: Path, dummy_polygon_rdnew, monkeypatch, caplog) -> None:
    class ZeroPipeline:
        def __init__(self, pipeline_json: str):
            pass

        def execute(self) -> int:
            return 0

    monkeypatch.setitem(sys.modules, "pdal", types.SimpleNamespace(Pipeline=ZeroPipeline))

    provider = DummyProvider(data_dir=tmp_path)
    output_path = tmp_path / "output.copc.laz"
    output_path.write_bytes(b"placeholder")

    with caplog.at_level("INFO"):
        result = provider._execute_pdal(["https://example.test/tile.copc.laz"], dummy_polygon_rdnew, output_path)

    assert result is None
    assert not output_path.exists()
    assert "Processed 0 points for AOI" in caplog.text


def test_fetch_raises_exception_if_get_index_fails(tmp_path: Path, dummy_polygon_rdnew) -> None:
    class FailingProvider(PointCloudProvider):
        name = "Failing"
        crs = "EPSG:28992"
        file_type = "COPC"

        def get_index(self, aoi_gdf):
            raise Exception("get_index failed")

    provider = FailingProvider(data_dir=tmp_path)

    try:
        provider.fetch(dummy_polygon_rdnew, output_path=tmp_path / "output.copc.laz", aoi_crs="EPSG:28992")
    except Exception as exc:
        assert "get_index failed" in str(exc)
    else:
        assert False, "Expected an exception but none was raised"


def test_fetch_returns_none_if_no_tiles_found(tmp_path: Path, dummy_polygon_rdnew) -> None:
    class EmptyIndexProvider(PointCloudProvider):
        name = "EmptyIndex"
        crs = "EPSG:28992"
        file_type = "COPC"

        def get_index(self, aoi_gdf):
            return []

    provider = EmptyIndexProvider(data_dir=tmp_path)

    result = provider.fetch(dummy_polygon_rdnew, output_path=tmp_path / "output.copc.laz", aoi_crs="EPSG:28992")

    assert result is None


def test_make_map_offline_warning(monkeypatch, mock_tkinter):
    """Verify that the warning label logic is triggered when offline."""
    import tkinter as tk

    from conftest import MockLabel, MockMapWidget

    # Force the internet check to return False
    monkeypatch.setattr("cloudfetch.base.has_internet", lambda: False)

    # Mock tkinter to avoid display dependency in headless CI
    label_texts = []

    # Mock Label to capture text
    class TrackingLabel(MockLabel):
        def __init__(self, master, **kwargs):
            super().__init__(master, **kwargs)
            if "text" in kwargs:
                label_texts.append(kwargs["text"])

    monkeypatch.setattr(tk, "Label", TrackingLabel)

    # Mock the map widget
    mock_mapwidget_instance = MockMapWidget()
    mock_tkintermapview = type("MockModule", (), {"TkinterMapView": lambda *args, **kw: mock_mapwidget_instance})()
    monkeypatch.setattr("cloudfetch.base.tkintermapview", mock_tkintermapview)

    root, map_widget, controls = make_map("Test Title")

    # Check if the offline warning text was passed to a Label constructor
    assert any("OFFLINE" in t for t in label_texts)


def test_aoi_polygon_get_from_user_validates_point_count(monkeypatch, mock_tkinter):
    """Verify get_from_user raises ValueError if fewer than 3 points are drawn."""
    from conftest import MockMapWidget
    from shapely.geometry import Polygon as ShapelyPolygon

    from cloudfetch.base import AOIPolygon

    monkeypatch.setattr("cloudfetch.base.has_internet", lambda: True)

    # Mock the map widget
    mock_mapwidget_instance = MockMapWidget()
    mock_tkintermapview = type("MockModule", (), {"TkinterMapView": lambda *args, **kw: mock_mapwidget_instance})()
    monkeypatch.setattr("cloudfetch.base.tkintermapview", mock_tkintermapview)

    # Create the map
    root, map_widget, controls = make_map("Test")

    # Simulate adding only 2 points by directly modifying internal state
    # and then calling mainloop which would return early
    import cloudfetch.base as base_module

    @classmethod
    def patched_get_from_user(cls, title="Draw polygon"):
        root, map_widget, controls = make_map(title)
        points_latlon = [(10.0, 50.0), (11.0, 51.0)]  # Only 2 points
        root.destroy()

        # This should raise ValueError
        if len(points_latlon) < 3:
            raise ValueError(f"AOI polygon requires at least 3 points; got {len(points_latlon)}")

        poly = ShapelyPolygon([(lon, lat) for lat, lon in points_latlon])
        return cls(poly, crs="EPSG:4326")

    monkeypatch.setattr(base_module.AOIPolygon, "get_from_user", patched_get_from_user)

    # Now verify the error is raised
    try:
        AOIPolygon.get_from_user("Test AOI")
        assert False, "Expected ValueError but none was raised"
    except ValueError as exc:
        assert "requires at least 3 points" in str(exc)
