from __future__ import annotations

import pytest

from app.modules.versioning.domain.entities import BranchProtectionPolicy, ServerBranch
from app.modules.versioning.domain.value_objects import BranchStatus


class TestStageGBranchProtectionDomain:
    def test_branch_protection_defaults(self) -> None:
        branch = ServerBranch(id="b1", server_id="srv-1", name="main")
        assert branch.is_protected is False
        assert branch.protection_policy is None
        assert branch.can_commit_directly() is True
        assert branch.can_archive() is True

    def test_branch_protect_enables_policy(self) -> None:
        branch = ServerBranch(id="b1", server_id="srv-1", name="main")
        policy = BranchProtectionPolicy(
            require_test_pass=True,
            allow_direct_commit=False,
            allow_force_bypass=True,
            prevent_deletion=True,
        )
        branch.protect(policy)
        assert branch.is_protected is True
        assert branch.protection_policy == policy
        assert branch.can_commit_directly() is False
        assert branch.can_archive() is False

    def test_branch_unprotect(self) -> None:
        branch = ServerBranch(id="b1", server_id="srv-1", name="main")
        branch.protect()
        assert branch.is_protected is True
        assert branch.protection_policy is not None

        branch.unprotect()
        assert branch.is_protected is False
        assert branch.protection_policy is None
        assert branch.can_commit_directly() is True
        assert branch.can_archive() is True

    def test_protect_archived_branch_rejected(self) -> None:
        branch = ServerBranch(id="b1", server_id="srv-1", name="main")
        branch.archive()
        assert branch.status == BranchStatus.ARCHIVED

        with pytest.raises(ValueError, match="Cannot configure protection on archived branch"):
            branch.protect()

    def test_unprotect_archived_branch_rejected(self) -> None:
        branch = ServerBranch(id="b1", server_id="srv-1", name="main")
        branch.protect()
        branch.archive()

        with pytest.raises(ValueError, match="Cannot unprotect archived branch"):
            branch.unprotect()

    def test_archive_protected_branch_flag(self) -> None:
        branch = ServerBranch(id="b1", server_id="srv-1", name="main")
        branch.protect(BranchProtectionPolicy(prevent_deletion=True))
        assert branch.can_archive() is False

        # When prevent_deletion is False, archiving is permitted
        branch.protect(BranchProtectionPolicy(prevent_deletion=False))
        assert branch.can_archive() is True

    def test_direct_commit_policy_flags(self) -> None:
        branch = ServerBranch(id="b1", server_id="srv-1", name="main")
        # Default protection policy has allow_direct_commit=False
        branch.protect()
        assert branch.can_commit_directly() is False

        # If allow_direct_commit=True, direct commit is permitted
        branch.protect(BranchProtectionPolicy(allow_direct_commit=True))
        assert branch.can_commit_directly() is True

        # Archived branches always reject direct commit
        branch.unprotect()
        branch.archive()
        assert branch.can_commit_directly() is False

    def test_branch_protection_policy_dict_roundtrip(self) -> None:
        policy = BranchProtectionPolicy(
            require_test_pass=False,
            allow_direct_commit=True,
            allow_force_bypass=False,
            prevent_deletion=False,
        )
        d = policy.to_dict()
        assert d == {
            "require_test_pass": False,
            "allow_direct_commit": True,
            "allow_force_bypass": False,
            "prevent_deletion": False,
        }
        restored = BranchProtectionPolicy.from_dict(d)
        assert restored == policy

    def test_branch_protection_policy_from_none(self) -> None:
        restored = BranchProtectionPolicy.from_dict(None)
        assert restored == BranchProtectionPolicy()
