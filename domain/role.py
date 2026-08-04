# domain/role.py
"""
Role Domain Model

Defines positions with capabilities, responsibilities, authority, and constraints.
Roles are assigned to Actors and determine what they can do in DOR.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import uuid


@dataclass
class RoleDefinition:
    """
    Defines a position (skills, responsibilities, authority, constraints).
    
    Roles are the mechanism by which Actors are granted capabilities and authority.
    Each Role defines:
    - What capabilities are required
    - What actions the Role can perform (authority)
    - What actions require approval from other Roles
    - What responsibilities the Role has
    
    Attributes:
        id: Unique identifier for the Role
        name: Human-readable name (e.g., "Senior AI Engineer")
        description: Description of the Role
        department_id: Optional ID of the Department this Role belongs to
        team_id: Optional ID of the Team this Role belongs to
        capabilities: List of Capability IDs required for this Role
        authority: What this Role can do (e.g., {"can_approve": True, "can_reject": False})
        needs_approval_from: What requires approval (e.g., {"merge_to_main": ["architecture_reviewer", "qa"]})
        responsibilities: List of responsibilities
        organization: The Organization this Role belongs to
        created_at: When the Role was created
        updated_at: When the Role was last updated
    """
    id: str
    name: str
    description: str = ""
    department_id: Optional[str] = None
    team_id: Optional[str] = None
    
    # Capabilities (list of capability IDs)
    capabilities: List[str] = field(default_factory=list)
    
    # Authority (what the role can do)
    authority: Dict[str, bool] = field(default_factory=dict)
    
    # Approval requirements (what requires approval)
    needs_approval_from: Dict[str, List[str]] = field(default_factory=dict)
    
    # Responsibilities
    responsibilities: List[str] = field(default_factory=list)
    
    # Relationships
    organization: Optional["Organization"] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Initialize with default ID if not provided."""
        if not hasattr(self, 'id') or self.id is None:
            object.__setattr__(self, 'id', str(uuid.uuid4()))

    def add_capability(self, capability_id: str) -> None:
        """
        Add a Capability ID to this Role.
        
        Args:
            capability_id: The ID of the Capability to add
        """
        if capability_id not in self.capabilities:
            self.capabilities.append(capability_id)
            self.updated_at = datetime.utcnow()

    def can_perform(self, action: str) -> bool:
        """
        Check if this Role can perform a given action.
        
        Args:
            action: The action to check (e.g., "approve", "reject", "merge")
            
        Returns:
            bool: True if the Role has authority to perform the action
        """
        return self.authority.get(f"can_{action}", False)

    def get_required_approvals(self, action: str) -> List[str]:
        """
        Get the list of Roles that must approve a given action.
        
        Args:
            action: The action to check
            
        Returns:
            List[str]: List of Role IDs that must approve
        """
        return self.needs_approval_from.get(action, [])

    def to_dict(self) -> Dict[str, any]:
        """Convert RoleDefinition to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "department_id": self.department_id,
            "team_id": self.team_id,
            "capabilities": self.capabilities,
            "authority": self.authority,
            "needs_approval_from": {
                k: v for k, v in self.needs_approval_from.items()
            },
            "responsibilities": self.responsibilities,
            "organization_id": self.organization.id if self.organization else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, any], **kwargs) -> "RoleDefinition":
        """Create RoleDefinition from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data["name"],
            description=data.get("description", ""),
            department_id=data.get("department_id"),
            team_id=data.get("team_id"),
            capabilities=data.get("capabilities", []),
            authority=data.get("authority", {}),
            needs_approval_from=data.get("needs_approval_from", {}),
            responsibilities=data.get("responsibilities", []),
            organization=None,  # Will be set separately
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.utcnow(),
            **kwargs
        )

    def __str__(self) -> str:
        """String representation of RoleDefinition."""
        return f"RoleDefinition(id={self.id}, name={self.name})"

    def __repr__(self) -> str:
        """Official representation of RoleDefinition."""
        return f"RoleDefinition(id={self.id!r}, name={self.name!r})"
