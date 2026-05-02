import json
import sys
import tkinter as tk
import types
from pathlib import Path

from cloudfetch.base import PointCloudProvider, make_map


class DummyProvider(PointCloudProvider):
    name = "Dummy"
    crs = "EPSG:28992"
    file_type = "COPC"

    def get_index(self, aoi_gdf):
        return []


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


def test_execute_pdal_with_resolution(tmp_path: Path, dummy_polygon_rdnew, monkeypatch) -> None:
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
        resolution=1.5,
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


def test_make_map_offline_warning(monkeypatch):
    """Verify that the warning label logic is triggered when offline."""
    # Force the internet check to return False
    monkeypatch.setattr("cloudfetch.base.has_internet", lambda: False)

    # Mock tkinter to avoid opening actual windows during tests
    # We check if Label is called with the expected 'OFFLINE' text
    label_texts = []
    original_label = tk.Label

    def mock_label(master, **kwargs):
        if "text" in kwargs:
            label_texts.append(kwargs["text"])
        return original_label(master, **kwargs)

    monkeypatch.setattr(tk, "Label", mock_label)

    # We must mock root.mainloop or the test will hang
    monkeypatch.setattr(tk.Tk, "mainloop", lambda self: None)

    root, map_widget, controls = make_map("Test Title")

    # Check if the offline warning text was passed to a Label constructor
    assert any("OFFLINE" in t for t in label_texts)

    root.destroy()
