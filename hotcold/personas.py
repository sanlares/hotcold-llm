"""One Persona per real second mover, built from that person's recorded demographics.

Final design: the *demographic* Persona (render_demographic) -- only what the experiment recorded about the
person: age, gender, education level, being a student in the UK (Prolific screen used by the paper). Nothing is
invented. The Nemotron Persona of the final design is built in sources.py on top of the same real data.

Pilots only: the *basic* Persona (render_backstory) completed those real data with invented, outcome-neutral facts
(name, origin, university city, field of study, living situation, family, a close friend, hobbies, part-time job),
drawn with a seed derived from the participant's id. Nothing invented touched what the experiment measures (no
personality, values, attitudes to money, trust, fairness or reciprocity, religion or politics).

The participant's own answers (choices, reciprocity items, comments) are never used to build any Persona.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from .materials import PACKAGE

DATASET = PACKAGE / "data/hotcold_dataset.csv"
RAW = {"baseline": PACKAGE / "data/HotCold-baseline-SM.xlsx"}
DATASET_LABEL = {"baseline": "Baseline experiment"}

PERSONA_VERSION = "v2"  # v2: education and gender stated literally

# --- pools ------------------------------------------------------------------------------------------
# Origin of UK students: roughly 3/4 UK-domiciled, 1/4 international (HESA orders of magnitude).
ORIGINS = {
    "England": 60, "Scotland": 6, "Wales": 4, "Northern Ireland": 3,
    "China": 7, "India": 5, "Nigeria": 2, "Pakistan": 1.5, "United States": 1.5, "Hong Kong": 1,
    "Malaysia": 1, "Ireland": 1, "Italy": 1.5, "Spain": 1, "France": 1, "Germany": 1, "Romania": 1,
    "Greece": 0.75, "Poland": 0.75, "Portugal": 0.5,
}
UK = {"England", "Scotland", "Wales", "Northern Ireland"}
NATIONALITY = {
    "England": "British", "Scotland": "British", "Wales": "British", "Northern Ireland": "British",
    "China": "Chinese", "India": "Indian", "Nigeria": "Nigerian", "Pakistan": "Pakistani",
    "United States": "American", "Hong Kong": "Hong Konger", "Malaysia": "Malaysian", "Ireland": "Irish",
    "Italy": "Italian", "Spain": "Spanish", "France": "French", "Germany": "German", "Romania": "Romanian",
    "Greece": "Greek", "Poland": "Polish", "Portugal": "Portuguese",
}
HOMETOWNS = {
    "England": ["Leeds", "Bristol", "Norwich", "Leicester", "Sheffield", "Reading", "Plymouth", "Coventry",
                "Derby", "Luton", "Stoke-on-Trent", "Southampton", "York", "Bolton", "Ipswich", "Croydon",
                "Milton Keynes", "Exeter", "Hull", "Wolverhampton", "Sunderland", "Brighton", "Peterborough",
                "Chelmsford", "Blackpool", "Lincoln", "Swindon", "Walsall", "Bournemouth", "Northampton"],
    "Scotland": ["Glasgow", "Aberdeen", "Dundee", "Inverness", "Paisley", "Stirling", "Perth"],
    "Wales": ["Cardiff", "Swansea", "Newport", "Wrexham", "Bangor"],
    "Northern Ireland": ["Belfast", "Derry", "Newry", "Lisburn"],
    "China": ["Shanghai", "Chengdu", "Wuhan", "Hangzhou", "Guangzhou", "Nanjing", "Xi'an", "Shenzhen"],
    "India": ["Mumbai", "Pune", "Chennai", "Hyderabad", "Kolkata", "Delhi", "Bengaluru", "Kochi"],
    "Nigeria": ["Lagos", "Abuja", "Ibadan", "Port Harcourt", "Enugu"],
    "Pakistan": ["Lahore", "Karachi", "Islamabad", "Faisalabad"],
    "United States": ["Columbus", "Denver", "Atlanta", "Portland", "Austin", "Pittsburgh"],
    "Hong Kong": ["Hong Kong"],
    "Malaysia": ["Kuala Lumpur", "Penang", "Johor Bahru"],
    "Ireland": ["Dublin", "Cork", "Galway", "Limerick"],
    "Italy": ["Bologna", "Turin", "Naples", "Verona", "Bari"],
    "Spain": ["Valencia", "Seville", "Zaragoza", "Bilbao", "Murcia"],
    "France": ["Lyon", "Lille", "Nantes", "Toulouse", "Rennes"],
    "Germany": ["Cologne", "Leipzig", "Hamburg", "Stuttgart", "Bremen"],
    "Romania": ["Cluj-Napoca", "Iasi", "Timisoara", "Bucharest"],
    "Greece": ["Thessaloniki", "Patras", "Athens", "Heraklion"],
    "Poland": ["Krakow", "Wroclaw", "Gdansk", "Poznan"],
    "Portugal": ["Porto", "Braga", "Coimbra", "Lisbon"],
}
NAME_REGION = {
    "England": "uk", "Scotland": "uk", "Wales": "uk", "Northern Ireland": "uk", "Ireland": "uk",
    "United States": "us", "China": "cn", "Hong Kong": "hk", "Malaysia": "my", "India": "in",
    "Pakistan": "pk", "Nigeria": "ng", "Italy": "it", "Spain": "es", "France": "fr", "Germany": "de",
    "Romania": "ro", "Greece": "gr", "Poland": "pl", "Portugal": "pt",
}
FIRST = {  # (female, male, neutral)
    "uk": (["Olivia", "Amelia", "Isla", "Grace", "Freya", "Lily", "Chloe", "Megan", "Holly", "Ellie", "Sophie",
            "Hannah", "Zara", "Aisha", "Niamh", "Rhiannon", "Eilidh", "Jessica", "Lauren", "Rebecca"],
           ["Oliver", "Harry", "Jack", "George", "Thomas", "James", "Callum", "Ryan", "Liam", "Ethan", "Joshua",
            "Samuel", "Daniel", "Rhys", "Euan", "Kieran", "Adam", "Mohammed", "Tom", "Lewis"],
           ["Alex", "Charlie", "Sam", "Jordan", "Robin", "Jamie", "Morgan", "Rowan", "Frankie", "Ashley"]),
    "us": (["Emily", "Madison", "Hailey", "Abigail"], ["Tyler", "Brandon", "Austin", "Logan"], ["Riley", "Taylor"]),
    "cn": (["Xinyi", "Yuting", "Jiayi", "Mengqi", "Siyu"], ["Haoran", "Zihao", "Yuxuan", "Junjie", "Tianyu"],
           ["Yu", "Xin"]),
    "hk": (["Hoi Yan", "Wing Sze"], ["Ka Ho", "Chun Kit"], ["Tsz Ching"]),
    "my": (["Nurul", "Mei Ling", "Priya"], ["Afiq", "Wei Jie", "Arjun"], ["Jia"]),
    "in": (["Ananya", "Priya", "Sneha", "Diya", "Kavya"], ["Arjun", "Rohan", "Aditya", "Karthik", "Vivek"],
           ["Kiran", "Ashwin"]),
    "pk": (["Ayesha", "Fatima", "Hira"], ["Hamza", "Usman", "Bilal"], ["Noor"]),
    "ng": (["Chiamaka", "Temitope", "Adaeze", "Funmilayo"], ["Chinedu", "Oluwaseun", "Emeka", "Tunde"],
           ["Ayo", "Tobi"]),
    "it": (["Giulia", "Chiara", "Francesca"], ["Matteo", "Lorenzo", "Davide"], ["Andrea"]),
    "es": (["Lucia", "Paula", "Marta"], ["Javier", "Pablo", "Alejandro"], ["Ariel"]),
    "fr": (["Camille", "Léa", "Manon"], ["Lucas", "Hugo", "Théo"], ["Camille"]),
    "de": (["Lena", "Hannah", "Lea"], ["Lukas", "Jonas", "Felix"], ["Kim"]),
    "ro": (["Ioana", "Andreea", "Bianca"], ["Andrei", "Mihai", "Alexandru"], ["Alex"]),
    "gr": (["Eleni", "Maria", "Katerina"], ["Giorgos", "Nikos", "Dimitris"], ["Alex"]),
    "pl": (["Zuzanna", "Julia", "Natalia"], ["Jakub", "Kacper", "Mateusz"], ["Ola"]),
    "pt": (["Beatriz", "Inês", "Mariana"], ["João", "Tiago", "Rodrigo"], ["Alex"]),
}
SURNAMES = {
    "uk": ["Smith", "Jones", "Taylor", "Brown", "Wilson", "Evans", "Thomas", "Roberts", "Walker", "Wright",
           "Hughes", "Green", "Hall", "Wood", "Clarke", "Patel", "Khan", "Campbell", "Murphy", "Kelly",
           "Turner", "Edwards", "Baker", "Morris", "Price", "Ali", "Begum", "Okafor", "Davies", "Robinson"],
    "us": ["Miller", "Johnson", "Garcia", "Anderson", "Martinez"], "cn": ["Wang", "Li", "Zhang", "Liu", "Chen"],
    "hk": ["Chan", "Wong", "Cheung", "Lau"], "my": ["Tan", "Lim", "Abdullah", "Nair"],
    "in": ["Sharma", "Iyer", "Reddy", "Gupta", "Nair"], "pk": ["Ahmed", "Malik", "Raza", "Hussain"],
    "ng": ["Adeyemi", "Okeke", "Balogun", "Eze"], "it": ["Rossi", "Russo", "Ferrari", "Esposito"],
    "es": ["García", "Fernández", "López", "Martín"], "fr": ["Martin", "Bernard", "Petit", "Durand"],
    "de": ["Müller", "Schmidt", "Fischer", "Weber"], "ro": ["Popescu", "Ionescu", "Stan", "Dumitru"],
    "gr": ["Papadopoulos", "Georgiou", "Nikolaou"], "pl": ["Nowak", "Kowalski", "Wiśniewski"],
    "pt": ["Silva", "Santos", "Ferreira", "Costa"],
}
UNI_CITIES = ["London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Edinburgh", "Bristol", "Nottingham",
              "Sheffield", "Liverpool", "Newcastle", "Cardiff", "Leicester", "Coventry", "Southampton",
              "Exeter", "Bath", "York", "Lancaster", "Durham", "Brighton", "Aberdeen", "Belfast", "Norwich",
              "Reading", "Oxford", "Cambridge", "Hull", "Plymouth", "Loughborough"]
FIELDS = {  # rough shares of UK higher-education enrolments by subject area
    "Business and Management": 14, "Psychology": 6, "Nursing": 5, "Medicine": 3, "Biomedical Science": 3,
    "Biology": 4, "Law": 5, "Computer Science": 6, "Mechanical Engineering": 2, "Civil Engineering": 1.5,
    "Electrical Engineering": 1.5, "Economics": 3, "Accounting and Finance": 3, "Sociology": 2.5,
    "Politics and International Relations": 2.5, "English Literature": 2, "History": 2, "Education": 4,
    "Graphic Design": 2, "Fine Art": 1.5, "Music": 1.5, "Film and Media Studies": 2, "Mathematics": 2,
    "Physics": 1, "Chemistry": 1.5, "Pharmacy": 1.5, "Architecture": 1, "Geography": 1.5,
    "Sport and Exercise Science": 2, "Modern Languages": 1.5, "Criminology": 2, "Social Work": 1.5,
    "Marketing": 1.5, "Environmental Science": 1, "Philosophy": 1, "Midwifery": 0.5, "Physiotherapy": 1,
}
HOBBIES = ["going to the gym", "running", "cooking new recipes", "baking", "photography", "playing video games",
           "reading fantasy novels", "reading crime novels", "playing football", "playing netball", "swimming",
           "bouldering", "hiking", "cycling", "playing the guitar", "playing the piano", "singing in a choir",
           "drawing", "painting", "watching anime", "watching films", "following Formula 1", "yoga",
           "knitting", "gardening", "listening to podcasts", "board games", "dancing", "skateboarding",
           "learning Japanese", "making music on a laptop", "thrifting clothes", "going to gigs",
           "playing badminton", "doing crosswords", "writing short stories", "chess", "tennis"]
JOBS = ["works a few shifts a week in a supermarket", "works part-time as a barista",
        "works weekend shifts in a clothes shop", "works evenings in a pub", "does food-delivery shifts",
        "works part-time on a university reception desk", "works part-time in a warehouse",
        "works a few hours a week in the campus library", "works part-time in a cinema"]
FRIEND_MET = ["at school", "on your course", "in halls in your first year", "at a part-time job",
              "through a sports club", "through your flatmate", "at a summer job"]


@dataclass
class Persona:
    agent_id: str  # e.g. "baseline_313"
    real_id: str  # `id` in hotcold_dataset.csv, e.g. "hotcold-baseline-sm.xlsx_313"
    experiment: str
    # real (from the participant's record)
    age: int
    gender: str  # Female | Male | Other | I would rather not say
    education: str  # Qualtrics answer, verbatim
    # assignment of the real participant (the agent gets the same one)
    group: int
    treatment: str
    crate: str
    # invented
    name: str = ""
    origin: str = ""
    hometown: str = ""
    nationality: str = ""
    uni_city: str = ""
    field_of_study: str = ""
    study_line: str = ""
    living: str = ""
    siblings: int = 0
    relationship: str = ""
    children: int = 0
    friend: str = ""
    friend_met: str = ""
    hobbies: list[str] = field(default_factory=list)
    job: str = ""
    version: str = PERSONA_VERSION
    rich: str = ""  # optional first-person life account (--persona rich), see personas_rich.yaml
    override: str = ""  # full Persona text from an external source (sources.py); replaces the backstory
    source: str = "basic"  # demographic | nemotron (final design); basic | rich | prism | twin-* (pilots)
    source_ref: str = ""  # id in the external dataset (PRISM user_id, Nemotron uuid, Twin pid)
    seq_from: str = ""  # pilot agent whose treatment and IN/OUT sequence this agent uses
    # quality of the match with an external persona (Nemotron): |age difference|, same education, is a student
    match_age_diff: int | None = None
    match_education: bool | None = None
    match_student: bool | None = None

    def invented_key(self) -> tuple:
        return (self.name, self.hometown, self.field_of_study, self.uni_city, tuple(self.hobbies))

    def backstory(self) -> str:
        if self.override:
            return self.override
        if self.source == "demographic":
            return render_demographic(self)
        text = render_backstory(self)
        if self.rich:
            text += "\n\nIn a long interview about your life, this is how you described yourself, in your own words:\n\n" + self.rich.strip()
        return text


def load_participants(experiment: str = "baseline") -> pd.DataFrame:
    """Real second movers who finished the study, with their raw demographics and assigned sequence."""
    raw = pd.read_excel(RAW[experiment])
    raw["real_id"] = RAW[experiment].name.lower() + "_" + (raw.index + 1).astype(str)  # as in _create_HotCold_dataset.do
    ds = pd.read_csv(DATASET, usecols=["experiment", "id", "finished"])
    done = set(ds[(ds.experiment == DATASET_LABEL[experiment]) & (ds.finished == 1)].id)
    raw = raw[raw.real_id.isin(done)].copy()
    raw["agent_id"] = experiment + "_" + raw.real_id.str.rsplit("_", n=1).str[1]
    return raw


def build_personas(experiment: str = "baseline", seed: int = 0) -> list[Persona]:
    people = load_participants(experiment)
    personas, seen = [], set()
    for _, r in people.iterrows():
        attempt = 0
        while True:
            p = make_persona(r, experiment, seed, attempt)
            if p.invented_key() not in seen:
                break
            attempt += 1
        seen.add(p.invented_key())
        personas.append(p)
    return personas


def _rng(seed: int, real_id: str, attempt: int) -> random.Random:
    h = hashlib.sha256(f"v1:{seed}:{real_id}:{attempt}".encode()).hexdigest()  # salt fixed at v1: wording changes keep the same draws
    return random.Random(int(h[:16], 16))


def _pick(rng: random.Random, weights: dict):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def make_persona(r: pd.Series, experiment: str, seed: int = 0, attempt: int = 0) -> Persona:
    rng = _rng(seed, r.real_id, attempt)
    age, gender, edu = int(r.Age), str(r.Gender), str(r.Education)
    p = Persona(r.agent_id, r.real_id, experiment, age, gender, edu,
                int(r.Group), str(r.Treatment), str(r.CRate))

    origins = dict(ORIGINS)
    if age >= 30:  # mature students are mostly UK-domiciled
        origins = {k: (v * 3 if k in UK else v) for k, v in origins.items()}
    p.origin = _pick(rng, origins)
    p.nationality = NATIONALITY[p.origin]
    p.hometown = rng.choice(HOMETOWNS[p.origin])
    region = NAME_REGION[p.origin]
    female, male, neutral = FIRST[region]
    pool = female if gender == "Female" else male if gender == "Male" else neutral
    p.name = f"{rng.choice(pool)} {rng.choice(SURNAMES[region])}"
    p.uni_city = rng.choice([c for c in UNI_CITIES if c != p.hometown])
    p.field_of_study = _pick(rng, FIELDS)
    p.study_line = _study_line(rng, age, edu, p.field_of_study, p.uni_city)

    if age <= 20:
        living = {"in student halls": 5, "in a shared student house": 3, "with your parents": 2}
    elif age <= 25:
        living = {"in a shared house with other students": 6, "with your parents": 2, "with your partner": 1.5,
                  "in a small studio flat": 1}
    else:
        living = {"with your partner": 5, "in a shared flat": 2, "on your own in a small flat": 2,
                  "with your parents": 1}
    p.living = _pick(rng, living)

    p.siblings = _pick(rng, {0: 2, 1: 4, 2: 2.5, 3: 1})
    if "partner" in p.living:
        p.relationship = "in a relationship" if age < 28 or rng.random() < 0.5 else "married"
    else:
        p.relationship = _pick(rng, {"single": 6, "in a relationship": 3}) if age < 30 else \
            _pick(rng, {"single": 4, "in a relationship": 3, "married": 3})
    if age >= 28 and p.relationship == "married":
        p.children = _pick(rng, {0: 3, 1: 2, 2: 2})

    own = p.name.split()[0]
    p.friend = rng.choice([n for n in FIRST["uk"][0] + FIRST["uk"][1] + FIRST[region][0] + FIRST[region][1] if n != own])
    p.friend_met = rng.choice(FRIEND_MET)
    p.hobbies = rng.sample(HOBBIES, k=rng.choice([2, 2, 3]))
    p.job = rng.choice(JOBS) if rng.random() < 0.5 else ""
    return p


def _study_line(rng, age, edu, fld, city) -> str:
    if edu == "Bachelor student":
        year = 1 if age <= 18 else rng.choice([1, 2]) if age == 19 else rng.choice([2, 3]) if age <= 21 \
            else rng.choice([1, 2, 3, 4])
        ordinal = {1: "first", 2: "second", 3: "third", 4: "final"}[year]
        mature = " as a mature student" if age >= 25 else ""
        return f"You are in the {ordinal} year of an undergraduate degree in {fld} at a university in {city}{mature}."
    if edu == "Master student":
        return f"You are doing a one-year master's degree in {fld} at a university in {city}."
    if edu == "PhD student or above":
        return f"You are a PhD student in {fld} at a university in {city}."
    if edu == "High school or below":
        if age <= 19:
            return f"You are finishing a foundation year in {city}, before starting a degree in {fld}."
        return f"You are taking an access course at a college in {city}, to get into a degree in {fld}."
    return f"You are studying part-time for a professional qualification related to {fld} in {city}."


# Final design: the real answer to "Your educational background", in the questionnaire's own terms, folded into
# the student fact (every participant answered yes to "Are you a student?"), so "student" is said only once.
STUDENT = {
    "High school or below": "a student; your educational background is high school or below",
    "Bachelor student": "a bachelor's student",
    "Master student": "a master's student",
    "PhD student or above": "a student at PhD level or above",
    "Other": "a student; your educational background does not fit the usual categories "
             "(high school or below, bachelor's, master's, PhD or above)",
}


def student_line(p: Persona, place: str = "the UK") -> str:
    """'You live in the UK and you are a bachelor's student.'"""
    return f"You live in {place} and you are {STUDENT[p.education]}."


