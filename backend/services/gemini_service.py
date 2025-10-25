# gemini_service.py

import os
from typing import Any, Dict, Optional

try:
    import google.generativeai as genai
except Exception:  # library may not be installed in some environments
    genai = None


class GeminiService:
    """Service wrapper around Google Gemini API for F1 strategy use-cases.

    Methods:
      - analyze_tire_strategy: Analyze stint/tire plans and provide recommendations
      - predict_race_outcome: Predict finishing positions and key risks given inputs
      - explain_strategy_decision: Explain rationale for a chosen strategy
      - test_connection: Verify API key and model availability
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "models/gemini-1.5-pro",
        system_instruction: Optional[str] = None,
        temperature: float = 0.4,
        top_p: float = 0.95,
        top_k: int = 32,
        max_output_tokens: int = 2048,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model_name = model
        self.system_instruction = system_instruction or (
            "You are an expert Formula 1 race strategist. Be concise, factual, and actionable. "
            "Use bullet points, include assumptions, and highlight uncertainties."
        )
        self.generation_config = {
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "max_output_tokens": max_output_tokens,
        }

        if genai is None:
            # Defer import error until first call to allow environments without the SDK to import code
            self._client_ready = False
            return

        if not self.api_key:
            self._client_ready = False
            return

        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=self.system_instruction,
                generation_config=self.generation_config,
            )
            self._client_ready = True
        except Exception:
            self._client_ready = False

    # ---------------------- Public Methods ----------------------
    def analyze_tire_strategy(self, race_context: Dict[str, Any], strategy_plan: Dict[str, Any]) -> str:
        """Analyze a tire strategy plan.

        Args:
            race_context: dict with keys like track, laps, safety_car_prob, weather, degradation, pit_delta, etc.
            strategy_plan: dict with stint list like [{stint: 1, compound: "M", laps: 18, push: "medium"}, ...]

        Returns:
            A concise analysis with pros/cons, key risks, fuel/pace assumptions, and recommended tweaks.
        """
        prompt = self._compose_prompt(
            task="Analyze Tire Strategy",
            context=race_context,
            payload={"plan": strategy_plan},
            requirements=[
                "Assess stint lengths vs. expected degradation and undercut/overcut windows",
                "Consider safety car/VSC likelihood and optimal pit windows",
                "Quantify pit loss, warmup characteristics, and traffic risk",
                "Provide 2-3 actionable recommendations with rationale",
            ],
        )
        return self._generate_text(prompt)

    def predict_race_outcome(self, race_context: Dict[str, Any], competitors: Dict[str, Any]) -> str:
        """Predict race outcome distribution for key competitors.

        Args:
            race_context: overall race assumptions
            competitors: mapping of driver -> dict with quali_pos, tire_alloc, race_pace_delta, etc.

        Returns:
            Text summary with finishing position ranges, pit strategies, and probability notes.
        """
        prompt = self._compose_prompt(
            task="Predict Race Outcome",
            context=race_context,
            payload={"competitors": competitors},
            requirements=[
                "Provide finishing position range for top 5 targets",
                "Call out decisive moments: pit windows, tire offset, safety car",
                "Include probability-style language (e.g., likely/unlikely, 60-70%)",
            ],
        )
        return self._generate_text(prompt)

    def explain_strategy_decision(self, decision: str, data: Dict[str, Any]) -> str:
        """Explain rationale behind a strategy decision.

        Args:
            decision: the chosen strategy or change (e.g., "Extend stint 1 by 3 laps")
            data: supporting data (stint times, deg curves, weather, gaps, safety car risk)
        Returns:
            Short explanation with bullet points: rationale, trade-offs, and counterfactuals.
        """
        prompt = self._compose_prompt(
            task="Explain Strategy Decision",
            context={"decision": decision},
            payload={"evidence": data},
            requirements=[
                "Bullet points with clear rationale",
                "List trade-offs and risks",
                "Add a brief counterfactual: what if we did not make this choice?",
            ],
        )
        return self._generate_text(prompt)

    def test_connection(self) -> bool:
        """Verify that the Gemini API is reachable and credentials are valid."""
        if genai is None or not self.api_key:
            return False
        if not getattr(self, "_client_ready", False):
            return False
        try:
            # Lightweight ping
            resp = self.model.generate_content("Test")
            return bool(resp and (getattr(resp, "text", None) or getattr(resp, "candidates", None)))
        except Exception:
            return False

    # ---------------------- Internal Helpers ----------------------
    def _compose_prompt(
        self,
        task: str,
        context: Dict[str, Any],
        payload: Dict[str, Any],
        requirements: Optional[list] = None,
    ) -> str:
        req = "\n- ".join(requirements or [])
        return (
            f"Task: {task}\n"
            f"System: {self.system_instruction}\n\n"
            f"Context:\n{self._safe_format_dict(context)}\n\n"
            f"Input:\n{self._safe_format_dict(payload)}\n\n"
            f"Requirements:\n- {req if req else 'Be concise and actionable.'}\n\n"
            "Return clear, structured text with bullet points where appropriate."
        )

    def _generate_text(self, prompt: str) -> str:
        if genai is None or not getattr(self, "_client_ready", False):
            return (
                "Gemini client not initialized. Ensure google-generativeai is installed and GEMINI_API_KEY "
                "or GOOGLE_API_KEY is set."
            )
        try:
            response = self.model.generate_content(prompt)
            # SDK may return .text or segments; normalize
            if hasattr(response, "text") and response.text:
                return response.text
            if hasattr(response, "candidates") and response.candidates:
                parts = []
                for cand in response.candidates:
                    try:
                        parts.append(cand.content.parts[0].text)
                    except Exception:
                        continue
                return "\n".join([p for p in parts if p]) or ""
            return ""
        except Exception as e:
            return f"Gemini API error: {e}"

    @staticmethod
    def _safe_format_dict(d: Dict[str, Any]) -> str:
        try:
            import json
            return json.dumps(d, indent=2, ensure_ascii=False)
        except Exception:
            return str(d)
