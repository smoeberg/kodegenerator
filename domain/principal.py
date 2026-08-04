# domain/principal.py
"""
Principal Domain Model

Represents an authenticated identity (typically from JWT).
The Principal is the entry point for all identity-related operations in DOR.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime
import uuid


@dataclass
class Principal:
    """
    Represents an authenticated identity (JWT subject).
    
    The Principal is the first-class representation of an authenticated user,
    service, or API key. It serves as the foundation for all authorization
    and access control decisions in DOR.
    
    Attributes:
        id: Unique identifier (UUID or external ID from OAuth/SSO)
        type: Type of principal ("user", "service", "api_key")
        name: Optional human-readable name
        email: Optional email address
        metadata: Additional context (claims from JWT)
        created_at: When the Principal was first authenticated
        updated_at: When the Principal was last updated
    """
    id: str
    type: str  # "user", "service", "api_key"
    name: Optional[str] = None
    email: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def from_jwt(cls, jwt_payload: Dict[str, Any]) -> "Principal":
        """
        Create a Principal from a JWT payload.
        
        This is the primary way to create a Principal in DOR, as most
        authentication flows will use JWT tokens.
        
        Args:
            jwt_payload: The decoded JWT payload (from jwt.decode())
            
        Returns:
            A new Principal instance
            
        Example:
            >>> from jwt import decode
            >>> token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
            >>> payload = decode(token, "secret", algorithms=["HS256"])
            >>> principal = Principal.from_jwt(payload)
        """
        return cls(
            id=jwt_payload.get("sub", str(uuid.uuid4())),
            type=jwt_payload.get("type", "user"),
            name=jwt_payload.get("name"),
            email=jwt_payload.get("email"),
            metadata={k: v for k, v in jwt_payload.items() 
                     if k not in ["sub", "type", "name", "email", "exp", "iat", "nbf"]}
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert Principal to dictionary for serialization."""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "email": self.email,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Principal":
        """Create Principal from dictionary."""
        return cls(
            id=data["id"],
            type=data["type"],
            name=data.get("name"),
            email=data.get("email"),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.utcnow()
        )

    def __str__(self) -> str:
        """String representation of Principal."""
        return f"Principal(id={self.id}, type={self.type}, name={self.name}, email={self.email})"

    def __repr__(self) -> str:
        """Official representation of Principal."""
        return f"Principal(id={self.id!r}, type={self.type!r}, name={self.name!r})"
