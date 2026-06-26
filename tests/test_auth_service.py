"""
Unit tests for AuthService class.

Tests Requirements 4.1, 4.2, 4.3, 4.4:
- Loading API keys from database into in-memory cache
- Validating API keys against in-memory cache
- Adding new API keys to database and cache
- Deactivating API keys in database and cache
"""
import pytest
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from hypothesis import given, strategies as st
from app.services.auth_service import AuthService


class TestAuthService:
    """Test suite for AuthService class."""
    
    @pytest.fixture
    def auth_service(self):
        """Create a fresh AuthService instance for each test."""
        return AuthService()
    
    @pytest.fixture
    def mock_pool(self):
        """Mock database connection pool."""
        pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.fetchval = AsyncMock()
        
        # Setup pool.acquire() to return mock connection
        pool.acquire = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock()
        
        return pool, mock_conn
    
    # Test Requirement 4.1: Load API keys from database into cache
    @pytest.mark.asyncio
    async def test_load_api_keys_empty_database(self, auth_service, mock_pool):
        """Test loading API keys when database is empty."""
        pool, mock_conn = mock_pool
        mock_conn.fetch.return_value = []
        
        with patch('app.database.pool', pool):
            await auth_service.load_api_keys()
        
        assert len(auth_service.active_keys) == 0
        mock_conn.fetch.assert_awaited_once()
    
    @pytest.mark.asyncio
    async def test_load_api_keys_with_active_keys(self, auth_service, mock_pool):
        """Test loading multiple active API keys from database."""
        pool, mock_conn = mock_pool
        
        # Simulate database records
        key1_hash = hashlib.sha256(b"test_key_1").hexdigest()
        key2_hash = hashlib.sha256(b"test_key_2").hexdigest()
        key3_hash = hashlib.sha256(b"test_key_3").hexdigest()
        
        mock_conn.fetch.return_value = [
            {'key_hash': key1_hash},
            {'key_hash': key2_hash},
            {'key_hash': key3_hash},
        ]
        
        with patch('app.database.pool', pool):
            await auth_service.load_api_keys()
        
        assert len(auth_service.active_keys) == 3
        assert key1_hash in auth_service.active_keys
        assert key2_hash in auth_service.active_keys
        assert key3_hash in auth_service.active_keys
    
    @pytest.mark.asyncio
    async def test_load_api_keys_clears_existing_cache(self, auth_service, mock_pool):
        """Test that loading API keys clears existing cache first."""
        pool, mock_conn = mock_pool
        
        # Pre-populate cache with old data
        old_hash = hashlib.sha256(b"old_key").hexdigest()
        auth_service.active_keys.add(old_hash)
        
        # New database data
        new_hash = hashlib.sha256(b"new_key").hexdigest()
        mock_conn.fetch.return_value = [{'key_hash': new_hash}]
        
        with patch('app.database.pool', pool):
            await auth_service.load_api_keys()
        
        assert len(auth_service.active_keys) == 1
        assert old_hash not in auth_service.active_keys
        assert new_hash in auth_service.active_keys
    
    # Test Requirement 4.2: Validate API key against in-memory cache
    @pytest.mark.asyncio
    async def test_validate_key_valid(self, auth_service):
        """Test validation of a valid API key in cache."""
        api_key = "test_valid_key"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        # Add key to cache
        auth_service.active_keys.add(key_hash)
        
        result = await auth_service.validate_key(api_key)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_validate_key_invalid(self, auth_service):
        """Test validation of an invalid API key not in cache."""
        api_key = "test_invalid_key"
        
        # Cache is empty
        result = await auth_service.validate_key(api_key)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_validate_key_uses_sha256(self, auth_service):
        """Test that validation uses SHA256 hashing."""
        api_key = "test_key_with_special_chars_!@#$%"
        expected_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        auth_service.active_keys.add(expected_hash)
        
        result = await auth_service.validate_key(api_key)
        assert result is True
    
    # Test Requirement 4.3: Add new API key to database and cache
    @pytest.mark.asyncio
    async def test_add_key_basic(self, auth_service, mock_pool):
        """Test adding a new API key with basic parameters."""
        pool, mock_conn = mock_pool
        api_key = "new_test_key"
        label = "Test Device"
        
        with patch('app.database.pool', pool):
            await auth_service.add_key(api_key, label=label)
        
        # Verify database insert
        mock_conn.execute.assert_awaited_once()
        call_args = mock_conn.execute.await_args
        assert "INSERT INTO api_keys" in call_args[0][0]
        
        # Verify cache update
        expected_hash = hashlib.sha256(api_key.encode()).hexdigest()
        assert expected_hash in auth_service.active_keys
    
    @pytest.mark.asyncio
    async def test_add_key_with_all_parameters(self, auth_service, mock_pool):
        """Test adding API key with all optional parameters."""
        pool, mock_conn = mock_pool
        api_key = "new_test_key"
        label = "Test Device"
        class_id = "123e4567-e89b-12d3-a456-426614174000"
        device_id = "ESP32_01"
        
        with patch('app.database.pool', pool):
            await auth_service.add_key(api_key, label=label, class_id=class_id, device_id=device_id)
        
        # Verify all parameters were passed to database
        call_args = mock_conn.execute.await_args
        assert call_args[0][1] == hashlib.sha256(api_key.encode()).hexdigest()
        assert call_args[0][2] == label
        assert call_args[0][3] == class_id
        assert call_args[0][4] == device_id
    
    @pytest.mark.asyncio
    async def test_add_key_updates_cache_immediately(self, auth_service, mock_pool):
        """Test that adding a key updates cache before function returns."""
        pool, mock_conn = mock_pool
        api_key = "immediate_key"
        
        # Verify key not in cache initially
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        assert key_hash not in auth_service.active_keys
        
        with patch('app.database.pool', pool):
            await auth_service.add_key(api_key)
        
        # Verify key is in cache after add
        assert key_hash in auth_service.active_keys
        
        # Verify validation works immediately
        result = await auth_service.validate_key(api_key)
        assert result is True
    
    # Test Requirement 4.4: Deactivate API key in database and cache
    @pytest.mark.asyncio
    async def test_deactivate_key_basic(self, auth_service, mock_pool):
        """Test deactivating an API key."""
        pool, mock_conn = mock_pool
        api_key = "key_to_deactivate"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        # Add key to cache first
        auth_service.active_keys.add(key_hash)
        
        with patch('app.database.pool', pool):
            await auth_service.deactivate_key(api_key)
        
        # Verify database update
        mock_conn.execute.assert_awaited_once()
        call_args = mock_conn.execute.await_args
        assert "UPDATE api_keys SET is_active = FALSE" in call_args[0][0]
        assert call_args[0][1] == key_hash
        
        # Verify cache removal
        assert key_hash not in auth_service.active_keys
    
    @pytest.mark.asyncio
    async def test_deactivate_key_removes_from_cache_immediately(self, auth_service, mock_pool):
        """Test that deactivating a key removes it from cache immediately."""
        pool, mock_conn = mock_pool
        api_key = "immediate_deactivate"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        # Add key to cache
        auth_service.active_keys.add(key_hash)
        assert await auth_service.validate_key(api_key) is True
        
        with patch('app.database.pool', pool):
            await auth_service.deactivate_key(api_key)
        
        # Verify key no longer validates
        assert await auth_service.validate_key(api_key) is False
        assert key_hash not in auth_service.active_keys
    
    @pytest.mark.asyncio
    async def test_deactivate_key_nonexistent(self, auth_service, mock_pool):
        """Test deactivating a key that doesn't exist in cache (should not raise error)."""
        pool, mock_conn = mock_pool
        api_key = "nonexistent_key"
        
        # Key not in cache
        with patch('app.database.pool', pool):
            await auth_service.deactivate_key(api_key)
        
        # Should still attempt database update
        mock_conn.execute.assert_awaited_once()
    
    # Edge cases and SHA256 hashing tests
    @pytest.mark.asyncio
    async def test_sha256_hash_consistency(self, auth_service):
        """Test that the same key always produces the same hash."""
        api_key = "consistent_key"
        
        hash1 = hashlib.sha256(api_key.encode()).hexdigest()
        hash2 = hashlib.sha256(api_key.encode()).hexdigest()
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 produces 64 character hex string
    
    @pytest.mark.asyncio
    async def test_different_keys_produce_different_hashes(self, auth_service):
        """Test that different keys produce different hashes."""
        key1 = "key_one"
        key2 = "key_two"
        
        hash1 = hashlib.sha256(key1.encode()).hexdigest()
        hash2 = hashlib.sha256(key2.encode()).hexdigest()
        
        assert hash1 != hash2
    
    @pytest.mark.asyncio
    async def test_validate_key_empty_string(self, auth_service):
        """Test validation with empty string key."""
        result = await auth_service.validate_key("")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_cache_consistency_after_multiple_operations(self, auth_service, mock_pool):
        """Test cache remains consistent after multiple add/deactivate operations."""
        pool, mock_conn = mock_pool
        
        with patch('app.database.pool', pool):
            # Add multiple keys
            await auth_service.add_key("key1")
            await auth_service.add_key("key2")
            await auth_service.add_key("key3")
            
            assert len(auth_service.active_keys) == 3
            
            # Deactivate one
            await auth_service.deactivate_key("key2")
            
            assert len(auth_service.active_keys) == 2
            assert await auth_service.validate_key("key1") is True
            assert await auth_service.validate_key("key2") is False
            assert await auth_service.validate_key("key3") is True


