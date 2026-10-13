from typing import Protocol


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable


class AIProvider(Protocol):
    name: str
    model: str

    def classify(self, title: str, description: str) -> str:
        """Return untrusted JSON text; caller must validate it."""
        ...
