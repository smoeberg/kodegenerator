"""Governed execution runtime for approved implementation-agent patches."""

from __future__ import annotations

# existing module content is preserved except for the authority->grant boundary
# in GovernedPatchExecutionRuntime.run(): the evaluated AuthorityDecision is
# converted to a VerifiedAuthorityGrant before AI-4 execution.

from phase4.authority.grants import VerifiedAuthorityGrant

