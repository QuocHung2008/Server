import asyncio
import io
import pickle
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from uuid import UUID
import numpy as np
import face_recognition
from concurrent.futures import ThreadPoolExecutor


@dataclass
class MatchResult:
    """Result of face matching operation"""
    matched: bool
    student_id: Optional[str]
    student_name: Optional[str]
    student_code: Optional[str]
    class_name: Optional[str]
    confidence: Optional[float]  # 1.0 - face_distance


class FaceService:
    """
    Face recognition service with in-memory encodings cache and ThreadPoolExecutor
    for CPU-bound operations.
    
    Requirements: 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4
    """
    
    def __init__(self, tolerance: float = 0.5, max_workers: int = 4):
        """
        Initialize FaceService with ThreadPoolExecutor
        
        Args:
            tolerance: Face distance tolerance for matching (default 0.5)
            max_workers: Number of worker threads for CPU-bound operations (default 4)
        """
        # In-memory encodings: dict[class_name, list[tuple[encoding, student_id, name, student_code]]]
        self.known_encodings: Dict[str, List[Tuple[np.ndarray, str, str, str]]] = {}
        self.tolerance = tolerance
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
    
    async def load_all_encodings(self) -> None:
        """
        Load all face encodings from database into in-memory dictionary organized by class.
        
        Requirements: 2.1, 2.2
        
        The encodings dictionary structure:
        {
            "class_name": [
                (encoding_array, student_id, full_name, student_code),
                ...
            ]
        }
        """
        self.known_encodings.clear()
        
        print("Loading all encodings from database...")
        from app.database import pool
        if pool is None:
            print("Error: DB Pool not initialized!")
            return
        
        async with pool.acquire() as conn:
            records = await conn.fetch('''
                SELECT s.id as student_id, s.full_name, s.student_code, s.face_encoding, c.name as class_name 
                FROM students s
                JOIN classes c ON s.class_id = c.id
                WHERE s.face_encoding IS NOT NULL
            ''')
            
            for record in records:
                class_name = record['class_name']
                if class_name not in self.known_encodings:
                    self.known_encodings[class_name] = []
                
                try:
                    encoding = pickle.loads(record['face_encoding'])
                    self.known_encodings[class_name].append((
                        encoding,
                        str(record['student_id']),
                        record['full_name'],
                        record['student_code']
                    ))
                except Exception as e:
                    print(f"Failed to load encoding for {record['student_code']}: {e}")
        
        count = sum(len(encs) for encs in self.known_encodings.values())
        print(f"Loaded {count} encodings across {len(self.known_encodings)} classes.")
    
    def _encode_face_sync(self, image_bytes: bytes) -> Optional[np.ndarray]:
        """
        Synchronous face encoding extraction (runs in ThreadPoolExecutor).
        
        Args:
            image_bytes: JPEG or PNG image bytes
            
        Returns:
            128-dimensional face encoding array or None if no face detected
        """
        try:
            image = face_recognition.load_image_file(io.BytesIO(image_bytes))
            encodings = face_recognition.face_encodings(image)
            if len(encodings) > 0:
                return encodings[0]
            return None
        except Exception as e:
            print(f"Error encoding face: {e}")
            return None
    
    async def encode_face(self, image_bytes: bytes) -> Optional[np.ndarray]:
        """
        Extract face encoding from image bytes using ThreadPoolExecutor.
        
        Requirements: 3.1, 3.2, 3.3
        
        Args:
            image_bytes: JPEG or PNG image bytes
            
        Returns:
            128-dimensional face encoding array or None if no face detected
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self._encode_face_sync, image_bytes)
    
    def _match_face_sync(self, unknown_encoding: np.ndarray, class_name: Optional[str] = None) -> Optional[dict]:
        """
        Synchronous face matching (runs in ThreadPoolExecutor).
        
        Args:
            unknown_encoding: Face encoding to match
            class_name: Optional class name to limit search scope
            
        Returns:
            Dictionary with match details or None if no match found
        """
        best_match = None
        best_distance = 1.0
        
        # Determine which classes to check
        classes_to_check = [class_name] if class_name and class_name in self.known_encodings else self.known_encodings.keys()
        
        for c_name in classes_to_check:
            class_students = self.known_encodings.get(c_name, [])
            if not class_students:
                continue
            
            # Extract encodings for this class
            encs = [item[0] for item in class_students]
            
            # Calculate face distances
            distances = face_recognition.face_distance(encs, unknown_encoding)
            
            # Find best match in this class
            for i, distance in enumerate(distances):
                if distance <= self.tolerance and distance < best_distance:
                    best_distance = distance
                    best_match = {
                        "student_id": class_students[i][1],
                        "name": class_students[i][2],
                        "student_code": class_students[i][3],
                        "class_name": c_name,
                        "confidence": 1.0 - distance
                    }
        
        return best_match
    
    async def match_face(self, unknown_encoding: np.ndarray, class_name: Optional[str] = None) -> MatchResult:
        """
        Match face encoding against in-memory encodings with tolerance 0.5.
        
        Requirements: 2.4, 2.5, 3.1, 3.2, 3.3
        
        Args:
            unknown_encoding: 128-dimensional face encoding to match
            class_name: Optional class name to limit search to specific class
            
        Returns:
            MatchResult with match details or matched=False if no match found
        """
        loop = asyncio.get_running_loop()
        match_dict = await loop.run_in_executor(
            self.executor,
            self._match_face_sync,
            unknown_encoding,
            class_name
        )
        
        if match_dict:
            return MatchResult(
                matched=True,
                student_id=match_dict["student_id"],
                student_name=match_dict["name"],
                student_code=match_dict["student_code"],
                class_name=match_dict["class_name"],
                confidence=match_dict["confidence"]
            )
        else:
            return MatchResult(
                matched=False,
                student_id=None,
                student_name=None,
                student_code=None,
                class_name=None,
                confidence=None
            )
    
    async def add_student_encoding(self, student_id: UUID, class_name: str, full_name: str, 
                                   student_code: str, encoding: np.ndarray) -> None:
        """
        Add a new student encoding to the in-memory cache immediately.
        
        Requirements: 2.3
        
        Args:
            student_id: Student UUID
            class_name: Class name
            full_name: Student full name
            student_code: Student code
            encoding: Face encoding array
        """
        self._add_student_encoding_sync(student_id, class_name, full_name, student_code, encoding)
    
    def _add_student_encoding_sync(self, student_id: UUID, class_name: str, full_name: str,
                                   student_code: str, encoding: np.ndarray) -> None:
        """
        Synchronous version of add_student_encoding for internal use.
        """
        if class_name not in self.known_encodings:
            self.known_encodings[class_name] = []
        
        self.known_encodings[class_name].append((
            encoding,
            str(student_id),
            full_name,
            student_code
        ))
        print(f"Added encoding for {student_code} to in-memory cache")
    
    def shutdown(self):
        """Shutdown the ThreadPoolExecutor"""
        self.executor.shutdown(wait=True)


# Global singleton instance
face_service = FaceService(tolerance=0.5, max_workers=4)
