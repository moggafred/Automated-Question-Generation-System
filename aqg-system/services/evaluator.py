# Guardrail Agent Framework for assessing quiz readability metrics
class QuizEvaluationAgent:
    @staticmethod
    def audit_assessment(quiz_data: dict) -> dict:
        """
        Performs a functional quality sweep of the structural JSON metadata payload to remove artifacts.
        Ensures options count integrity and removes corrupted nodes.
        """
        cleaned_questions = []
        for index, item in enumerate(quiz_data.get("questions", [])):
            # Enforce sequential indexing safety
            item["id"] = index + 1
            
            # Validation clean sweeps 
            if item["type"] == "multiple-choice":
                if not item.get("options") or len(item["options"]) < 4:
                    continue # Discard questions with broken choice allocations
                if item["correct_answer"] not in item["options"]:
                    item["options"][0] = item["correct_answer"] # Safely secure correctness inclusion
            
            cleaned_questions.append(item)
            
        quiz_data["questions"] = cleaned_questions
        return quiz_data