import hashlib
import json
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from textwrap import dedent

import streamlit as st
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

MODEL = "gpt-4.1-mini"
USERS_PATH = Path("users.json")
USER_DATA_DIR = Path("user_data")
STYLE_PRESETS = {
    "Modern": {"accent": "#1d4ed8"},
    "Klassiek": {"accent": "#7c2d12"},
    "Minimal": {"accent": "#111827"},
    "Donker": {"accent": "#38bdf8"},
    "Ambacht": {"accent": "#166534"},
}
SNEL_TEMPLATES = {
    "Leeg starten": {
        "klus_type": "",
        "beschrijving": "",
        "stijl": None,
    },
    "Diensten algemeen": {
        "klus_type": "Dienstverlening",
        "beschrijving": "Uitvoering van de afgesproken werkzaamheden conform planning en met zorg voor een nette oplevering.",
        "stijl": "Modern",
    },
    "Onderhoud en reparatie": {
        "klus_type": "Onderhoud en reparatie",
        "beschrijving": "Uitvoeren van de afgesproken onderhouds- en herstelwerkzaamheden inclusief controle en nette oplevering.",
        "stijl": "Ambacht",
    },
    "Advies en consultancy": {
        "klus_type": "Advieswerkzaamheden",
        "beschrijving": "Levering van advies en begeleiding op basis van de afgesproken scope, planning en gewenste resultaten.",
        "stijl": "Minimal",
    },
    "Creatief en media": {
        "klus_type": "Creatieve werkzaamheden",
        "beschrijving": "Uitwerken en opleveren van de afgesproken creatieve werkzaamheden volgens briefing en planning.",
        "stijl": "Klassiek",
    },
    "Schoonmaak en facilitair": {
        "klus_type": "Schoonmaakwerkzaamheden",
        "beschrijving": "Uitvoeren van de afgesproken schoonmaak- of facilitaire werkzaamheden volgens planning en kwaliteitseisen.",
        "stijl": "Minimal",
    },
    "Techniek en installatie": {
        "klus_type": "Technische werkzaamheden",
        "beschrijving": "Uitvoeren van de afgesproken technische of installatiewerkzaamheden inclusief controle en oplevering.",
        "stijl": "Donker",
    },
    "Bouw en afwerking": {
        "klus_type": "Bouw- en afbouwwerkzaamheden",
        "beschrijving": "Uitvoeren van de afgesproken bouw-, afbouw- of afwerkingswerkzaamheden volgens planning en afspraak.",
        "stijl": "Ambacht",
    },
}
USER_DATA_DIR.mkdir(exist_ok=True)


