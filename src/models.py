from pydantic import BaseModel


class SummarizeRequest(BaseModel):
    github_url: str


class SummarizeResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str
