from urllib.parse import urlparse
from errors.global_exception_handler import AgentMartException
from ipaddress import ip_address


class ApiValidator:
    """
    Validates Apis before they are executed
    """

    _ALLOWED_PROTOCOLS = ["http", "https"]

    def validate(self, url: str):
        parsed = urlparse(url)

        if parsed.scheme not in self._ALLOWED_PROTOCOLS:
            raise AgentMartException(
                f"Supported protocols are {self._ALLOWED_PROTOCOLS}", status_code=400
            )

        if not parsed.hostname:
            raise AgentMartException(f"API URL must contain a valid hostname")

        hostname = parsed.hostname.lower()
        return self._validate_ip(hostname)

    @staticmethod
    def _validate_ip(
        hostname: str,
    ) -> None:

        try:
            address = ip_address(hostname)

        except ValueError:
            # Normal DNS hostname.
            return

        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise AgentMartException(
                f"IP address '{hostname}' is not allowed.", status_code=400
            )