def get_style_config(style_name: str, accent_override: str | None = None) -> dict:
    basis = STYLE_PRESETS.get(style_name, STYLE_PRESETS["Modern"]).copy()
    if accent_override:
        basis["accent"] = accent_override
    return basis


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def load_users() -> dict:
    if not USERS_PATH.exists():
        return {}
    try:
        return json.loads(USERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(users: dict) -> None:
    USERS_PATH.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def make_user_key(email: str) -> str:
    return email.strip().lower().replace("@", "_at_").replace(".", "_")


def get_user_config_path(email: str) -> Path:
    return USER_DATA_DIR / f"{make_user_key(email)}_config.json"


def get_user_customers_path(email: str) -> Path:
    return USER_DATA_DIR / f"{make_user_key(email)}_customers.json"


def load_json_file(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def save_json_file(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_customers(email: str) -> list[dict]:
    data = load_json_file(get_user_customers_path(email), [])
    if isinstance(data, list):
        return data
    return []


def save_customers(email: str, customers: list[dict]) -> None:
    save_json_file(get_user_customers_path(email), customers)


def find_customer(customers: list[dict], naam: str) -> dict | None:
    for klant in customers:
        if klant.get("naam", "").strip().lower() == naam.strip().lower():
            return klant
    return None


def upsert_customer(email: str, naam: str, gegevens: str) -> None:
    naam = naam.strip()
    gegevens = gegevens.strip()
    if not naam:
        return
    customers = load_customers(email)
    bestaand = find_customer(customers, naam)
    if bestaand:
        bestaand["gegevens"] = gegevens
    else:
        customers.append({"naam": naam, "gegevens": gegevens})
    customers = sorted(customers, key=lambda x: x.get("naam", "").lower())
    save_customers(email, customers)


def load_config(email: str) -> dict:
    standaard = {
        "bedrijfsnaam": "",
        "bedrijfsgegevens": "",
        "kvk_nummer": "",
        "btw_id": "",
        "accentkleur": "#1d4ed8",
        "offerte_stijl": "Modern",
        "standaard_geldigheid": 14,
        "standaard_betaaltermijn": 14,
    }
    pad = get_user_config_path(email)
    if not pad.exists():
        return standaard
    try:
        data = json.loads(pad.read_text(encoding="utf-8"))
        standaard.update(data)
        return standaard
    except Exception:
        return standaard


def save_config(email: str, config: dict) -> None:
    pad = get_user_config_path(email)
    pad.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_admin_account() -> None:
    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    if not admin_email or not admin_password:
        return
    users = load_users()
    if admin_email not in users:
        users[admin_email] = {"password_hash": hash_password(admin_password), "role": "admin"}
        save_users(users)


def auth_screen() -> bool:
    ensure_admin_account()
    if st.session_state.get("logged_in") and st.session_state.get("user_email"):
        return True

    st.title("🔐 Inloggen")
    tab_login, tab_register = st.tabs(["Inloggen", "Account maken"])

    with tab_login:
        email = st.text_input("E-mail", key="login_email")
        password = st.text_input("Wachtwoord", type="password", key="login_password")
        if st.button("Inloggen", key="login_btn", use_container_width=True):
            users = load_users()
            record = users.get(email.strip().lower())
            if record and record.get("password_hash") == hash_password(password):
                st.session_state["logged_in"] = True
                st.session_state["user_email"] = email.strip().lower()
                st.session_state["user_role"] = record.get("role", "user")
                st.rerun()
            else:
                st.error("Onjuiste inloggegevens.")

    with tab_register:
        reg_email = st.text_input("E-mail", key="reg_email")
        reg_password = st.text_input("Wachtwoord", type="password", key="reg_password")
        reg_password_2 = st.text_input("Herhaal wachtwoord", type="password", key="reg_password_2")
        if st.button("Account aanmaken", key="register_btn", use_container_width=True):
            email = reg_email.strip().lower()
            users = load_users()
            if not email or "@" not in email:
                st.error("Vul een geldig e-mailadres in.")
            elif len(reg_password) < 6:
                st.error("Wachtwoord moet minstens 6 tekens hebben.")
            elif reg_password != reg_password_2:
                st.error("Wachtwoorden komen niet overeen.")
            elif email in users:
                st.error("Dit account bestaat al.")
            else:
                users[email] = {"password_hash": hash_password(reg_password), "role": "user"}
                save_users(users)
                save_config(email, load_config(email))
                save_customers(email, [])
                st.success("Account aangemaakt. Log nu in.")

    return False


def euro_bedrag(waarde: str | float) -> str:
    bedrag = float(str(waarde).replace(",", ".").strip())
    return f"EUR {bedrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_bedrag(waarde: str | float) -> float:
    return float(str(waarde).replace(",", ".").strip())


def bereken_prijzen(subtotaal_input: str, btw_percentage: str) -> dict:
    subtotaal = parse_bedrag(subtotaal_input)
    btw = parse_bedrag(btw_percentage)
    btw_bedrag = subtotaal * (btw / 100)
    totaal = subtotaal + btw_bedrag
    return {
        "subtotaal": subtotaal,
        "btw_percentage": btw,
        "btw_bedrag": btw_bedrag,
        "totaal": totaal,
        "subtotaal_format": euro_bedrag(subtotaal),
        "btw_bedrag_format": euro_bedrag(btw_bedrag),
        "totaal_format": euro_bedrag(totaal),
    }


def professionele_intro(stijl: str) -> str:
    intros = {
        "Modern": "Bedankt voor uw aanvraag. Hieronder vindt u onze duidelijke en professionele offerte.",
        "Klassiek": "Naar aanleiding van uw aanvraag doen wij u hierbij graag de volgende offerte toekomen.",
        "Minimal": "Hierbij ontvangt u onze offerte voor de gevraagde werkzaamheden.",
        "Donker": "Dank voor uw aanvraag. Hieronder staat onze offerte overzichtelijk samengevat.",
        "Ambacht": "Bedankt voor uw aanvraag. Met plezier sturen wij u onze offerte voor deze werkzaamheden.",
    }
    return intros.get(stijl, intros["Modern"])


def professionele_afsluiting(bedrijfsnaam: str) -> str:
    return dedent(
        f"""
        Wij vertrouwen erop u hiermee een passende aanbieding te hebben gedaan.
        Bij akkoord ontvangen wij graag uw bevestiging. Voor vragen kunt u altijd contact met ons opnemen.

        Met vriendelijke groet,
        {bedrijfsnaam}
        """
    ).strip()


def valideer(data: dict) -> list[str]:
    fouten = []
    verplichte_velden = ["bedrijfsnaam", "bedrijfsgegevens", "kvk_nummer", "klantnaam", "klus_type", "beschrijving", "prijs"]
    for veld in verplichte_velden:
        if not str(data.get(veld, "")).strip():
            fouten.append(f"{veld.replace('_', ' ').capitalize()} is verplicht.")
    try:
        if parse_bedrag(data["prijs"]) < 0:
            fouten.append("Subtotaal moet 0 of hoger zijn.")
    except Exception:
        fouten.append("Subtotaal moet een geldig getal zijn, bijvoorbeeld 1250 of 1250,50.")
    try:
        if parse_bedrag(data.get("btw_percentage", "21")) < 0:
            fouten.append("BTW-percentage moet 0 of hoger zijn.")
    except Exception:
        fouten.append("BTW-percentage moet een geldig getal zijn, bijvoorbeeld 21 of 9.")
    if data.get("kvk_nummer") and not str(data["kvk_nummer"]).replace(" ", "").isdigit():
        fouten.append("KvK-nummer moet uit cijfers bestaan.")
    return fouten


def maak_prompt(data: dict) -> str:
    return dedent(
        f"""
        Je bent een professionele Nederlandse offerte-schrijver.
        Schrijf een nette, duidelijke en klantvriendelijke offerte in correct Nederlands.
        De stijl van de offerte is: {data['offerte_stijl']}.

        Gebruik deze gegevens:
        - Bedrijfsnaam: {data['bedrijfsnaam']}
        - Bedrijfsgegevens: {data['bedrijfsgegevens']}
        - KvK-nummer: {data['kvk_nummer']}
        - Btw-id: {data['btw_id']}
        - Klantnaam: {data['klantnaam']}
        - Klantgegevens: {data['klantgegevens']}
        - Datum: {data['datum']}
        - Offertenummer: {data['offertenummer']}
        - Type klus: {data['klus_type']}
        - Beschrijving werkzaamheden: {data['beschrijving']}
        - Subtotaal: {data['subtotaal_format']}
        - BTW-percentage: {data['btw_percentage']}%
        - BTW-bedrag: {data['btw_bedrag_format']}
        - Totaal inclusief btw: {data['totaal_format']}
        - Geldigheid: {data['geldigheid']} dagen
        - Betaaltermijn: {data['betaaltermijn']} dagen

        Structuur:
        1. Titel OFFERTE
        2. Zakelijke inleiding
        3. Werkzaamheden
        4. Prijsopgave
        5. Geldigheid en betaaltermijn
        6. Professionele afsluiting

        Houd het compact, zakelijk en direct bruikbaar voor een klant.
        Gebruik platte tekst zonder markdown.
        """
    ).strip()


def fallback_offerte(data: dict) -> str:
    klantblok = data["klantgegevens"].strip()
    if klantblok:
        klantblok = f"{data['klantnaam']}\n{klantblok}"
    else:
        klantblok = data["klantnaam"]
    btw_regel = f"Btw-id: {data['btw_id']}" if data["btw_id"].strip() else ""
    intro = professionele_intro(data["offerte_stijl"])
    afsluiting = professionele_afsluiting(data["bedrijfsnaam"])
    return dedent(
        f"""
        OFFERTE

        Offertenummer: {data['offertenummer']}
        Datum: {data['datum']}

        VAN
        {data['bedrijfsnaam']}
        {data['bedrijfsgegevens']}
        KvK: {data['kvk_nummer']}
        {btw_regel}

        VOOR
        {klantblok}

        Geachte {data['klantnaam']},

        {intro}

        WERKZAAMHEDEN
        {data['beschrijving']}

        TYPE KLUS
        {data['klus_type']}

        PRIJSOPGAVE
        Subtotaal: {data['subtotaal_format']}
        BTW ({data['btw_percentage']}%): {data['btw_bedrag_format']}
        Totaal inclusief btw: {data['totaal_format']}

        GELDIGHEID EN BETAALTERMIJN
        Deze offerte is geldig gedurende {data['geldigheid']} dagen na offertedatum.
        Betaaltermijn: {data['betaaltermijn']} dagen.

        {afsluiting}
        """
    ).strip()


def genereer_offerte(data: dict) -> str:
    if not OPENAI_AVAILABLE or not os.getenv("OPENAI_API_KEY"):
        return fallback_offerte(data)
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.responses.create(model=MODEL, input=maak_prompt(data))
        tekst = response.output_text.strip()
        return tekst or fallback_offerte(data)
    except Exception:
        return fallback_offerte(data)


def maak_pdf(bestandsnaam: str, data: dict, offerte_tekst: str, logo_bytes: bytes | None = None) -> None:
    stijl = get_style_config(data["offerte_stijl"], data["accentkleur"])
    doc = SimpleDocTemplate(bestandsnaam, pagesize=A4, rightMargin=34, leftMargin=34, topMargin=34, bottomMargin=34)
    styles = getSampleStyleSheet()
    titel = ParagraphStyle("Titel", parent=styles["Heading1"], fontSize=18, leading=20, textColor=colors.HexColor(stijl["accent"]), spaceAfter=8)
    subtitel = ParagraphStyle("Subtitel", parent=styles["BodyText"], fontSize=9, leading=11, textColor=colors.grey, spaceAfter=8)
    kop = ParagraphStyle("Kop", parent=styles["Heading2"], fontSize=10, leading=12, textColor=colors.HexColor(stijl["accent"]), spaceBefore=6, spaceAfter=4)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9, leading=11, alignment=TA_LEFT)
    rechts = ParagraphStyle("Rechts", parent=body, alignment=TA_RIGHT)

    story = []
    if logo_bytes:
        try:
            logo = Image(BytesIO(logo_bytes), width=90, height=45)
            story.append(logo)
            story.append(Spacer(1, 4))
        except Exception:
            pass

    story.append(Paragraph("OFFERTE", titel))
    story.append(Paragraph(f"Offertenummer: {data['offertenummer']} | Datum: {data['datum']}", subtitel))

    klant_html = data["klantnaam"]
    if data["klantgegevens"].strip():
        klant_html += "<br/>" + data["klantgegevens"].replace("\n", "<br/>")
    bedrijfsblok = f"<b>{data['bedrijfsnaam']}</b><br/>{data['bedrijfsgegevens'].replace(chr(10), '<br/>')}<br/>KvK: {data['kvk_nummer']}"
    if data["btw_id"].strip():
        bedrijfsblok += f"<br/>Btw-id: {data['btw_id']}"

    header_table = Table([[Paragraph(bedrijfsblok, body), Paragraph(f"<b>Klant</b><br/>{klant_html}", rechts)]], colWidths=[300, 190])
    header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(header_table)
    story.append(Spacer(1, 6))

    story.append(Paragraph("Werkzaamheden", kop))
    story.append(Paragraph(data["beschrijving"].strip().replace("\n", "<br/>"), body))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Prijsopgave", kop))
    prijs_table = Table(
        [["Omschrijving", "Bedrag"], ["Subtotaal", data["subtotaal_format"]], [f"BTW ({data['btw_percentage']}%)", data["btw_bedrag_format"]], ["Totaal incl. btw", data["totaal_format"]]],
        colWidths=[360, 120],
    )
    prijs_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(stijl["accent"])),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 1), (-1, -2), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dbeafe")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(prijs_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Voorwaarden", kop))
    story.append(Paragraph(f"Geldig gedurende {data['geldigheid']} dagen na offertedatum. Betaaltermijn: {data['betaaltermijn']} dagen.", body))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Afsluiting", kop))
    story.append(Paragraph("Bij akkoord ontvangen wij graag uw bevestiging. Voor vragen kunt u contact opnemen.", body))
    doc.build(story)


