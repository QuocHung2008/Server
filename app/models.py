from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Float, Boolean, TIMESTAMP, ForeignKey, func, Text, Index
from sqlalchemy.dialects.postgresql import UUID, BYTEA

Base = declarative_base()

class ClassModel(Base):
    __tablename__ = 'classes'
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name = Column(String(100), unique=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

class StudentModel(Base):
    __tablename__ = 'students'
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_code = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(200), nullable=False)
    class_id = Column(UUID(as_uuid=True), ForeignKey('classes.id', ondelete='CASCADE'), nullable=False)
    image_path = Column(Text)
    face_encoding = Column(BYTEA)
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    __table_args__ = (
        Index('idx_students_class', 'class_id'),
    )

class AttendanceRecordModel(Base):
    __tablename__ = 'attendance_records'
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_id = Column(UUID(as_uuid=True), ForeignKey('students.id', ondelete='CASCADE'), nullable=False)
    class_id = Column(UUID(as_uuid=True), ForeignKey('classes.id', ondelete='CASCADE'), nullable=False)
    device_id = Column(String(100))
    confidence = Column(Float)
    status = Column(String(20), default='present')
    recorded_at = Column(TIMESTAMP, server_default=func.now())
    
    __table_args__ = (
        Index('idx_attendance_recorded_at', 'recorded_at', postgresql_ops={'recorded_at': 'DESC'}),
        Index('idx_attendance_class_time', 'class_id', 'recorded_at', postgresql_ops={'recorded_at': 'DESC'}),
    )

class ApiKeyModel(Base):
    __tablename__ = 'api_keys'
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    key_hash = Column(String(64), unique=True, nullable=False)
    label = Column(String(100))
    class_id = Column(UUID(as_uuid=True), ForeignKey('classes.id', ondelete='SET NULL'))
    device_id = Column(String(100))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    last_used_at = Column(TIMESTAMP)
    
    __table_args__ = (
        Index('idx_api_keys_active', 'is_active', postgresql_where=Text('is_active = TRUE')),
    )
