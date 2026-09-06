from __future__ import annotations


class CompileError(Exception):
    """Base exception for all compiler and recovery failures."""


class CompileInputError(CompileError):
    """Refusal when input approved staged transactions violate invariants."""


class CompileLockedError(CompileError):
    """Raised when compile lock cannot be acquired."""


class BeanCheckUnavailableError(CompileError):
    """Raised when bean-check executable is not found on PATH."""


class BeanCheckFailedError(CompileError):
    """Raised when bean-check rejects the compiled staging ledger."""


class AmbiguousRecoveryError(CompileError):
    """Raised when recovery journal encounters an unrecognizable state."""
