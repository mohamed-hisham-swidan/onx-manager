# ADR-0009: Pydantic Field Validators for Domain Value-Object Inputs

**Status**: Accepted
**Date**: 2026-07-27
**Author**: Batch 2.5 / Batch 4

## Context

Domain value objects (`MinecraftVersion`, `EmailAddress`) perform input validation in their constructors. When these are called from command handlers with data that passed Pydantic schema validation (where the field was typed as `str` with no constraints), invalid input would raise `ValueError` (not `MCSError`) inside the handler. The `CommandBus` catch-all would convert this to HTTP 500 with `UNEXPECTED_ERROR` instead of the correct HTTP 422 `VALIDATION_ERROR`.

This was discovered in two places:
1. `minecraft_version` field in `ServerCreateRequest` — any string was accepted, `MinecraftVersion.parse()` would raise `ValueError`
2. `email` field in `CreateUserRequest` — any string was accepted, `EmailAddress.__post_init__` would raise `ValueError`

## Decision

For every Pydantic request schema field whose value is passed to a domain value-object constructor:

1. Add a `@field_validator` to the Pydantic schema that validates against the same pattern/constraint used by the domain value object
2. Add a try/except safety-net in the command handler that catches `ValueError` from the domain constructor and raises `InvalidValueError` (an `MCSError` subclass) instead

This ensures:
- Invalid input is rejected at the HTTP boundary (422, not 500)
- The error message includes the specific field name and invalid value
- If validation is bypassed (e.g., internal call), the handler still produces a proper error

## Consequences

- HTTP 500 → 422 for invalid input across all affected endpoints
- Consistent error format (Pydantic `detail` list for schema violations, MCSError envelope for handler violations)
- More code in schemas (one validator per validated field)
- Audit required whenever a new domain value object is added to ensure its Pydantic schema counterpart includes a matching validator
