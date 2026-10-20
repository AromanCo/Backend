import uuid

from pydantic import BaseModel, ConfigDict


class NamedDemoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    is_demo: bool
