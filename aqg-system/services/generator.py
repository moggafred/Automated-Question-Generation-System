from pydantic import BaseModel, Field
from typing import List, Literal
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from config.settings import settings

class QuestionSchema(BaseModel):
    id: int = Field(..., description="Unique sequential identifier for the question.")
    type: Literal["multiple-choice", "short-answer", "fill-in-the-blank"] = Field(..., description="Type of question generated.")
    question: str = Field(..., description="The highly specific interrogative question text derived directly from source content.")
    options: List[str] = Field(default=[], description="Exactly 4 items if multiple-choice. Array must be empty for short-answer and fill-in-the-blank.")
    correct_answer: str = Field(..., description="The absolute correct answer option or text.")
    explanation: str = Field(..., description="A detailed psychometric validation rationale explaining why the correct choice is accurate and why distractors fail.")

class AssessmentSchema(BaseModel):
    quiz_title: str = Field(..., description="A crisp title reflecting the thematic subject of the context.")
    questions: List[QuestionSchema] = Field(..., description="Collection of generated questions.")

class QuestionGeneratorService:
    def __init__(self):
        kwargs: dict = {
            "model": settings.LLM_MODEL,
            "openai_api_key": settings.OPENAI_API_KEY,
            "temperature": 0.3,
        }
        if settings.LLM_BASE_URL:
            kwargs["base_url"] = settings.LLM_BASE_URL
        if settings.LLM_PROVIDER == "local":
            kwargs = {
                "model": settings.LOCAL_LLM_MODEL,
                "base_url": settings.LOCAL_LLM_BASE_URL,
                "openai_api_key": "EMPTY",
                "temperature": 0.3,
            }
        self.llm = ChatOpenAI(**kwargs)
        self.output_parser = JsonOutputParser(pydantic_object=AssessmentSchema)
        
    def generate_quiz(self, context_chunk: str, question_type: str, quantity: int) -> dict:
        """Generates structured quizzes using guaranteed schema JSON forcing pipelines."""
        system_instructions = (
            "You are an expert psychometrician and academic curriculum assessor.\n"
            "Your task is to generate high-quality evaluation assessments based strictly on the provided context.\n"
            "Requirements:\n"
            "1. Avoid meta-phrasing like 'According to the passage' or 'Based on the text'. Make questions direct.\n"
            "2. If multiple-choice, create exactly 4 highly plausible options where only 1 is correct. Distractors must map to common logical fallacies or conceptual errors.\n"
            "3. If fill-in-the-blank, target critical terms or operational metrics. Replace the exact target phrase in the question with '_______'.\n"
            "4. Ensure full formatting alignment with the requested JSON schema output formatting requirements.\n"
            "{format_instructions}"
        )
        
        user_prompt = (
            "Generate {quantity} {question_type} questions derived directly from this context chunk:\n\n"
            "--- START CONTEXT ---\n"
            "{context}\n"
            "--- END CONTEXT ---"
        )
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_instructions),
            ("user", user_prompt)
        ])
        
        # Inject standard format instructions expected by JSON output parser mapping
        format_inst = self.output_parser.get_format_instructions()
        chain = prompt | self.llm | self.output_parser
        
        # Let upstream failures propagate so the API layer can surface a proper 500
        return chain.invoke({
            "format_instructions": format_inst,
            "quantity": quantity,
            "question_type": question_type,
            "context": context_chunk
        })