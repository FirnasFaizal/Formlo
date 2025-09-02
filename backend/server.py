from fastapi import FastAPI, APIRouter, HTTPException, Depends, File, UploadFile, Form, Request
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from authlib.integrations.starlette_client import OAuth
import os
import logging
import uuid
import json
import tempfile
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
import PyPDF2
from docx import Document
import pytesseract
from PIL import Image
import io
import asyncio

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app
app = FastAPI(title="Formlo - Document to Google Forms Converter")

# Session middleware for OAuth
app.add_middleware(SessionMiddleware, secret_key=os.environ.get('SECRET_KEY', 'your-secret-key-here'))

# OAuth setup
oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
    access_token_url='https://oauth2.googleapis.com/token',
    api_base_url='https://openidconnect.googleapis.com/v1/',
    client_kwargs={
        'scope': 'openid email profile https://www.googleapis.com/auth/forms.body https://www.googleapis.com/auth/drive.file'
    }
)

# Google Forms API setup
GOOGLE_CREDENTIALS = json.loads(os.environ.get('GOOGLE_CREDENTIALS', '{}'))
SCOPES = [
    'https://www.googleapis.com/auth/forms.body',
    'https://www.googleapis.com/auth/drive.file'
]

def get_google_service():
    credentials = service_account.Credentials.from_service_account_info(
        GOOGLE_CREDENTIALS, scopes=SCOPES
    )
    return build('forms', 'v1', credentials=credentials)

