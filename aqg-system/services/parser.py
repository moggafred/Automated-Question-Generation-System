import fitz  # PyMuPDF
from fastapi import HTTPException

class DocumentParserService:
    @staticmethod
    def extract_text(file_bytes: bytes, filename: str) -> str:
        """Extract raw text content from uploaded files seamlessly."""
        if filename.endswith(".txt"):
            return file_bytes.decode("utf-8")
        elif filename.endswith(".pdf"):
            try:
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                text = ""
                for page in doc:
                    text += page.get_text()
                if not text.strip():
                    raise HTTPException(status_code=400, detail="PDF content is empty or contains unreadable scanned images.")
                return text
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to parse PDF document: {str(e)}")
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Please upload .txt or .pdf files.")

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
        """Splits text into chunks using overlapping windows to protect context boundaries."""
        chunks = []
        words = text.split()
        current_idx = 0
        while current_idx < len(words):
            chunk = words[current_idx:current_idx + chunk_size]
            chunks.append(" ".join(chunk))
            current_idx += chunk_size - overlap
            if len(words) - current_idx < overlap:
                break
        return chunks