"""Primary language of a drawing sheet, read from its extracted text.

The spelling check cannot judge whether a word belongs on the sheet until it
knows which language the sheet is written in — an English caption is correct on
an English drawing and a defect on a German one. Detection here is plain
deterministic Python so the answer is stable across runs; the model is only told
the result and left to find the offending text.

Scoring counts marker words that belong to one language and not to the others.
Spellings that carry no signal in this domain ("Detail", "Plan", "Beton",
"Position", "Total", "Index", "Projekt") are deliberately absent from every
lexicon. Extraction frequently loses umlauts and accents, so text and lexicons
are both folded to plain ASCII and the transliterated German spellings
("fuer", "geprueft") are listed next to the folded ones ("fur", "gepruft").
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

# Below this many marker hits the sheet carries too little prose to judge.
_MIN_HITS = 4

LANGUAGE_NAMES: dict[str, str] = {
    "de": "German",
    "en": "English",
    "fr": "French",
    "it": "Italian",
    "nl": "Dutch",
    "es": "Spanish",
}

_LEXICONS: dict[str, frozenset[str]] = {
    "de": frozenset("""
        und der die das den dem des ein eine einer eines fur fuer mit von vom
        nach bei ist sind nicht oben unten links rechts vorne hinten oder alle
        siehe gemass gemaess sowie jeweils wird werden durch auch ohne beim zum
        schnitt ansicht wandansicht draufsicht bewehrung schalung stahl stabe
        staebe bauteil zeichnung massstab masstab gezeichnet gepruft geprueft
        blatt stuck stueck gewicht masse gesamtmasse lange laenge breite hohe
        hoehe anzahl bemerkung bemerkungen anderung aenderung freigabe seite
        aussparung abstand festigkeit wand wande waende platte stutze stuetze
        trager traeger balken decke liste stabliste mattenstahlliste
        einbauteilliste montageteilliste betondeckung expositionsklasse
        lastausgleich achse oberkante unterkante einbau teil teile ausfuhrung
        ausfuehrung prufung pruefung planfreigabe werk halle nummer matte
        matten durchmesser verlegung angaben hinweis hinweise bewehrungsplan
        schneideskizze zulassig zulaessig erforderlich vorgefertigt fertigteil
    """.split()),
    "en": frozenset("""
        and the for with from this that are not all see shall must both each
        top bottom left right front back upper lower inner outer according
        section view elevation formwork reinforcement drawing scale drawn
        checked approved designed sheet weight length width height quantity
        remark remarks change release page opening spacing concrete strength
        wall walls slab column beam list bar bars mesh cover exposure axis
        edge note notes cutting sketch layout erection precast spacer embedded
        parts part assembly item grid level required allowed rebar
    """.split()),
    "fr": frozenset("""
        les des une pour avec dans sur sont pas tous voir selon coupe vue
        ferraillage coffrage dessin echelle dessine verifie feuille poids
        longueur largeur hauteur quantite remarque ouverture espacement mur
        murs dalle poteau poutre plancher acier armature niveau axe bord
        nombre piece prefabrique diametre enrobage epaisseur
    """.split()),
    "it": frozenset("""
        gli dei delle una per con nel sono non tutti vedi secondo sezione vista
        prospetto armatura cassero disegno scala disegnato verificato foglio
        peso lunghezza larghezza altezza quantita apertura passo muro solaio
        pilastro trave acciaio livello asse bordo pezzo prefabbricato
        copriferro spessore
    """.split()),
    "nl": frozenset("""
        het een voor met van niet alle zie volgens doorsnede aanzicht
        bovenaanzicht wapening bekisting tekening schaal getekend gecontroleerd
        blad lengte breedte hoogte aantal opmerking wijziging sparing plaat
        kolom vloer staal stuk prefab dekking dikte
    """.split()),
    "es": frozenset("""
        los las una para con son todos ver segun seccion alzado armado
        encofrado dibujo escala dibujado revisado hoja longitud ancho altura
        cantidad separacion losa pilar viga acero nivel eje borde pieza
        prefabricado recubrimiento espesor
    """.split()),
}

_TOKEN_RE = re.compile(r"[a-z]{2,}")


def fold(text: str) -> str:
    """Lowercase *text* and strip umlauts, accents and ß to plain ASCII letters."""
    text = text.replace("ß", "ss").replace("ẞ", "SS")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


class DrawingLanguage(NamedTuple):
    """Outcome of detection over one sheet's extracted text.

    ``code`` is "unknown" when the sheet holds too little prose to decide, in
    which case ``name`` is "unknown" and ``markers`` is empty.
    """

    code: str
    name: str
    confidence: float          # share of all marker hits won by `code`, 0.0–1.0
    scores: dict[str, int]     # marker hits per language code, descending
    markers: list[str]         # distinct marker words the winner was read from
    secondary: str | None      # runner-up code when it holds ≥15% of the hits


def detect_drawing_language(text: str) -> DrawingLanguage:
    """Primary language of the sheet whose extracted text is *text*.

    Pass the raw page text, never the formatted LLM prompt — the formatter's own
    English section headers would count toward English.
    """
    tokens = _TOKEN_RE.findall(fold(text or ""))
    if not tokens:
        return DrawingLanguage("unknown", "unknown", 0.0, {}, [], None)

    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for code, lexicon in _LEXICONS.items():
        matched = [t for t in tokens if t in lexicon]
        if matched:
            scores[code] = len(matched)
            hits[code] = matched

    total = sum(scores.values())
    if total < _MIN_HITS:
        return DrawingLanguage("unknown", "unknown", 0.0, dict(sorted(
            scores.items(), key=lambda kv: -kv[1])), [], None)

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    code, best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    secondary = runner_up[0] if runner_up and runner_up[1] >= 0.15 * total else None

    # Distinct words, most frequent first — this is the evidence shown in logs.
    counts: dict[str, int] = {}
    for word in hits[code]:
        counts[word] = counts.get(word, 0) + 1
    markers = sorted(counts, key=lambda w: (-counts[w], w))

    return DrawingLanguage(
        code=code,
        name=LANGUAGE_NAMES[code],
        confidence=round(best / total, 2),
        scores=dict(ranked),
        markers=markers,
        secondary=secondary,
    )


def language_name(code: str | None) -> str:
    """Display name for a language *code*, or "unknown" for an unmapped one."""
    return LANGUAGE_NAMES.get(code or "", "unknown")
