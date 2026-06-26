from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class ClassBase(BaseModel):
    name: str

class ClassCreate(ClassBase):
    pass

class ClassResponse(ClassBase):
    id: UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class StudentBase(BaseModel):
    student_code: str
    full_name: str
    class_id: UUID

class StudentCreate(StudentBase):
    pass

class StudentResponse(StudentBase):
    id: UUID
    image_path: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AttendanceResponse(BaseModel):
    id: UUID
    student_id: UUID
    class_id: UUID
    device_id: Optional[str] = None
    confidence: Optional[float] = None
    status: str
    recorded_at: datetime
    model_config = ConfigDict(from_attributes=True)
    
class AttendanceUpdatePayload(BaseModel):
    id: str
    student_name: str
    student_code: str
    class_name: str
    device_id: str
    confidence: float
    status: str
    recorded_at: str

class WsResponse(BaseModel):
    status: str
    name: Optional[str] = None
    student_id: Optional[str] = None
    class_name: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: str
    device_id: str
