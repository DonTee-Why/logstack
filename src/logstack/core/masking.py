"""
Data masking engine for sensitive field detection and masking.

Based on ADR-001: Global baseline masking with per-token overrides.
Executes before WAL persistence to ensure no sensitive data is stored.
"""

import re
from typing import Any, Dict, List, Optional, Set

import structlog

from ..config import get_settings

logger = structlog.get_logger(__name__)


class MaskingEngine:
    """
    Handles sensitive data masking with configurable rules.
    
    Features:
    - Global baseline masking for common sensitive fields
    - Per-token override rules for additional fields
    - Partial masking (keep prefixes/suffixes)
    - Deep object traversal for nested data
    """
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self._compiled_patterns: Dict[str, "re.Pattern[str]"] = {}
        logger.info("Masking engine initialized")
    
    def mask_log_entry(self, entry_data: Dict[str, Any], token: str) -> Dict[str, Any]:
        """
        Mask sensitive data in a log entry.
        
        Args:
            entry_data: The log entry dictionary to mask
            token: API token to determine per-token masking rules
            
        Returns:
            Masked log entry dictionary
        """
        # Get masking rules for this token
        baseline_keys = set(self.settings.masking.baseline_keys)
        token_overrides = self._get_token_overrides(token)
        all_mask_keys = baseline_keys.union(token_overrides)
        
        logger.debug(
            "Masking log entry",
            token=token[:8] + "...",
            baseline_keys=len(baseline_keys),
            token_overrides=len(token_overrides),
            total_mask_keys=len(all_mask_keys)
        )
        
        # Create a deep copy and mask it
        masked_entry: Dict[str, Any] = self._deep_copy_and_mask(entry_data, all_mask_keys, token)
        
        return masked_entry
    
    def _get_token_overrides(self, token: str) -> Set[str]:
        """Get additional masking keys for a specific token."""
        tenant_overrides = self.settings.masking.tenant_overrides.get(token, [])
        return set(tenant_overrides)
    
    def _deep_copy_and_mask(
        self,
        obj: Any,
        mask_keys: Set[str],
        token: str,
        path: str = ""
    ) -> Any:
        """
        Recursively traverse and mask sensitive data in nested structures.
        
        Args:
            obj: Object to traverse (dict, list, or primitive)
            mask_keys: Set of keys that should be masked
            token: API token for logging context
            path: Current path in the object (for debugging)
            
        Returns:
            Masked copy of the object
        """
        if isinstance(obj, dict):
            masked_dict = {}
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key
                
                # Check if this key should be masked
                if self._should_mask_key(key, mask_keys):
                    masked_value = self._mask_value(key, value, token)
                    masked_dict[key] = masked_value
                    
                    logger.debug(
                        "Masked sensitive field",
                        token=token[:8] + "...",
                        field=key,
                        path=current_path,
                        original_type=type(value).__name__
                    )
                else:
                    # Recursively process nested structures
                    masked_dict[key] = self._deep_copy_and_mask(
                        value, mask_keys, token, current_path
                    )
            
            return masked_dict
        
        elif isinstance(obj, list):
            return [
                self._deep_copy_and_mask(item, mask_keys, token, f"{path}[{i}]")
                for i, item in enumerate(obj)
            ]
        
        else:
            # Primitive value - return as-is
            return obj
    
    def _should_mask_key(self, key: str, mask_keys: Set[str]) -> bool:
        """
        Determine if a key should be masked.
        
        Uses case-insensitive matching and partial key matching.
        """
        key_lower = key.lower()
        
        # Exact match (case-insensitive)
        for mask_key in mask_keys:
            if key_lower == mask_key.lower():
                return True
            
            # Partial match (key contains mask_key)
            if mask_key.lower() in key_lower:
                return True
        
        # Additional heuristic patterns for common sensitive fields
        sensitive_patterns = [
            'card', 'credit', 'ssn', 'social', 'phone', 'email',
            'pass', 'pwd', 'key', 'token', 'auth', 'secret',
            'private', 'confidential', 'sensitive'
        ]
        
        for pattern in sensitive_patterns:
            if pattern in key_lower:
                return True
        
        return False
    
    def _mask_value(self, key: str, value: Any, token: str) -> str:
        """
        Apply appropriate masking to a sensitive value.
        
        Args:
            key: The field key being masked
            value: The value to mask
            token: API token for context
            
        Returns:
            Masked string representation
        """
        # Convert to string for masking
        str_value = str(value) if value is not None else ""
        
        # Check for partial masking rules
        partial_rules = self.settings.masking.partial_rules
        key_lower = key.lower()
        
        # Check for exact matches first
        for rule_key, rule_config in partial_rules.items():
            if key_lower == rule_key.lower():
                return self._apply_partial_masking(str_value, rule_config)
        
        # Check for partial matches (key contains rule_key)
        for rule_key, rule_config in partial_rules.items():
            if rule_key.lower() in key_lower:
                return self._apply_partial_masking(str_value, rule_config)
        
        # Default: Full masking
        return self._apply_full_masking(str_value)
    
    def _apply_partial_masking(self, value: str, rule_config: Dict[str, Any]) -> str:
        """Apply partial masking based on rule configuration."""
        if not value:
            return "****"
        
        # Email masking: e*****e@email.com for example@email.com
        if "mask_email" in rule_config and rule_config["mask_email"]:
            return self._mask_email(value)
        
        # Keep prefix
        if "keep_prefix" in rule_config:
            prefix_len = rule_config["keep_prefix"]
            if len(value) <= prefix_len:
                return "****"
            
            prefix = value[:prefix_len]
            suffix = "****"
            return f"{prefix}{suffix}"
        
        # Keep suffix
        if "keep_suffix" in rule_config:
            suffix_len = rule_config["keep_suffix"]
            if len(value) <= suffix_len:
                return "****"
            
            prefix = "****"
            suffix = value[-suffix_len:]
            return f"{prefix}{suffix}"
        
        # Default to full masking
        return self._apply_full_masking(value)
    
    def _apply_full_masking(self, value: str) -> str:
        """Apply full masking to a value."""
        if not value:
            return "****"
        
        # For very short values, just mask completely
        if len(value) <= 4:
            return "****"
        
        # For longer values, show length hint
        if len(value) <= 16:
            return "****"
        
        # For very long values, show some structure
        return f"****[{len(value)} chars]"
    
    def _mask_email(self, email: str) -> str:
        """
        Mask email addresses in format: e*****e@email.com for example@email.com
        
        Args:
            email: Email address to mask
            
        Returns:
            Masked email string
        """
        if not email or "@" not in email:
            return "****"
        
        try:
            local_part, domain = email.split("@", 1)
            
            if len(local_part) <= 2:
                # Very short local part, mask completely
                masked_local = "****"
            else:
                # Show first and last character with stars in between
                first_char = local_part[0]
                last_char = local_part[-1]
                middle_stars = "*" * min(5, len(local_part) - 2)  # Max 5 stars
                masked_local = f"{first_char}{middle_stars}{last_char}"
            
            return f"{masked_local}@{domain}"
            
        except Exception:
            # If anything goes wrong, fall back to full masking
            return "****"


# Global masking engine instance
_masking_engine: Optional[MaskingEngine] = None


def get_masking_engine() -> MaskingEngine:
    """Get or create the global masking engine instance."""
    global _masking_engine
    
    if _masking_engine is None:
        _masking_engine = MaskingEngine()
    
    return _masking_engine


def mask_log_entries(entries: List[Dict[str, Any]], token: str) -> List[Dict[str, Any]]:
    """
    Convenience function to mask a list of log entries.
    
    Args:
        entries: List of log entry dictionaries
        token: API token for masking rules
        
    Returns:
        List of masked log entries
    """
    engine = get_masking_engine()
    
    masked_entries = []
    for entry in entries:
        try:
            masked_entry = engine.mask_log_entry(entry, token)
            masked_entries.append(masked_entry)
        except Exception as e:
            logger.error(
                "Failed to mask log entry",
                token=token[:8] + "...",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            # In case of masking failure, return heavily masked version
            masked_entries.append({"error": "masking_failed", "original_keys": list(entry.keys())})
    
    return masked_entries
