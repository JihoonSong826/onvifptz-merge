"""Public errors intentionally omit URLs, credentials and device fault prose."""


class PtzError(Exception):
    pass


class ConfigurationError(PtzError):
    pass


class AuthenticationError(PtzError):
    pass


class TransportError(PtzError):
    """A request may have reached the camera even though no reply was received."""


class ProtocolError(PtzError):
    pass


class Unsupported(PtzError):
    pass


class NotReady(PtzError):
    pass


class Superseded(PtzError):
    """A pending command was replaced or invalidated by Stop."""


class Busy(PtzError):
    pass


class SoapFault(PtzError):
    def __init__(self, codes: tuple[str, ...]):
        self.codes = codes
        # Do not echo vendor fault text: it can contain secrets or request XML.
        super().__init__("ONVIF SOAP fault")

    def has(self, *names: str) -> bool:
        return any(code.rsplit(":", 1)[-1] in names for code in self.codes)
