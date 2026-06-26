from fastapi import APIRouter, Query, Response
import io
import openpyxl
from datetime import datetime
from app.database import pool

router = APIRouter(prefix="/api/attendance", tags=["attendance"])

@router.get("/")
async def get_attendance(class_id: str = None, date: str = None):
    if pool is None: return []
    query = """
        SELECT a.id, s.full_name as student_name, s.student_code, c.name as class_name, 
               a.device_id, a.confidence, a.status, a.recorded_at 
        FROM attendance_records a
        JOIN students s ON a.student_id = s.id
        JOIN classes c ON a.class_id = c.id
        WHERE 1=1
    """
    args = []
    if class_id:
        args.append(class_id)
        query += f" AND a.class_id = ${len(args)}"
    if date:
        args.append(date + "%") # Simple LIKE match for date string
        query += f" AND a.recorded_at::text LIKE ${len(args)}"
        
    query += " ORDER BY a.recorded_at DESC LIMIT 500"
    
    async with pool.acquire() as conn:
        records = await conn.fetch(query, *args)
        return [dict(r) for r in records]

@router.get("/export")
async def export_excel(class_id: str = None, date: str = None):
    records = await get_attendance(class_id, date)
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Attendance"
    
    headers = ["Thời gian", "Họ tên", "Mã SV", "Lớp", "Thiết bị", "Trạng thái", "Độ tin cậy"]
    ws.append(headers)
    
    for r in records:
        ws.append([
            r['recorded_at'].strftime("%Y-%m-%d %H:%M:%S") if isinstance(r['recorded_at'], datetime) else r['recorded_at'],
            r['student_name'],
            r['student_code'],
            r['class_name'],
            r['device_id'],
            r['status'],
            r['confidence']
        ])
        
    stream = io.BytesIO()
    wb.save(stream)
    
    filename = f"attendance_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return Response(
        content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
