class PointCloudLibError(RuntimeError):
    """Base exception for pointcloudlib errors."""


class ProviderFetchError(PointCloudLibError):
    """Raised when a provider fails to fetch data for an AOI."""

    def __init__(self, provider_name: str, message: str):
        self.provider_name = provider_name
        self.message = message
        super().__init__(f"[{provider_name}] {message}")


class PDALExecutionError(PointCloudLibError):
    """Raised when PDAL execution fails for a provider."""

    def __init__(self, provider_name: str, message: str):
        self.provider_name = provider_name
        self.message = message
        super().__init__(f"[{provider_name}] {message}")
