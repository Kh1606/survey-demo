from fastapi import FastAPI, HTTPException
from sqlalchemy import Column, Integer, String, JSON, ForeignKey, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
import datetime
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
import csv, io

from database import engine, SessionLocal

Base = declarative_base()
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

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

Base.metadata.create_all(bind=engine)

# ─── ENDPOINTS ─────────────────────────────────────────
class SurveyCreate(BaseModel):
    title: str
    config: dict          # {"questions":[...] }

class SurveyUpdate(BaseModel):            # <-- NEW
    config: dict

@app.post("/surveys", status_code=201)
def create_survey(data: SurveyCreate):
    db = SessionLocal()
    survey = Survey(title=data.title, config=data.config)
    db.add(survey); db.commit(); db.refresh(survey)
    db.close()
    return {"id": survey.id}

@app.put("/surveys/{survey_id}", status_code=204)      # <-- NEW
def update_survey(survey_id: int, data: SurveyUpdate):
    db = SessionLocal()
    survey = db.query(Survey).get(survey_id)
    if not survey:
        db.close()
        raise HTTPException(status_code=404, detail="Survey not found")
    survey.config = data.config
    db.commit(); db.close()

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
    db = SessionLocal()
    rows, header = [], None
    for r in db.query(Response).filter_by(survey_id=survey_id).all():
        row = {"response_id": r.id, "submitted_at": r.submitted_at.isoformat()}
        for a in db.query(Answer).filter_by(response_id=r.id):
            row[a.question_id] = a.answer
        rows.append(row)
        header = header or list(row.keys())
    db.close()
    row_list = [[row[col] for col in header] for row in rows]
    return {"columns": header, "data": row_list}

@app.get("/surveys/{survey_id}/export")
def export_csv(survey_id: int):
    flat = get_flat_responses(survey_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(flat["columns"])
    writer.writerows(flat["data"])
    buf.seek(0)
    return StreamingResponse(buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename=\"survey_{survey_id}.csv\"'})

@app.get("/surveys/{survey_id}/responses")
def get_responses(survey_id: int):
    db = SessionLocal()
    out=[]
    for r in db.query(Response).filter_by(survey_id=survey_id).all():
        answers = db.query(Answer).filter_by(response_id=r.id).all()
        out.append({"response_id":r.id,"submitted_at":r.submitted_at,
                    "answers":{a.question_id:a.answer for a in answers}})
    db.close()
    return out