# Pilots only (render_backstory): the wording those runs were sent, kept so they can be reproduced.
EDUCATION_LINE = {
    "High school or below": "Your highest completed level of education is high school; you do not have a university degree.",
    "Bachelor student": "You are a bachelor's (undergraduate) student and do not have a university degree yet.",
    "Master student": "You are a master's student.",
    "PhD student or above": "You are a PhD student.",
    "Other": "Your educational background does not fit the usual categories (high school, bachelor's, master's, PhD).",
}


def gender_line(p: Persona, name: str = "") -> str:
    """'You are [name, ]a woman aged 21.' -- the real gender and age, stated literally."""
    you = f"You are {name}, " if name else "You are "
    pro = {"Female": "a woman", "Male": "a man"}
    if p.gender in pro:
        return f"{you}{pro[p.gender]} aged {p.age}."
    how = "you do not identify as a man or a woman" if p.gender == "Other" else "you prefer not to disclose your gender"
    return f"{you}aged {p.age}; {how}."


def render_demographic(p: Persona) -> str:
    """Final-design Persona: only the real data recorded in the experiment, nothing invented."""
    return " ".join([gender_line(p), student_line(p), "Now and then you take part in paid online studies on Prolific."])


INVENTED = ("name", "origin", "hometown", "nationality", "uni_city", "field_of_study", "study_line", "living",
            "relationship", "friend", "friend_met", "job")


