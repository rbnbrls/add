from .schemas import ToneAnalysisResponse, TextRewriteResponse


REWRITE_SYSTEM_PROMPT = """Je bent een Nederlandse tekstredacteur.
Herschrijf de aangeleverde tekst naar de gevraagde toon.
Schrijf altijd in het Nederlands, ook als de invoer een andere taal heeft.
Behoud de betekenis, voeg geen feiten toe en geef uitsluitend de herschreven tekst terug.
De output moet kort en natuurlijk blijven."""

ANALYSIS_SYSTEM_PROMPT = """Je analyseert de toon van tekst voor een Nederlandstalige gebruiker.
Schrijf alle antwoorden in het Nederlands.
Geef korte, concrete en niet-diagnostische observaties.
Beoordeel alleen wat uit de tekst blijkt en verzin geen context of feiten.
Geef uitsluitend de gevraagde JSON terug."""


def rewrite_text(gateway, text: str, tone: str) -> TextRewriteResponse:
    result = gateway.generate_json(
        system_prompt=REWRITE_SYSTEM_PROMPT,
        user_prompt=f"Gewenste toon: {tone}\n\nTekst:\n{text}",
        response_model=TextRewriteResponse,
    )
    return result


def analyze_tone(gateway, text: str) -> ToneAnalysisResponse:
    return gateway.generate_json(
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
        user_prompt=f"Analyseer deze tekst:\n\n{text}",
        response_model=ToneAnalysisResponse,
    )
