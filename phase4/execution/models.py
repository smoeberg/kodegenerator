"""Phase 4 AI-4 execution domain models."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Tuple
import hashlib, json
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityDecision

class ExecutionStatus(str, Enum):
    SUCCEEDED="succeeded"; FAILED="failed"; REJECTED="rejected"; REPLAYED="replayed"

@dataclass(frozen=True)
class ExecutionRequest:
    request_id:str; agent_identity:str; action:str; resource:str; context_packet_id:str; organization_id:str
    parameters:Tuple[Tuple[str,str],...]=(); idempotency_key:Optional[str]=None; actor_id:Optional[str]=None; capability:Optional[str]=None
    def __post_init__(self):
        for n in ("request_id","agent_identity","action","resource","context_packet_id","organization_id"):
            if not isinstance(getattr(self,n),str) or not getattr(self,n).strip(): raise ValueError(f"{n} must be non-empty")
        keys=[k for k,_ in self.parameters]
        if len(keys)!=len(set(keys)): raise ValueError("parameter keys must be unique")
        if self.idempotency_key is not None and not self.idempotency_key.strip(): raise ValueError("idempotency_key must be non-empty when supplied")
    @staticmethod
    def create(request_id:str,agent_identity:str,action:str,resource:str,context_packet_id:str,*,organization_id:str,parameters:Mapping[str,str]|None=None,idempotency_key:Optional[str]=None,actor_id:Optional[str]=None,capability:Optional[str]=None)->"ExecutionRequest":
        return ExecutionRequest(request_id,agent_identity,action,resource,context_packet_id,organization_id,tuple(sorted((str(k),str(v)) for k,v in (parameters or {}).items())),idempotency_key,actor_id,capability)

@dataclass(frozen=True)
class GovernedDispatch:
    request:ExecutionRequest; grant:VerifiedAuthorityGrant; _dispatch_token:object|None=field(default=None,init=False,repr=False,compare=False)
    @classmethod
    def issue(cls,request,grant):
        if not isinstance(request,ExecutionRequest): raise TypeError("request must be an ExecutionRequest")
        if not isinstance(grant,VerifiedAuthorityGrant) or not grant.binds(request): raise ValueError("grant is not valid for this execution request")
        value=cls(request,grant); object.__setattr__(value,"_dispatch_token",object()); return value
    @property
    def is_verified(self): return self._dispatch_token is not None and self.grant.verified and self.grant.binds(self.request)

@dataclass(frozen=True)
class ExecutionResult:
    execution_id:str; request_id:str; authority_policy_id:str; authority_policy_version:str; agent_identity:str; action:str; resource:str; context_packet_id:str; status:ExecutionStatus; adapter_id:str; output:Tuple[Tuple[str,str],...]; error:Optional[str]; executed_at:str
    @property
    def succeeded(self): return self.status is ExecutionStatus.SUCCEEDED
    @property
    def terminal(self): return self.status in {ExecutionStatus.SUCCEEDED,ExecutionStatus.FAILED,ExecutionStatus.REJECTED,ExecutionStatus.REPLAYED}

def execution_id_for(request:ExecutionRequest,decision:AuthorityDecision)->str:
    payload={"request_id":request.request_id,"agent_identity":request.agent_identity,"action":request.action,"resource":request.resource,"context_packet_id":request.context_packet_id,"organization_id":request.organization_id,"parameters":sorted(list(request.parameters)),"idempotency_key":request.idempotency_key,"actor_id":request.actor_id,"capability":request.capability,"authority_decision":decision.decision.value,"policy_id":decision.policy_id,"policy_version":decision.policy_version,"matched_rule_ids":list(decision.matched_rule_ids)}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