def test_hash_password() -> None:
    assert hash_password("test123") == hash_password("test123")


def test_euro_bedrag() -> None:
    assert euro_bedrag("1250") == "EUR 1.250,00"
    assert euro_bedrag("1250,5") == "EUR 1.250,50"


def test_bereken_prijzen() -> None:
    prijzen = bereken_prijzen("100", "21")
    assert prijzen["subtotaal"] == 100.0
    assert round(prijzen["btw_bedrag"], 2) == 21.0
    assert round(prijzen["totaal"], 2) == 121.0


def test_style_config() -> None:
    stijl = get_style_config("Klassiek")
    assert stijl["accent"] == "#7c2d12"


def test_customer_store() -> None:
    email = "test@example.com"
    upsert_customer(email, "Jan Jansen", "Straat 1")
    klanten = load_customers(email)
    assert any(k["naam"] == "Jan Jansen" for k in klanten)


def test_valideer() -> None:
    data = {"bedrijfsnaam": "Test", "bedrijfsgegevens": "Straat 1", "kvk_nummer": "12345678", "klantnaam": "Jan", "klus_type": "Schilderwerk", "beschrijving": "Muren schilderen", "prijs": "1000", "btw_percentage": "21"}
    assert valideer(data) == []
    data["prijs"] = "abc"
    assert len(valideer(data)) >= 1


