from pydantic import BaseModel
from typing import Optional, Dict

class ContainerConfig(BaseModel):
    image: str
    name: Optional[str]
    env: Optional[Dict[str, str]] = {}
    cpu: float  # e.g., 0.2
    memory: str  # e.g., "512m"
    ports: Optional[Dict[str, int]] = {}  # e.g., {"5000/tcp": 8080} or {"8000/tcp": 0} for auto-assignment