# LLM Chat setup for Gemini
def get_llm_chat(session_id: str):
    api_key = os.environ.get('EMERGENT_LLM_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="LLM API key not configured")
    
    return LlmChat(
        api_key=api_key,
        session_id=session_id,
        system_message="You are an expert at analyzing documents and extracting structured questions for forms. Extract questions, identify question types (multiple choice, short answer, long answer, true/false), and provide answer options when applicable."
    ).with_model("gemini", "gemini-2.0-flash")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Pydantic Models
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class GeneratedForm(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    original_filename: str
    form_id: str
    form_title: str
    form_url: str
    questions_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processing_status: str = "completed"

class ProcessingJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    filename: str
    status: str = "processing"  # processing, completed, failed
    progress: int = 0
    error_message: Optional[str] = None
    form_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# Helper Functions
async def extract_text_from_file(file: UploadFile) -> str:
    """Extract text from uploaded file"""
    content = await file.read()
    text = ""
    
    if file.filename.lower().endswith('.pdf'):
        # Extract text from PDF
        with io.BytesIO(content) as pdf_buffer:
            pdf_reader = PyPDF2.PdfReader(pdf_buffer)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
    
    elif file.filename.lower().endswith('.docx'):
        # Extract text from DOCX
        with io.BytesIO(content) as docx_buffer:
            doc = Document(docx_buffer)
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
    
    elif file.filename.lower().endswith('.txt'):
        # Extract text from TXT
        text = content.decode('utf-8')
    
    return text.strip()

async def analyze_text_with_llm(text: str, session_id: str) -> Dict[str, Any]:
    """Analyze text with Gemini to extract questions"""
    chat = get_llm_chat(session_id)
    
    prompt = f"""
    Analyze the following text and extract structured questions that can be converted into a Google Form.
    
    Text to analyze:
    {text}
    
    Please extract questions and return them in the following JSON format:
    {{
        "form_title": "Generated form title based on content",
        "form_description": "Brief description of the form",
        "questions": [
            {{
                "title": "Question text",
                "type": "RADIO|CHECKBOX|SHORT_ANSWER|PARAGRAPH_TEXT|TRUE_FALSE",
                "required": true|false,
                "options": ["option1", "option2"] // only for RADIO, CHECKBOX, TRUE_FALSE
            }}
        ]
    }}
    
    Question type mapping:
    - RADIO: Single choice (multiple choice)
    - CHECKBOX: Multiple choice (checkboxes)
    - SHORT_ANSWER: Short text response
    - PARAGRAPH_TEXT: Long text response
    - TRUE_FALSE: True/False questions (use RADIO with True/False options)
    
    Make sure to extract meaningful questions and provide appropriate answer choices when applicable.
    """
    
    user_message = UserMessage(text=prompt)
    response = await chat.send_message(user_message)
    
    try:
        # Parse JSON response
        import re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            raise ValueError("No JSON found in response")
    except Exception as e:
        # Fallback response
        return {
            "form_title": "Extracted Questions Form",
            "form_description": "Questions extracted from uploaded document",
            "questions": [
                {
                    "title": "Please provide feedback on the document content",
                    "type": "PARAGRAPH_TEXT",
                    "required": False
                }
            ]
        }

async def create_google_form(form_data: Dict[str, Any]) -> Dict[str, str]:
    """Create Google Form using the Forms API"""
    service = get_google_service()
    
    # Create the form
    form_body = {
        "info": {
            "title": form_data["form_title"],
            "description": form_data.get("form_description", "")
        }
    }
    
    form = service.forms().create(body=form_body).execute()
    form_id = form["formId"]
    
    # Add questions
    requests = []
    for i, question in enumerate(form_data["questions"]):
        if question["type"] == "RADIO":
            question_item = {
                "title": question["title"],
                "questionItem": {
                    "question": {
                        "required": question.get("required", False),
                        "choiceQuestion": {
                            "type": "RADIO",
                            "options": [{"value": option} for option in question.get("options", ["Option 1", "Option 2"])]
                        }
                    }
                }
            }
        elif question["type"] == "CHECKBOX":
            question_item = {
                "title": question["title"],
                "questionItem": {
                    "question": {
                        "required": question.get("required", False),
                        "choiceQuestion": {
                            "type": "CHECKBOX",
                            "options": [{"value": option} for option in question.get("options", ["Option 1", "Option 2"])]
                        }
                    }
                }
            }
        elif question["type"] == "SHORT_ANSWER":
            question_item = {
                "title": question["title"],
                "questionItem": {
                    "question": {
                        "required": question.get("required", False),
                        "textQuestion": {
                            "paragraph": False
                        }
                    }
                }
            }
        else:  # PARAGRAPH_TEXT
            question_item = {
                "title": question["title"],
                "questionItem": {
                    "question": {
                        "required": question.get("required", False),
                        "textQuestion": {
                            "paragraph": True
                        }
                    }
                }
            }
        
        requests.append({
            "createItem": {
                "item": question_item,
                "location": {"index": i}
            }
        })
    
    # Batch update to add all questions
    if requests:
        batch_update_body = {"requests": requests}
        service.forms().batchUpdate(formId=form_id, body=batch_update_body).execute()
    
    return {
        "form_id": form_id,
        "form_url": f"https://docs.google.com/forms/d/{form_id}/edit"
    }

# Auth dependency
async def get_current_user(request: Request) -> Optional[User]:
    user_data = request.session.get('user')
    if user_data:
        return User(**user_data)
    return None

async def require_auth(request: Request) -> User:
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

# API Routes
@api_router.get("/")
async def root():
    return {"message": "Formlo API - Document to Google Forms Converter"}

@api_router.get("/auth/login")
async def login(request: Request):
    redirect_uri = 'https://test-runner-9.preview.emergentagent.com/api/auth/callback'
    return await oauth.google.authorize_redirect(request, redirect_uri)

@api_router.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')
    
    if user_info:
        user_data = {
            "id": str(uuid.uuid4()),
            "email": user_info['email'],
            "name": user_info['name'],
            "picture": user_info.get('picture'),
            "created_at": datetime.now(timezone.utc)
        }
        
        # Save or update user in database
        existing_user = await db.users.find_one({"email": user_info['email']})
        if not existing_user:
            await db.users.insert_one(user_data)
        else:
            user_data = existing_user
        
        # Store user in session
        request.session['user'] = {
            "id": str(user_data["id"]),
            "email": user_data["email"],
            "name": user_data["name"],
            "picture": user_data.get("picture")
        }
    
    return RedirectResponse(url='/')

@api_router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out successfully"}

@api_router.get("/auth/me")
async def get_me(user: User = Depends(require_auth)):
    return user

@api_router.post("/upload", response_model=ProcessingJob)
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(require_auth)
):
    # Validate file type
    allowed_extensions = {'.pdf', '.docx', '.txt'}
    file_extension = Path(file.filename).suffix.lower()
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400, 
            detail=f"File type {file_extension} not supported. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Create processing job
    job = ProcessingJob(
        user_id=user.id,
        filename=file.filename,
        status="processing"
    )
    
    # Save job to database
    await db.processing_jobs.insert_one(job.dict())
    
    # Process file asynchronously (in real app, use background tasks)
    try:
        # Extract text
        text = await extract_text_from_file(file)
        
        if not text.strip():
            raise ValueError("No text could be extracted from the file")
        
        # Update progress
        await db.processing_jobs.update_one(
            {"id": job.id},
            {"$set": {"progress": 30, "status": "analyzing"}}
        )
        
        # Analyze with LLM
        analysis = await analyze_text_with_llm(text, job.id)
        
        # Update progress
        await db.processing_jobs.update_one(
            {"id": job.id},
            {"$set": {"progress": 60, "status": "creating_form"}}
        )
        
        # Create Google Form
        form_result = await create_google_form(analysis)
        
        # Save generated form
        generated_form = GeneratedForm(
            user_id=user.id,
            original_filename=file.filename,
            form_id=form_result["form_id"],
            form_title=analysis["form_title"],
            form_url=form_result["form_url"],
            questions_count=len(analysis["questions"])
        )
        
        await db.generated_forms.insert_one(generated_form.dict())
        
        # Update job as completed
        await db.processing_jobs.update_one(
            {"id": job.id},
            {"$set": {
                "progress": 100,
                "status": "completed",
                "form_id": form_result["form_id"]
            }}
        )
        
    except Exception as e:
        # Update job as failed
        await db.processing_jobs.update_one(
            {"id": job.id},
            {"$set": {
                "status": "failed",
                "error_message": str(e)
            }}
        )
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
    
    return job

@api_router.get("/jobs/{job_id}", response_model=ProcessingJob)
async def get_job_status(job_id: str, user: User = Depends(require_auth)):
    job = await db.processing_jobs.find_one({"id": job_id, "user_id": user.id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ProcessingJob(**job)

@api_router.get("/forms", response_model=List[GeneratedForm])
async def get_user_forms(user: User = Depends(require_auth)):
    forms = await db.generated_forms.find(
        {"user_id": user.id}
    ).sort("created_at", -1).to_list(100)
    return [GeneratedForm(**form) for form in forms]

@api_router.delete("/forms/{form_id}")
async def delete_form(form_id: str, user: User = Depends(require_auth)):
    result = await db.generated_forms.delete_one({
        "form_id": form_id,
        "user_id": user.id
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Form not found")
    return {"message": "Form deleted successfully"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()