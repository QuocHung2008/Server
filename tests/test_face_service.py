"""
Unit tests for FaceService class

Tests Requirements: 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4

Note: These tests verify the class structure and basic logic without requiring
the face_recognition library to be installed.
"""

import pytest
import numpy as np
import pickle
from uuid import uuid4
from unittest.mock import MagicMock, patch
import sys

# Mock face_recognition module if not available
if 'face_recognition' not in sys.modules:
    sys.modules['face_recognition'] = MagicMock()

from app.services.face_service import FaceService, MatchResult


class TestFaceServiceInit:
    """Test FaceService initialization"""
    
    def test_init_default_parameters(self):
        """Test FaceService initializes with default parameters"""
        service = FaceService()
        assert service.tolerance == 0.5
        assert service.executor._max_workers == 4
        assert isinstance(service.known_encodings, dict)
        assert len(service.known_encodings) == 0
        service.shutdown()
    
    def test_init_custom_parameters(self):
        """Test FaceService initializes with custom parameters"""
        service = FaceService(tolerance=0.6, max_workers=2)
        assert service.tolerance == 0.6
        assert service.executor._max_workers == 2
        service.shutdown()


class TestFaceServiceEncodingCache:
    """Test in-memory encoding cache functionality"""
    
    @pytest.mark.asyncio
    async def test_add_student_encoding_new_class(self):
        """Test adding student encoding for a new class (Requirement 2.3)"""
        service = FaceService()
        encoding = np.random.rand(128)
        student_id = uuid4()
        
        await service.add_student_encoding(
            student_id=student_id,
            class_name="12T1",
            full_name="Test Student",
            student_code="ST001",
            encoding=encoding
        )
        
        assert "12T1" in service.known_encodings
        assert len(service.known_encodings["12T1"]) == 1
        assert service.known_encodings["12T1"][0][1] == str(student_id)
        assert service.known_encodings["12T1"][0][2] == "Test Student"
        assert service.known_encodings["12T1"][0][3] == "ST001"
        service.shutdown()
    
    @pytest.mark.asyncio
    async def test_add_student_encoding_existing_class(self):
        """Test adding student encoding to existing class (Requirement 2.3)"""
        service = FaceService()
        
        # Add first student
        encoding1 = np.random.rand(128)
        student_id1 = uuid4()
        await service.add_student_encoding(student_id1, "12T1", "Student 1", "ST001", encoding1)
        
        # Add second student to same class
        encoding2 = np.random.rand(128)
        student_id2 = uuid4()
        await service.add_student_encoding(student_id2, "12T1", "Student 2", "ST002", encoding2)
        
        assert len(service.known_encodings["12T1"]) == 2
        service.shutdown()


