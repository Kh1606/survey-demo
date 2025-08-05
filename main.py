from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, Integer, String, JSON, ForeignKey, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
import datetime, csv, io
from pydantic import BaseModel

from database import engine, SessionLocal

# ─── setup ─────────────────────────────────────────────────────────────
Base = declarative_base()
app  = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# ─── models ────────────────────────────────────────────────────────────
class Survey(Base):
    __tablename__ = "surveys"
    id        = Column(Integer, primary_key=True, index=True)
    title     = Column(String,  nullable=False)
    config    = Column(JSON,    nullable=False)
    created_at= Column(TIMESTAMP, default=datetime.datetime.utcnow)

class Response(Base):
    __tablename__ = "responses"
    id        = Column(Integer, primary_key=True, index=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"))
    submitted_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)

class Answer(Base):
    __tablename__ = "answers"
    id          = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("responses.id"))
    question_id = Column(String, nullable=False)
    answer      = Column(JSON,  nullable=False)

Base.metadata.create_all(bind=engine)

# ─── ensure survey 1 exists & has correct questions ────────────────────
@app.on_event("startup")
def ensure_survey_one():
    db = SessionLocal()
    new_cfg = {
        "questions": [
            {"id": "q1", "type": "text", "label": "Company name"},
            {"id": "q2", "type": "text", "label": "Your name"},
            {"id": "q3", "type": "text", "label": "Company address"}
        ]
    }
    survey = db.query(Survey).get(1)
    if survey:
        survey.config = new_cfg          # overwrite existing
    else:
        survey = Survey(id=1, title="Company Info", config=new_cfg)
        db.add(survey)
    db.commit(); db.close()

# ─── request/response models ───────────────────────────────────────────
class SurveyCreate(BaseModel):
    title: str
    config: dict        # {"questions":[...]}

# ─── routes ────────────────────────────────────────────────────────────
@app.post("/surveys", status_code=201)
def create_survey(data: SurveyCreate):
    db = SessionLocal()
    s = Survey(title=data.title, config=data.config)
    db.add(s); db.commit(); db.refresh(s); db.close()
    return {"id": s.id}

@app.get("/surveys/{sid}")
def get_survey(sid: int):
    db = SessionLocal()
    s = db.query(Survey).get(sid); db.close()
    if not s: raise HTTPException(404, "Survey not found")
    return {"id": s.id, "title": s.title, "config": s.config}

@app.post("/surveys/{sid}/responses")
def submit_response(sid: int, data: dict):
    db = SessionLocal()
    if not db.query(Survey).get(sid):
        db.close(); raise HTTPException(404, "Survey not found")
    r = Response(survey_id=sid); db.add(r); db.commit(); db.refresh(r)
    for qid, ans in data.get("answers", {}).items():
        db.add(Answer(response_id=r.id, question_id=qid, answer=ans))
    db.commit(); db.close()
    return {"response_id": r.id}

# flat JSON for results.html
@app.get("/surveys/{sid}/responses/flat")
def flat(sid: int):
    db = SessionLocal(); rows, header = [], None
    for r in db.query(Response).filter_by(survey_id=sid):
        row = {"response_id": r.id, "submitted_at": r.submitted_at.isoformat()}
        for a in db.query(Answer).filter_by(response_id=r.id):
            row[a.question_id] = a.answer
        rows.append(row); header = header or list(row.keys())
    db.close()
    data = [[row.get(col) for col in header] for row in rows]
    return {"columns": header, "data": data}

# CSV export
@app.get("/surveys/{sid}/export")
def export_csv(sid: int):
    flat_data = flat(sid)
    buf = io.StringIO()
    csv.writer(buf).writerows([flat_data["columns"], *flat_data["data"]])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename=\"survey_{sid}.csv\"'})

# full nested responses (optional)
@app.get("/surveys/{sid}/responses")
def nested(sid: int):
    db = SessionLocal(); out=[]
    for r in db.query(Response).filter_by(survey_id=sid):
        answers = db.query(Answer).filter_by(response_id=r.id)
        out.append({"response_id":r.id,"submitted_at":r.submitted_at,
                    "answers":{a.question_id:a.answer for a in answers}})
    db.close(); return out
