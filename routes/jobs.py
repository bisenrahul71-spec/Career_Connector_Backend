from fastapi import APIRouter, HTTPException, UploadFile, File
from database import db
from models import JobPost
from bson import ObjectId
import PyPDF2
import io
import google.generativeai as genai
import json
import os

router = APIRouter()

@router.post("/")
async def create_job(job: JobPost):
    new_job = job.dict()
    result = await db["jobs"].insert_one(new_job)
    return {"message": "Job posted successfully", "id": str(result.inserted_id)}

@router.get("/")
async def get_jobs():
    jobs = []
    async for job in db["jobs"].find():
        job["_id"] = str(job["_id"])
        jobs.append(job)
    return jobs

@router.get("/{job_id}")
async def get_job(job_id: str):
    job = await db["jobs"].find_one({"_id": ObjectId(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["_id"] = str(job["_id"])
    return job

# ✅ New endpoint — extract JD from uploaded file
@router.post("/extract-jd")
async def extract_jd(file: UploadFile = File(...)):
    contents = await file.read()
    text = ""
    # Extract text based on file type
    filename = file.filename.lower()
    if filename.endswith(".pdf"):
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(contents))
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
    elif filename.endswith(".txt"):
        text = contents.decode("utf-8")
    elif filename.endswith(".docx"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(contents))
            text = "\n".join([para.text for para in doc.paragraphs])
        except:
            raise HTTPException(status_code=400, detail="Could not read .docx file. Please install python-docx.")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, DOCX, or TXT.")

    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from file.")

    # Use Gemini to extract structured JD info
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-flash-latest")
    prompt = f"""
    Extract job details from this job description text.
    Return ONLY a JSON object in this exact format:
    {{
        "title": "job title or empty string",
        "company": "company name or empty string",
        "location": "location or empty string",
        "description": "full job description text",
        "skills": "comma separated skills like: Python, SQL, Power BI"
    }}
    
    Job description text:
    {text[:4000]}
    """
    response = model.generate_content(prompt)
    cleaned = response.text.replace("```json", "").replace("```", "").strip()
    try:
        result = json.loads(cleaned)
    except:
        result = {"description": text[:2000], "skills": ""}
    return result