class TestBackwardCompatibility:
    """Test backward compatibility wrapper functions."""
    
    @pytest.fixture
    def mock_pool(self):
        """Mock database connection pool."""
        pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.fetchval = AsyncMock()
        
        # Setup pool.acquire() to return mock connection
        pool.acquire = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock()
        
        return pool, mock_conn
    
    @pytest.mark.asyncio
    async def test_load_api_keys_function(self, mock_pool):
        """Test the backward compatible load_api_keys function."""
        from app.services.auth_service import load_api_keys, auth_service
        
        pool, mock_conn = mock_pool
        key_hash = hashlib.sha256(b"test_key").hexdigest()
        mock_conn.fetch.return_value = [{'key_hash': key_hash}]
        
        with patch('app.database.pool', pool):
            await load_api_keys()
        
        assert key_hash in auth_service.active_keys
    
    def test_is_valid_api_key_function(self):
        """Test the backward compatible is_valid_api_key function."""
        from app.services.auth_service import is_valid_api_key, auth_service
        
        # Clear and populate cache
        auth_service.active_keys.clear()
        api_key = "test_key"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        auth_service.active_keys.add(key_hash)
        
        assert is_valid_api_key(api_key) is True
        assert is_valid_api_key("invalid_key") is False


class TestAPIKeyCacheConsistencyProperty:
    """Property-based tests for API key cache consistency.
    
    **Validates: Requirements 4.3**
    
    Property 5: API Key Cache Consistency
    Tests that cache updates immediately after create/deactivate operations.
    """
    
    @pytest.mark.asyncio
    @given(
        api_key=st.text(min_size=16, max_size=64, alphabet=st.characters(blacklist_categories=('Cs', 'Cc'))),
        operation=st.sampled_from(["create", "deactivate"])
    )
    async def test_api_key_cache_consistency(self, api_key, operation):
        """Property test: Cache updates immediately after create/deactivate operations.
        
        **Validates: Requirements 4.3**
        
        For any API key creation or deactivation operation in the database,
        the in-memory API key cache SHALL be updated immediately such that
        subsequent authentication requests reflect the current state without
        requiring application restart.
        
        Args:
            api_key: Randomly generated API key string (16-64 characters)
            operation: Either "create" or "deactivate"
        """
        # Create mock pool inside test to avoid fixture issues with Hypothesis
        pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.fetchval = AsyncMock()
        
        # Setup pool.acquire() to return mock connection
        pool.acquire = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock()
        
        # Create fresh AuthService instance for each test
        auth_service = AuthService()
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        with patch('app.database.pool', pool):
            if operation == "create":
                # Test create operation
                await auth_service.add_key(api_key)
                
                # Verify key hash is in cache immediately
                assert key_hash in auth_service.active_keys, \
                    f"Key hash should be in cache immediately after creation"
                
                # Verify validation works immediately without DB query
                assert await auth_service.validate_key(api_key) is True, \
                    f"Key should validate successfully immediately after creation"
                
            elif operation == "deactivate":
                # First create the key
                await auth_service.add_key(api_key)
                assert key_hash in auth_service.active_keys, \
                    f"Key should be in cache after creation"
                
                # Then deactivate it
                await auth_service.deactivate_key(api_key)
                
                # Verify key hash is removed from cache immediately
                assert key_hash not in auth_service.active_keys, \
                    f"Key hash should be removed from cache immediately after deactivation"
                
                # Verify validation fails immediately without DB query
                assert await auth_service.validate_key(api_key) is False, \
                    f"Key should not validate after deactivation"
