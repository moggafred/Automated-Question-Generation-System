import logging

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aqg")
from config.settings import settings
from services.parser import DocumentParserService
from services.generator import QuestionGeneratorService
from services.evaluator import QuizEvaluationAgent
from services.retriever import DocumentRetriever

app = FastAPI(title="Automated Question Generation API Engine", version="1.0.0", debug=settings.DEBUG)

# Setup framework configuration allocations for core engines
generator_service = QuestionGeneratorService()

# 7. Add a /health endpoint returning {"status": "ok"}
@app.get("/health", status_code=200)
async def health_check():
    return {"status": "ok"}

@app.post("/api/v1/generate")
async def api_generate_questions(
    file: UploadFile = File(...),
    type: str = Form("multiple-choice"),
    count: int = Form(3),
    topic: str = Form("")
):
    # Ensure parameter validation boundaries
    if count < 1 or count > 10:
        raise HTTPException(status_code=400, detail="Count configuration constraint violation: Please select between 1 and 10 questions.")

    try:
        file_bytes = b""
        while chunk := await file.read(1024 * 1024):
            file_bytes += chunk
            if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploaded file exceeds the {settings.MAX_UPLOAD_SIZE // (1024 * 1024)}MB size limit.",
                )
        raw_text = DocumentParserService.extract_text(file_bytes, file.filename)

        # Process text chunks
        chunks = DocumentParserService.chunk_text(raw_text)
        if not chunks:
            raise HTTPException(status_code=400, detail="Document contains insufficient alphanumeric depth to form structured context grids.")

        # 1. Wire the retriever: ingest the chunk indexes for semantic retrieval
        retriever = DocumentRetriever(dim=settings.RAG_EMBED_DIM)
        retriever.index_chunks(chunks)

        # 2. Honor the topic param: derive the retrieval query from it
        search_query = topic.strip() if topic.strip() else "key concepts and main summaries"
        relevant_chunks = retriever.retrieve(query=search_query, top_k=settings.RAG_TOP_K)
        combined_context = "\n\n".join(relevant_chunks) if relevant_chunks else chunks[0]

        # Generate questions from the retrieved context nodes
        raw_quiz = generator_service.generate_quiz(combined_context, type, count)

        # Apply local validation guardrail filters
        sanitized_quiz = QuizEvaluationAgent.audit_assessment(raw_quiz)
        return sanitized_quiz
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled failure during question generation: %s", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")

# Mount Static Client UI interface engines
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=settings.DEBUG)