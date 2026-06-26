import hashlib
from typing import Set


class AuthService:
    """Authentication service with in-memory API key cache.
    
    Manages API key validation using SHA256 hashing and an in-memory cache
    to avoid database queries during authentication.
    """
    
    def __init__(self):
        self.active_keys: Set[str] = set()
    
    async def load_api_keys(self) -> None:
        """Load active API keys from database into in-memory set.
        
        Loads all active API keys from the api_keys table, hashes them with SHA256,
        and stores the hashes in the active_keys set for fast lookup.
        
        Validates: Requirements 4.1
        """
        self.active_keys.clear()
        
        print("Loading API keys into cache...")
        from app.database import pool
        if pool is None:
            print("Error: DB Pool not initialized!")
            return
        
        async with pool.acquire() as conn:
            records = await conn.fetch('''
                SELECT key_hash FROM api_keys WHERE is_active = TRUE
            ''')
            for record in records:
                self.active_keys.add(record['key_hash'])
        
        print(f"Loaded {len(self.active_keys)} active API keys into cache.")
    
    async def validate_key(self, api_key: str) -> bool:
        """Check API key hash against in-memory cache.
        
        Hashes the provided API key with SHA256 and checks if it exists
        in the in-memory cache. Does not query the database.
        
        Args:
            api_key: The raw API key string to validate
        
        Returns:
            True if the key hash exists in cache and is active, False otherwise
        
        Validates: Requirements 4.2
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return key_hash in self.active_keys
    
    async def add_key(self, api_key: str, label: str = None, class_id: str = None, device_id: str = None) -> None:
        """Add new API key to both database and cache.
        
        Hashes the API key with SHA256, inserts it into the database,
        and immediately updates the in-memory cache.
        
        Args:
            api_key: The raw API key string to add
            label: Optional label for the API key
            class_id: Optional UUID of associated class
            device_id: Optional device identifier
        
        Validates: Requirements 4.3
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        from app.database import pool
        if pool is None:
            raise Exception("Database pool is not initialized")
        
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO api_keys (key_hash, label, class_id, device_id, is_active)
                VALUES ($1, $2, $3, $4, TRUE)
            ''', key_hash, label, class_id, device_id)
        
        # Update cache immediately
        self.active_keys.add(key_hash)
        print(f"Added API key to database and cache: {label or 'Unlabeled'}")
    
    async def deactivate_key(self, api_key: str) -> None:
        """Deactivate API key in both database and cache.
        
        Marks the API key as inactive in the database and removes it
        from the in-memory cache immediately.
        
        Args:
            api_key: The raw API key string to deactivate
        
        Validates: Requirements 4.4
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        from app.database import pool
        if pool is None:
            raise Exception("Database pool is not initialized")
        
        async with pool.acquire() as conn:
            await conn.execute('''
                UPDATE api_keys SET is_active = FALSE WHERE key_hash = $1
            ''', key_hash)
        
        # Update cache immediately
        self.active_keys.discard(key_hash)
        print(f"Deactivated API key in database and cache")


# Global singleton instance
auth_service = AuthService()


# Backward compatibility functions
async def load_api_keys():
    """Load API keys into cache (backward compatibility wrapper)."""
    await auth_service.load_api_keys()


def is_valid_api_key(key: str) -> bool:
    """Check if API key is valid (backward compatibility wrapper)."""
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    return key_hash in auth_service.active_keys