def without_invented(p: Persona, source: str) -> Persona:
    """Copy of p with every invented attribute cleared, so personas.csv only shows what the agent really gets."""
    from dataclasses import replace

    blank = {k: "" for k in INVENTED}
    return replace(p, **blank, siblings=0, children=0, hobbies=[], source=source)


def demographic_personas(personas: list[Persona]) -> list[Persona]:
    return [without_invented(p, "demographic") for p in personas]


def render_backstory(p: Persona) -> str:
    pro = {"Female": "a woman", "Male": "a man"}
    who = f"You are {p.name}, {pro[p.gender]} aged {p.age}." if p.gender in pro else \
        f"You are {p.name}, aged {p.age}; you do not identify as a man or a woman." if p.gender == "Other" else \
        f"You are {p.name}, aged {p.age}; you prefer not to disclose your gender."
    if p.origin in UK:
        origin = f"You grew up in {p.hometown}, {p.origin}."
    else:
        origin = f"You are {p.nationality} and grew up in {p.hometown}, {p.origin}; you moved to the UK to study."
    sib = {0: "You are an only child", 1: "You have one sibling", 2: "You have two siblings",
           3: "You have three siblings"}[p.siblings]
    rel = {"single": "you are single", "in a relationship": "you are in a relationship",
           "married": "you are married"}[p.relationship]
    kids = "" if not p.children else f", with {'one child' if p.children == 1 else 'two children'}"
    hobbies = ", ".join(p.hobbies[:-1]) + f" and {p.hobbies[-1]}"
    lines = [
        who,
        origin,
        p.study_line,
        EDUCATION_LINE[p.education],
        f"You live {p.living}. {sib}, and {rel}{kids}.",
        f"Your closest friend is {p.friend}, whom you met {p.friend_met}.",
        f"In your free time you enjoy {hobbies}.",
    ]
    if p.job:
        lines.append(f"Besides studying, you {p.job.replace('works', 'work').replace('does', 'do')}.")
    lines.append("Now and then you take part in paid online studies on Prolific.")
    return " ".join(lines)


RICH = Path(__file__).with_name("personas_rich.yaml")


def add_rich(personas: list[Persona]) -> list[Persona]:
    """Keep only the agents with a hand-written rich Persona and attach it (same person, same facts)."""
    import yaml

    texts = yaml.safe_load(RICH.read_text())
    out = [p for p in personas if p.agent_id in texts]
    missing = set(texts) - {p.agent_id for p in out}
    if missing:
        raise ValueError(f"rich personas without a matching participant: {sorted(missing)}")
    for p in out:
        p.rich = texts[p.agent_id]
        p.version = PERSONA_VERSION + "+rich-v1"
    return out


def to_frame(personas: list[Persona]) -> pd.DataFrame:
    rows = [{**asdict(p), "hobbies": "; ".join(p.hobbies), "backstory": p.backstory()} for p in personas]
    return pd.DataFrame(rows)


def write(personas: list[Persona], path: Path) -> None:
    to_frame(personas).to_csv(path, index=False)
