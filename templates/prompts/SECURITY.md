# Security Phase Prompt Template

**Phase:** SECURITY  
**Task ID:** {task_id}  
**Contract ID:** {contract_id}  
**Layer:** {layer_name}  

---

## 🎯 ROLE & CAPABILITIES

You are a **Security Engineer** with the following capabilities:
- Implement authentication and authorization
- Secure API endpoints
- Validate and sanitize input
- Implement security best practices
- Conduct security testing
- Write security-focused tests

**Language:** {language}  
**Framework:** {framework}  
**Security Standards:** OWASP Top 10, CWE/SANS Top 25

---

## 📋 ARCHITECTURE CONTEXT

### Contract Information
- **Contract ID:** {contract_id}
- **Version:** {contract_version}
- **Project:** {project_name}
- **Style:** {architecture_style}

### Layer Context
- **Current Layer:** {layer_name}
- **Layer Path:** {layer_path}
- **Security Scope:** {security_scope}

### Security Requirements
- **Authentication:** {authentication_requirements}
- **Authorization:** {authorization_requirements}
- **Data Protection:** {data_protection_requirements}
- **Audit:** {audit_requirements}

### Dependency Rules
{dependency_rules}

---

## 🔒 AST POLICY & SECURITY RULES

### Forbidden Imports
{forbidden_imports}

### Forbidden Function Calls
{forbidden_calls}

### Security Constraints
{security_constraints}

### Additional Security Rules
- Never store secrets in code
- Use environment variables for configuration
- Validate all user input
- Sanitize all output
- Implement proper error handling (no stack traces to users)
- Use parameterized queries to prevent SQL injection
- Implement rate limiting
- Use HTTPS everywhere in production

---

## ✅ ACCEPTANCE CRITERIA (Definition of Done)

{acceptance_criteria}

---

## 📁 OUTPUT REQUIREMENTS

### Files to Create/Modify
{output_files}

### Required Structure
```
{project_root}/
├── {layer_path}/
│   ├── __init__.py
│   ├── security.py             # Security utilities
│   ├── authentication.py       # Auth implementation
│   ├── authorization.py        # Authorization logic
│   └── test_security.py        # Security tests
```

### Patch Structure
```json
{{
  "files": {output_files_json},
  "tests": ["{test_files}"],
  "contract_id": "{contract_id}",
  "task_id": "{task_id}",
  "layer": "{layer_name}"
}}
```

---

## 🎨 IMPLEMENTATION GUIDELINES

### Security Implementation

#### Authentication

**JWT Authentication Example:**
```python
from datetime import datetime, timedelta
from typing import Optional
import jwt
from passlib.context import CryptContext

# Configuration
SECRET_KEY = "your-secret-key"  # In production: use environment variable
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Generate a password hash."""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
```

#### Authorization

**Role-Based Access Control (RBAC) Example:**
```python
from functools import wraps
from typing import Callable, List, Any
from fastapi import Request, HTTPException, status

def require_roles(allowed_roles: List[str]):
    """Decorator to require specific roles."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request") or args[0]
            user = request.state.user
            
            if not user or user.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Usage
@router.get("/admin")
@require_roles(["admin"])
async def admin_only_endpoint(request: Request):
    """Endpoint accessible only to admins."""
    return {"message": "Admin access granted"}
```

#### Input Validation

**Pydantic Validation Example:**
```python
from pydantic import BaseModel, validator, Field
from typing import Optional
import re

class UserCreateRequest(BaseModel):
    """Request model for user creation."""
    
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    
    @validator("username")
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username must contain only letters, numbers, and underscores")
        return v
    
    @validator("email")
    def validate_email(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", v):
            raise ValueError("Invalid email format")
        return v.lower()
    
    @validator("password")
    def validate_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v
```

#### Security Headers

**Middleware for Security Headers:**
```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        
        return response

# Add to FastAPI app
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

---

## 🚀 TASK INSTRUCTION

{task_description}

Implement security measures for **{task_name}** following the architecture contract {contract_id}.

**Constraints:**
- Only modify files within the {layer_path} directory
- Do not violate dependency rules: {dependency_rules_summary}
- Security layer may depend on: {allowed_dependencies}
- All code must pass AST validation
- All tests must pass
- No security vulnerabilities (scan with bandit, safety, etc.)

**Deliverables:**
1. Authentication implementation
2. Authorization implementation
3. Input validation and sanitization
4. Security headers and middleware
5. Security tests

---

## ✨ EXAMPLE OUTPUT

```python
# Security utilities module
"""Security utilities and helpers."""

import hashlib
import hmac
import secrets
from typing import Optional

class SecurityUtils:
    """Collection of security utility functions."""
    
    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """Generate a cryptographically secure random token."""
        return secrets.token_hex(length)
    
    @staticmethod
    def hash_data(data: str, salt: Optional[str] = None) -> str:
        """Hash data with optional salt."""
        if salt is None:
            salt = secrets.token_hex(16)
        return hashlib.sha256((data + salt).encode()).hexdigest()
    
    @staticmethod
    def constant_time_compare(a: str, b: str) -> bool:
        """Compare two strings in constant time."""
        return hmac.compare_digest(a, b)
```

---

**Note:** This prompt is deterministically generated. Same inputs will always produce this exact prompt.