def run_tests() -> None:
    test_hash_password()
    test_euro_bedrag()
    test_bereken_prijzen()
    test_style_config()
    test_customer_store()
    test_valideer()


run_tests()

st.set_page_config(page_title="AI Offerte Generator Pro", page_icon="📄", layout="wide")
if not auth_screen():
    st.stop()

user_email = st.session_state["user_email"]
config = load_config(user_email)
klanten = load_customers(user_email)
klant_namen = [k["naam"] for k in klanten]

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    .stDownloadButton button, .stButton button {border-radius: 12px; font-weight: 600;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📄 Offerte Generator v11")
st.write(f"Ingelogd als: {user_email}")
st.write("Sneller werken met brede templates, opgeslagen klanten en professionelere offertetekst voor veel verschillende soorten bedrijven.")

with st.sidebar:
    st.subheader("Snel starten")
    template_keuze = st.selectbox("Kies een template", list(SNEL_TEMPLATES.keys()))
    st.subheader("Stijl")
    stijl_keys = list(STYLE_PRESETS.keys())
    opgeslagen_stijl = config.get("offerte_stijl", "Modern")
    voorgestelde_stijl = SNEL_TEMPLATES.get(template_keuze, {}).get("stijl") or opgeslagen_stijl
    default_index = stijl_keys.index(voorgestelde_stijl) if voorgestelde_stijl in stijl_keys else 0
    offerte_stijl = st.selectbox("Kies offerte stijl", stijl_keys, index=default_index)
    standaard_accent = get_style_config(offerte_stijl)["accent"]
    accentkleur = st.color_picker("Accentkleur", config.get("accentkleur", standaard_accent))
    st.subheader("Branding")
    logo_bestand = st.file_uploader("Upload logo (png/jpg)", type=["png", "jpg", "jpeg"])
    st.subheader("Account")
    save_profile = st.button("💾 Sla bedrijfsprofiel op", use_container_width=True)
    if st.button("Uitloggen", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.subheader("AI status")
    if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
        st.success("OpenAI actief")
    elif OPENAI_AVAILABLE:
        st.warning("OpenAI package gevonden, maar geen API key. Standaardtekst wordt gebruikt.")
    else:
        st.warning("OpenAI package niet gevonden. Standaardtekst wordt gebruikt.")

voorgeselecteerde_klus = SNEL_TEMPLATES.get(template_keuze, {}).get("klus_type", "")
voorgeselecteerde_beschrijving = SNEL_TEMPLATES.get(template_keuze, {}).get("beschrijving", "")
gekozen_klant = st.selectbox("Kies opgeslagen klant (optioneel)", ["Nieuwe klant"] + klant_namen)
klant_defaults = find_customer(klanten, gekozen_klant) if gekozen_klant != "Nieuwe klant" else None

with st.form("offerte_form"):
    st.subheader("Bedrijfsgegevens")
    bedrijfsnaam = st.text_input("Bedrijfsnaam", value=config.get("bedrijfsnaam", ""), placeholder="Bijv. Fokke Schilderwerken")
    bedrijfsgegevens = st.text_area("Adres / contactgegevens", value=config.get("bedrijfsgegevens", ""), placeholder="Dorpsstraat 10\n1234 AB Amsterdam\n06-12345678\ninfo@bedrijf.nl", height=120)
    c_bedrijf_1, c_bedrijf_2 = st.columns(2)
    with c_bedrijf_1:
        kvk_nummer = st.text_input("KvK-nummer", value=config.get("kvk_nummer", ""), placeholder="Bijv. 12345678")
    with c_bedrijf_2:
        btw_id = st.text_input("Btw-id", value=config.get("btw_id", ""), placeholder="Bijv. NL001234567B01")

    st.subheader("Klant")
    klantnaam = st.text_input("Klantnaam", value=klant_defaults.get("naam", "") if klant_defaults else "", placeholder="Bijv. Jan Jansen")
    klantgegevens = st.text_area("Klantgegevens (optioneel)", value=klant_defaults.get("gegevens", "") if klant_defaults else "", placeholder="Straatnaam 5\n1234 AB Utrecht", height=90)
    klant_opslaan = st.checkbox("Sla deze klant op voor later", value=bool(klant_defaults))

    st.subheader("Klus")
    klus_type = st.text_input("Type klus", value=voorgeselecteerde_klus, placeholder="Bijv. Buiten schilderwerk")
    beschrijving = st.text_area("Beschrijving werkzaamheden", value=voorgeselecteerde_beschrijving, placeholder="Bijv. Schuren, gronden en aflakken van kozijnen en voordeur.", height=120)

    c1, c2, c3 = st.columns(3)
    with c1:
        prijs = st.text_input("Subtotaal in euro", placeholder="Bijv. 1250 of 1250,50")
    with c2:
        geldigheid = st.number_input("Geldigheid in dagen", min_value=1, value=int(config.get("standaard_geldigheid", 14)), step=1)
    with c3:
        betaaltermijn = st.number_input("Betaaltermijn in dagen", min_value=1, value=int(config.get("standaard_betaaltermijn", 14)), step=1)

    btw_percentage = st.selectbox("BTW-percentage", ["21", "9", "0"], index=0)

    submitted = st.form_submit_button("✨ Genereer professionele offerte", use_container_width=True)

if save_profile:
    save_config(user_email, {
        "bedrijfsnaam": config.get("bedrijfsnaam", ""),
        "bedrijfsgegevens": config.get("bedrijfsgegevens", ""),
        "kvk_nummer": config.get("kvk_nummer", ""),
        "btw_id": config.get("btw_id", ""),
        "accentkleur": accentkleur,
        "offerte_stijl": offerte_stijl,
        "standaard_geldigheid": int(config.get("standaard_geldigheid", 14)),
        "standaard_betaaltermijn": int(config.get("standaard_betaaltermijn", 14)),
    })
    st.sidebar.success("Bedrijfsprofiel opgeslagen voor jouw account.")

if submitted:
    datum = datetime.now().strftime("%d-%m-%Y")
    offertenummer = f"OFF-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    prijs_info = bereken_prijzen(prijs, btw_percentage) if prijs else {}
    data = {
        "bedrijfsnaam": bedrijfsnaam,
        "bedrijfsgegevens": bedrijfsgegevens,
        "kvk_nummer": kvk_nummer,
        "btw_id": btw_id,
        "klantnaam": klantnaam,
        "klantgegevens": klantgegevens,
        "klus_type": klus_type,
        "beschrijving": beschrijving,
        "prijs": prijs,
        "btw_percentage": btw_percentage,
        "subtotaal_format": prijs_info.get("subtotaal_format", ""),
        "btw_bedrag_format": prijs_info.get("btw_bedrag_format", ""),
        "totaal_format": prijs_info.get("totaal_format", ""),
        "geldigheid": str(geldigheid),
        "betaaltermijn": str(betaaltermijn),
        "datum": datum,
        "offertenummer": offertenummer,
        "accentkleur": accentkleur,
        "offerte_stijl": offerte_stijl,
    }

    fouten = valideer(data)
    if fouten:
        for fout in fouten:
            st.error(fout)
    else:
        if klant_opslaan:
            upsert_customer(user_email, klantnaam, klantgegevens)
        save_config(user_email, {
            "bedrijfsnaam": bedrijfsnaam,
            "bedrijfsgegevens": bedrijfsgegevens,
            "kvk_nummer": kvk_nummer,
            "btw_id": btw_id,
            "accentkleur": accentkleur,
            "offerte_stijl": offerte_stijl,
            "standaard_geldigheid": int(geldigheid),
            "standaard_betaaltermijn": int(betaaltermijn),
        })

        offerte = genereer_offerte(data)
        txt_bestand = f"offerte_{klantnaam.strip().lower().replace(' ', '_') or 'klant'}.txt"
        pdf_bestand = txt_bestand.replace('.txt', '.pdf')
        logo_bytes = logo_bestand.getvalue() if logo_bestand else None

        with open(txt_bestand, "w", encoding="utf-8") as f:
            f.write(offerte)
        maak_pdf(pdf_bestand, data, offerte, logo_bytes=logo_bytes)

        st.success("Offerte gegenereerd en klaar om te downloaden.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Stijl", offerte_stijl)
        c2.metric("Subtotaal", data["subtotaal_format"])
        c3.metric("BTW", f"{btw_percentage}%")
        c4.metric("Totaal", data["totaal_format"])
        st.download_button("⬇️ Download als TXT", data=offerte, file_name=txt_bestand, mime="text/plain", use_container_width=True)
        with open(pdf_bestand, "rb") as f:
            st.download_button("⬇️ Download als PDF", data=f.read(), file_name=pdf_bestand, mime="application/pdf", use_container_width=True)
        with st.expander("Toon offerte tekst"):
            st.text_area("Offerte tekst", offerte, height=240)
