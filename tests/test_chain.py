from pathlib import Path

from cloudfetch.base import PointCloudProvider, ProviderChain


class MockProviderA(PointCloudProvider):
    name = "A"
    crs = "EPSG:28992"
    file_type = "COPC"

    def get_index(self, aoi_gdf):
        return []

    def fetch(self, aoi, output_path=None, aoi_crs="EPSG:28992", sampling_radius=None):
        raise Exception("provider A failed")


class MockProviderB(PointCloudProvider):
    name = "B"
    crs = "EPSG:28992"
    file_type = "COPC"

    def get_index(self, aoi_gdf):
        return []

    def fetch(self, aoi, output_path=None, aoi_crs="EPSG:28992", sampling_radius=None):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ok")
        return path


def test_provider_chain_uses_second_provider_on_first_failure(dummy_polygon_rdnew, tmp_path: Path) -> None:
    out_path = tmp_path / "result.copc.laz"
    chain = ProviderChain([MockProviderA(), MockProviderB()], data_dir=tmp_path)

    result = chain.fetch(dummy_polygon_rdnew, output_path=out_path, aoi_crs="EPSG:28992")

    assert result == out_path
    assert out_path.exists()


def test_provider_chain_raises_exception_if_all_providers_fail(dummy_polygon_rdnew, tmp_path: Path) -> None:
    out_path = tmp_path / "result.copc.laz"
    chain = ProviderChain([MockProviderA(), MockProviderA()], data_dir=tmp_path)

    try:
        chain.fetch(dummy_polygon_rdnew, output_path=out_path, aoi_crs="EPSG:28992")
    except Exception as exc:
        assert "All providers failed" in str(exc)
    else:
        assert False, "Expected an exception but none was raised"


def test_provider_chain_get_index_raises_not_implemented():
    chain = ProviderChain([MockProviderA(), MockProviderB()])
    try:
        chain.get_index(None)
    except NotImplementedError as exc:
        assert "Call fetch() directly on a ProviderChain" in str(exc)
    else:
        assert False, "Expected NotImplementedError but none was raised"


def test_provider_chain_syncs_data_dir_with_child_providers(dummy_polygon_rdnew, tmp_path: Path) -> None:
    out_path = tmp_path / "result.copc.laz"
    provider_a = MockProviderA(data_dir=tmp_path)
    provider_b = MockProviderB(data_dir=tmp_path)
    chain = ProviderChain([provider_a, provider_b], data_dir=tmp_path)

    chain.fetch(dummy_polygon_rdnew, output_path=out_path, aoi_crs="EPSG:28992")

    assert provider_a.data_dir == tmp_path
    assert provider_b.data_dir == tmp_path
    assert provider_a.index_dir == tmp_path / "indices"
    assert provider_b.index_dir == tmp_path / "indices"
    assert provider_a.index_dir.exists()
    assert provider_b.index_dir.exists()


def test_provider_chain_raises_exception_if_all_providers_fail_with_different_errors(dummy_polygon_rdnew, tmp_path: Path) -> None:
    out_path = tmp_path / "result.copc.laz"

    class MockProviderC(PointCloudProvider):
        name = "C"
        crs = "EPSG:28992"
        file_type = "COPC"

        def get_index(self, aoi_gdf):
            return []

        def fetch(self, aoi, output_path=None, aoi_crs="EPSG:28992", sampling_radius=None):
            raise Exception("provider C failed")

    chain = ProviderChain([MockProviderA(), MockProviderC()], data_dir=tmp_path)

    try:
        chain.fetch(dummy_polygon_rdnew, output_path=out_path, aoi_crs="EPSG:28992")
    except Exception as exc:
        assert "All providers failed" in str(exc)
        assert "provider A failed" in str(exc)
        assert "provider C failed" in str(exc)
    else:
        assert False, "Expected an exception but none was raised"


def test_provider_chain_returns_none_if_all_providers_return_none(dummy_polygon_rdnew, tmp_path: Path) -> None:
    out_path = tmp_path / "result.copc.laz"

    class MockProviderD(PointCloudProvider):
        name = "D"
        crs = "EPSG:28992"
        file_type = "COPC"

        def get_index(self, aoi_gdf):
            return []

        def fetch(self, aoi, output_path=None, aoi_crs="EPSG:28992", sampling_radius=None):
            return None

    chain = ProviderChain([MockProviderD(), MockProviderD()], data_dir=tmp_path)

    result = chain.fetch(dummy_polygon_rdnew, output_path=out_path, aoi_crs="EPSG:28992")

    assert result is None


def test_provider_chain_returns_first_successful_result(dummy_polygon_rdnew, tmp_path: Path) -> None:
    out_path = tmp_path / "result.copc.laz"

    class MockProviderE(PointCloudProvider):
        name = "E"
        crs = "EPSG:28992"
        file_type = "COPC"

        def get_index(self, aoi_gdf):
            return []

        def fetch(self, aoi, output_path=None, aoi_crs="EPSG:28992", sampling_radius=None):
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"ok from E")
            return path

    class MockProviderF(PointCloudProvider):
        name = "F"
        crs = "EPSG:28992"
        file_type = "COPC"

        def get_index(self, aoi_gdf):
            return []

        def fetch(self, aoi, output_path=None, aoi_crs="EPSG:28992", sampling_radius=None):
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"ok from F")
            return path

    chain = ProviderChain([MockProviderE(), MockProviderF()], data_dir=tmp_path)

    result = chain.fetch(dummy_polygon_rdnew, output_path=out_path, aoi_crs="EPSG:28992")

    assert result == out_path
    assert out_path.exists()
    assert out_path.read_bytes() == b"ok from E"


def test_provider_chain_syncs_index_dir_with_custom_output_path(dummy_polygon_rdnew, tmp_path: Path) -> None:
    """Verify index_dir is synced when using a custom output path outside chain data_dir."""
    # Use a custom output location different from chain's data_dir
    custom_output_dir = tmp_path / "custom_output"
    out_path = custom_output_dir / "result.copc.laz"

    # Use provider A (fails) then B (succeeds) to test sync on attempted providers
    provider_a = MockProviderA(data_dir=tmp_path)
    provider_b = MockProviderB(data_dir=tmp_path)
    chain = ProviderChain([provider_a, provider_b], data_dir=tmp_path)

    # Fetch to a completely different output directory
    result = chain.fetch(dummy_polygon_rdnew, output_path=out_path, aoi_crs="EPSG:28992")

    # Verify result was written to custom location
    assert result == out_path
    assert out_path.exists()

    # Verify both providers' index directories were synced to custom_output_dir
    # (A is synced before failing, B is synced before succeeding)
    assert provider_a.data_dir == custom_output_dir
    assert provider_b.data_dir == custom_output_dir
    assert provider_a.index_dir == custom_output_dir / "indices"
    assert provider_b.index_dir == custom_output_dir / "indices"
    assert provider_a.index_dir.exists()
    assert provider_b.index_dir.exists()
