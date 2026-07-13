from pathlib import Path

import pytest
import requests
import responses

from cloudfetch.datasets import download_file
from cloudfetch.exceptions import ProviderFetchError


@responses.activate
def test_download_file_happy_path(tmp_path: Path) -> None:
    url = "https://example.test/file.gpkg"
    expected = b"dummy-bytes"
    dest = tmp_path / "file.gpkg"

    responses.add(responses.GET, url, body=expected, status=200)

    result = download_file(url, dest)

    assert result == dest
    assert dest.read_bytes() == expected


@responses.activate
def test_download_file_404_raises_provider_fetch_error(tmp_path: Path) -> None:
    url = "https://example.test/missing.gpkg"
    dest = tmp_path / "missing.gpkg"

    responses.add(responses.GET, url, status=404)

    with pytest.raises(ProviderFetchError):
        download_file(url, dest)


@responses.activate
def test_download_file_connection_interruption_deletes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.test/interrupted.gpkg"
    dest = tmp_path / "interrupted.gpkg"
    dest.write_bytes(b"partial")

    calls: list[Path] = []
    original_unlink = Path.unlink

    def spy_unlink(path_obj: Path, *args, **kwargs):
        calls.append(path_obj)
        return original_unlink(path_obj, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", spy_unlink)

    responses.add(
        responses.GET,
        url,
        body=requests.exceptions.ConnectionError("connection dropped"),
    )

    with pytest.raises(ProviderFetchError):
        download_file(url, dest)

    assert not dest.exists()
    assert any(path == dest for path in calls)
