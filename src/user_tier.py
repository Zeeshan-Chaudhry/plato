"""
User tier management system.

Handles free vs paid tier tracking, document limits, and usage counting.
"""

import os
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from flask import session

# Tier definitions
TIER_FREE = "free"
TIER_PAID = "paid"

# Limits
FREE_TIER_MAX_SIZE_MB = 5.0
PAID_TIER_MAX_SIZE_MB = 3.0
PAID_TIER_DOCUMENT_LIMIT = 15


class UserTierManager:
    """Manages user tier and usage tracking."""
    
    def __init__(self):
        """Initialize tier manager."""
        # In production, this would use a database
        # For now, we'll use session storage
        pass
    
    def get_user_tier(self, user_id: Optional[str] = None) -> str:
        """Get user's current tier.
        
        Args:
            user_id: User identifier (defaults to session)
            
        Returns:
            Tier name ("free" or "paid")
        """
        # Get from session
        user_tier = session.get('user_tier', TIER_FREE)
        return user_tier
    
    def set_user_tier(self, tier: str, user_id: Optional[str] = None):
        """Set user's tier.
        
        Args:
            tier: Tier name ("free" or "paid")
            user_id: User identifier (defaults to session)
        """
        if tier not in [TIER_FREE, TIER_PAID]:
            raise ValueError(f"Invalid tier: {tier}")
        
        session['user_tier'] = tier
        if tier == TIER_PAID:
            # Reset document count when upgrading
            session['paid_documents_used'] = 0
            session['paid_tier_purchased_at'] = datetime.now().isoformat()
    
    def get_documents_used(self, user_id: Optional[str] = None) -> int:
        """Get number of documents user has processed.
        
        Args:
            user_id: User identifier (defaults to session)
            
        Returns:
            Number of documents processed in current billing period
        """
        if self.get_user_tier() == TIER_FREE:
            return 0  # Free tier has no limit tracking
        
        return session.get('paid_documents_used', 0)
    
    def increment_document_count(self, user_id: Optional[str] = None):
        """Increment document count for paid users.
        
        Args:
            user_id: User identifier (defaults to session)
        """
        if self.get_user_tier() == TIER_PAID:
            current = session.get('paid_documents_used', 0)
            session['paid_documents_used'] = current + 1
    
    def can_process_document(self, file_size_mb: float, user_id: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Check if user can process a document.
        
        Args:
            file_size_mb: File size in MB
            user_id: User identifier (defaults to session)
            
        Returns:
            Tuple of (can_process, error_message)
        """
        tier = self.get_user_tier()
        
        # Check file size limit
        max_size = PAID_TIER_MAX_SIZE_MB if tier == TIER_PAID else FREE_TIER_MAX_SIZE_MB
        if file_size_mb > max_size:
            return False, f"File too large ({file_size_mb:.1f}MB). Maximum is {max_size}MB for {tier} tier."
        
        # Check document limit for paid tier
        if tier == TIER_PAID:
            documents_used = self.get_documents_used()
            if documents_used >= PAID_TIER_DOCUMENT_LIMIT:
                return False, f"You've reached your limit of {PAID_TIER_DOCUMENT_LIMIT} documents. Please purchase another package."
        
        return True, None
    
    def get_remaining_documents(self, user_id: Optional[str] = None) -> Optional[int]:
        """Get remaining documents for paid users.
        
        Args:
            user_id: User identifier (defaults to session)
            
        Returns:
            Remaining documents or None for free tier
        """
        if self.get_user_tier() == TIER_FREE:
            return None
        
        used = self.get_documents_used()
        return max(0, PAID_TIER_DOCUMENT_LIMIT - used)
    
    def get_tier_info(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get user's tier information.
        
        Args:
            user_id: User identifier (defaults to session)
            
        Returns:
            Dictionary with tier information
        """
        tier = self.get_user_tier()
        info = {
            'tier': tier,
            'max_file_size_mb': PAID_TIER_MAX_SIZE_MB if tier == TIER_PAID else FREE_TIER_MAX_SIZE_MB,
        }
        
        if tier == TIER_PAID:
            info['documents_used'] = self.get_documents_used()
            info['documents_remaining'] = self.get_remaining_documents()
            info['document_limit'] = PAID_TIER_DOCUMENT_LIMIT
        
        return info


# Global instance
tier_manager = UserTierManager()
