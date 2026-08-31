from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from database import db
import PyPDF2
import io
import google.generativeai as genai
import cloudinary
import cloudinary.uploader
from jose import jwt, JWTError
from datetime import datetime
import json
import os

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/login")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

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

    # Upload the actual file to Cloudinary
    resume_url = None
    try:
        upload_result = cloudinary.uploader.upload(
            io.BytesIO(contents),
            resource_type="raw",
            folder="resumes",
            public_id=f"{user['id']}_resume",
            overwrite=True,
        )
        resume_url = upload_result.get("secure_url")
    except Exception as e:
        print(f"Cloudinary upload failed: {e}")

    # Use Gemini to extract skills
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = f"""
    Extract all technical and soft skills from this resume text.
    Return ONLY a JSON array of skills like: ["Python", "SQL", "Communication"]
    Resume text:
    {text[:3000]}
    """
    try:
        response = model.generate_content(
            prompt,
            request_options={"timeout": 60}  # give Gemini up to 60s instead of default
        )
        skills_text = response.text.replace("```json", "").replace("```", "").strip()
        try:
            skills_list = json.loads(skills_text)
        except Exception as e:
            print(f"Failed to parse skills JSON: {e}")
            skills_list = []
    except Exception as e:
        print(f"Gemini skill extraction failed: {e}")
        skills_text = "[]"
        skills_list = []

    # Save skills + resume URL to MongoDB
    await db["student_profiles"].update_one(
        {"user_id": user["id"]},
        {"$set": {
            "user_id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "skills": skills_list,
            "resume_url": resume_url,
            "updated_at": datetime.utcnow().isoformat()
        }},
        upsert=True
    )

    return {
        "extracted_text": text[:500],
        "skills": skills_text,
        "resume_url": resume_url
    }