class TestFaceServiceMatchingSync:
    """Test face matching functionality (synchronous helper methods)"""
    
    def test_match_face_no_encodings(self):
        """Test matching when no encodings are loaded (Requirement 2.4, 2.5)"""
        service = FaceService()
        unknown_encoding = np.random.rand(128)
        
        with patch('face_recognition.face_distance', return_value=np.array([])):
            result = service._match_face_sync(unknown_encoding)
        
        assert result is None
        service.shutdown()
    
    def test_match_face_with_tolerance(self):
        """Test that matches respect tolerance threshold (Requirement 2.5)"""
        service = FaceService(tolerance=0.5)
        
        # Create a known encoding
        known_encoding = np.random.rand(128)
        student_id = uuid4()
        service._add_student_encoding_sync(student_id, "12T1", "Test Student", "ST001", known_encoding)
        
        # Mock face_distance to return 0 (perfect match)
        with patch('face_recognition.face_distance', return_value=np.array([0.0])):
            result = service._match_face_sync(known_encoding.copy())
        
        assert result is not None
        assert result["student_id"] == str(student_id)
        assert result["confidence"] == 1.0  # 1 - 0 = 1.0
        
        service.shutdown()
    
    def test_match_face_best_match_selection(self):
        """Test that the closest match is selected (Requirement 2.5)"""
        service = FaceService(tolerance=0.5)
        
        # Create a base encoding
        base_encoding = np.zeros(128)
        
        # Add two students
        encoding1 = base_encoding + 0.1
        student_id1 = uuid4()
        service._add_student_encoding_sync(student_id1, "12T1", "Student 1", "ST001", encoding1)
        
        encoding2 = base_encoding + 0.3
        student_id2 = uuid4()
        service._add_student_encoding_sync(student_id2, "12T1", "Student 2", "ST002", encoding2)
        
        # Mock face_distance to return distances [0.1, 0.3]
        with patch('face_recognition.face_distance', return_value=np.array([0.1, 0.3])):
            result = service._match_face_sync(base_encoding)
        
        assert result is not None
        assert result["student_id"] == str(student_id1)  # Closer match
        assert result["confidence"] == 0.9  # 1 - 0.1
        
        service.shutdown()
    
    def test_match_face_exceeds_tolerance(self):
        """Test that matches beyond tolerance are rejected (Requirement 2.5)"""
        service = FaceService(tolerance=0.5)
        
        # Add a student
        encoding1 = np.random.rand(128)
        student_id1 = uuid4()
        service._add_student_encoding_sync(student_id1, "12T1", "Student 1", "ST001", encoding1)
        
        # Mock face_distance to return distance > tolerance
        with patch('face_recognition.face_distance', return_value=np.array([0.6])):
            result = service._match_face_sync(np.random.rand(128))
        
        assert result is None  # Should not match
        
        service.shutdown()
    
    def test_match_face_class_filter(self):
        """Test matching with class name filter (Requirement 2.4)"""
        service = FaceService()
        
        # Add students to different classes
        encoding1 = np.random.rand(128)
        student_id1 = uuid4()
        service._add_student_encoding_sync(student_id1, "12T1", "Student 1", "ST001", encoding1)
        
        encoding2 = np.random.rand(128)
        student_id2 = uuid4()
        service._add_student_encoding_sync(student_id2, "10T1", "Student 2", "ST002", encoding2)
        
        # Match with class filter - should only check 12T1
        with patch('face_recognition.face_distance', return_value=np.array([0.2])):
            result = service._match_face_sync(encoding1, class_name="12T1")
        
        assert result is not None
        assert result["class_name"] == "12T1"
        
        service.shutdown()


class TestFaceServiceSerializationRoundTrip:
    """Test face encoding serialization/deserialization (Requirement 21.3)"""
    
    def test_pickle_round_trip(self):
        """Test that face encodings survive pickle round-trip"""
        original_encoding = np.random.rand(128)
        
        # Serialize
        serialized = pickle.dumps(original_encoding)
        
        # Deserialize
        deserialized = pickle.loads(serialized)
        
        # Verify equality
        assert np.allclose(original_encoding, deserialized, rtol=1e-9, atol=1e-9)
    
    def test_pickle_with_known_values(self):
        """Test pickle with known encoding values"""
        original_encoding = np.array([float(i) for i in range(128)])
        
        serialized = pickle.dumps(original_encoding)
        deserialized = pickle.loads(serialized)
        
        assert np.array_equal(original_encoding, deserialized)


class TestMatchResult:
    """Test MatchResult dataclass"""
    
    def test_match_result_matched(self):
        """Test MatchResult for successful match"""
        result = MatchResult(
            matched=True,
            student_id="uuid-123",
            student_name="Test Student",
            student_code="ST001",
            class_name="12T1",
            confidence=0.95
        )
        
        assert result.matched is True
        assert result.student_id == "uuid-123"
        assert result.student_name == "Test Student"
        assert result.student_code == "ST001"
        assert result.class_name == "12T1"
        assert result.confidence == 0.95
    
    def test_match_result_not_matched(self):
        """Test MatchResult for failed match"""
        result = MatchResult(
            matched=False,
            student_id=None,
            student_name=None,
            student_code=None,
            class_name=None,
            confidence=None
        )
        
        assert result.matched is False
        assert result.student_id is None
        assert result.confidence is None


class TestThreadPoolExecutor:
    """Test ThreadPoolExecutor configuration (Requirements 3.1, 3.4)"""
    
    def test_executor_worker_count(self):
        """Test that ThreadPoolExecutor uses 4 workers as specified"""
        service = FaceService()
        assert service.executor._max_workers == 4
        service.shutdown()
    
    def test_executor_custom_worker_count(self):
        """Test that ThreadPoolExecutor respects custom worker count"""
        service = FaceService(max_workers=2)
        assert service.executor._max_workers == 2
        service.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

