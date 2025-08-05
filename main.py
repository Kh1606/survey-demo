from fastapi import FastAPI, HTTPException
from sqlalchemy import Column, Integer, String, JSON, ForeignKey, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
import datetime
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import csv, io

from database import engine, SessionLocal
from fastapi.staticfiles import StaticFiles    # ← NEW


Base = declarative_base()
app = FastAPI()            # ①  APP OBJECT FIRST
app.mount("/static", StaticFiles(directory="static"), name="static")  # ← NEW
# ─── MODELS ────────────────────────────────────────────
class Survey(Base):
    __tablename__ = "surveys"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    config = Column(JSON, nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)

class Response(Base):
    __tablename__ = "responses"
    id = Column(Integer, primary_key=True, index=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"))
    submitted_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)

class Answer(Base):
    __tablename__ = "answers"
    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("responses.id"))
    question_id = Column(String, nullable=False)
    answer = Column(JSON, nullable=False)

# Create tables
Base.metadata.create_all(bind=engine)

# ─── ENDPOINTS ─────────────────────────────────────────
class SurveyCreate(BaseModel):
    title: str
    config: dict          # {"questions": [...]}

@app.post("/surveys", status_code=201)
def create_survey(data: SurveyCreate):
    db = SessionLocal()
    survey = Survey(title=data.title, config=data.config)
    db.add(survey); db.commit(); db.refresh(survey)
    db.close()
    return {"id": survey.id}

@app.on_event("startup")
def startup():
    db = SessionLocal()
    if db.query(Survey).count() == 0:
        sample = Survey(
            title="Customer Feedback",
            config={
                "questions": [
                    {"id": "q1", "type": "text", "label": "What is your name?"},
                    {"id": "q2", "type": "rating", "label": "Rate our service (1-5)"}
                ]
            }
        )
        db.add(sample); db.commit()
        print("✅ Sample survey created with id", sample.id)
    db.close()

@app.get("/surveys/{survey_id}")
def get_survey(survey_id: int):
    db = SessionLocal()
    survey = db.query(Survey).get(survey_id)
    db.close()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    return {"id": survey.id, "title": survey.title, "config": survey.config}

@app.post("/surveys/{survey_id}/responses")
def submit_response(survey_id: int, data: dict):
    db = SessionLocal()
    if not db.query(Survey).get(survey_id):
        db.close()
        raise HTTPException(status_code=404, detail="Survey not found")
    resp = Response(survey_id=survey_id); db.add(resp); db.commit(); db.refresh(resp)
    for qid, ans in data.get("answers", {}).items():
        db.add(Answer(response_id=resp.id, question_id=qid, answer=ans))
    db.commit(); db.close()
    return {"response_id": resp.id}

@app.get("/surveys/{survey_id}/responses/flat")
def get_flat_responses(survey_id: int):
    """Return columns+rows so the front-end can build a table easily."""
    db = SessionLocal()
    rows, header = [], None
    for r in db.query(Response).filter_by(survey_id=survey_id).all():
        row = {
            "response_id": r.id,
            "submitted_at": r.submitted_at.isoformat()
        }
        for a in db.query(Answer).filter_by(response_id=r.id):
            row[a.question_id] = a.answer
        rows.append(row)
        header = header or list(row.keys())       # remember column order
    db.close()
    # Convert rows to a list-of-lists so it serialises compactly
    row_list = [[row[col] for col in header] for row in rows]
    return {"columns": header, "data": row_list}

@app.get("/surveys/{survey_id}/export")
def export_csv(survey_id: int):
    """Download results as CSV (opens in Excel/Sheets)."""
    flat = get_flat_responses(survey_id)
    buf  = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(flat["columns"])
    writer.writerows(flat["data"])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename=\"survey_{survey_id}.csv\"'}
    )

@app.get("/surveys/{survey_id}/responses")
def get_responses(survey_id: int):
    db = SessionLocal()
    records = []
    for r in db.query(Response).filter_by(survey_id=survey_id).all():
        answers = db.query(Answer).filter_by(response_id=r.id).all()
        records.append({
            "response_id": r.id,
            "submitted_at": r.submitted_at,
            "answers": {a.question_id: a.answer for a in answers}
        })
    db.close()
    return records
