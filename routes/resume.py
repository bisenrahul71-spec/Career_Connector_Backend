from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from database import db
import PyPDF2
import io
import google.generativeai as genai
from jose import jwt, JWTError
from datetime import datetime
import json
import os

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/login")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        user = await db["users"].find_one({"email": email})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {"email": email, "id": str(user["_id"]), "name": user["name"]}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    user=Depends(get_current_user)
):
    # Read PDF
    contents = await file.read()
    pdf_reader = PyPDF2.PdfReader(io.BytesIO(contents))

    # Extract text
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text() or ""

    # Use Gemini to extract skills
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-flash-latest")
    prompt = f"""
    Extract all technical and soft skills from this resume text.
    Return ONLY a JSON array of skills like: ["Python", "SQL", "Communication"]
    Resume text:
    {text[:3000]}
    """
    response = model.generate_content(prompt)
    skills_text = response.text.replace("```json", "").replace("```", "").strip()
    try:
        skills_list = json.loads(skills_text)
    except:
        skills_list = []

    # Save skills to MongoDB
    await db["student_profiles"].update_one(
        {"user_id": user["id"]},
        {"$set": {
            "user_id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "skills": skills_list,
            "updated_at": datetime.utcnow().isoformat()
        }},
        upsert=True
    )

    return {
        "extracted_text": text[:500],
        "skills": skills_text
    }
