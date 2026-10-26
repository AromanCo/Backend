from fastapi import HTTPException


class CodedForbidden(HTTPException):
    """A 403 response with a stable top-level code and string detail."""

    def __init__(self, detail: str, code: str) -> None:
        super().__init__(status_code=403, detail=detail)
        self.code = code
