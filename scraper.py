import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

TARGET_SOURCES = [
    {"name": "Kariyer Kapisi", "url": "https://kariyerkapisi.gov.tr/isealim", "group": "genel"},
    {"name": "ISKUR Kamu", "url": "https://www.iskur.gov.tr/ilanlar/kamu-memur-alim-ilanlari/", "group": "genel"},
    {"name": "Ilan.gov.tr", "url": "https://www.ilan.gov.tr/ilan/kategori/8/kamu-akademik-personel?ats=5&currentPage=0", "group": "genel"},
    {"name": "SBB Kamu Ilan", "url": "https://kamuilan.sbb.gov.tr/", "group": "genel"},
    {"name": "Memurlar.net Ilan", "url": "https://ilan.memurlar.net/default.aspx", "group": "genel"},
    {"name": "Isinolsa Memur", "url": "https://www.isinolsa.com/memur-alimi/", "group": "genel"},
    {"name": "MSB Personel Temin", "url": "https://personeltemin.msb.gov.tr/", "group": "askeri"},
    {"name": "Jandarma Personel Temin", "url": "https://personeltemin.jandarma.gov.tr/", "group": "askeri"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
}

CATEGORY_RULES = {
    "Askeri": ["uzman cavus", "uzman erbas", "sozlesmeli er", "astsubay", "subay", "muvazzaf", "jandarma", "msb", "tsk", "temin", "duyuru"],
    "Sağlık": ["hemsire", "saglik", "ebelik", "paramedik", "laboratuvar", "eczaci", "hastane", "dis", "tibbi sekreter"],
    "Şoför": ["sofor", "surucu", "ambulans", "agir vasita", "src", "psikoteknik", "nakliye"],
    "Mühendis": ["muhendis", "mimar", "sehir planlama"],
    "Teknik": ["tekniker", "teknisyen", "bakim", "onarim", "elektrik", "makine", "insaat"],
    "Öğretmen": ["ogretmen", "egitmen", "ogretim", "akademik", "universite", "arastirma gorevlisi"],
    "Güvenlik": ["guvenlik", "ogg", "koruma ve guvenlik"],
    "Adalet": ["zabıt katibi", "zabit katibi", "infaz", "adliye", "ceza infaz", "icra"],
    "Bilişim": ["bilisim", "yazilim", "programci", "ag", "siber", "sistem uzmani", "veri"],
    "Sosyal": ["sosyal calismaci", "psikolog", "cocuk gelisimi", "asdep", "pdr"],
    "Destek": ["temizlik", "hizmetli", "asci", "mutfak", "bahcivan", "destek personeli"],
    "Büro": ["memur", "buro", "veri hazirlama", "vhki", "idari", "sekreter", "kadro"],
}

DOC_RULES = {
    "Ehliyet": ["ehliyet", "surucu belgesi", "b sinifi", "d sinifi", "c sinifi"],
    "SRC": ["src", "psikoteknik"],
    "Güvenlik": ["ogg", "ozel guvenlik", "silahli", "silahsiz"],
    "Bilgisayar": ["bilgisayar", "hijyen", "sertifika", "meb"],
    "IlkYardim": ["ilk yardim"],
    "YDS": ["yds", "yokdil", "yabanci dil"],
}


def normalize_tr(text: str) -> str:
    table = str.maketrans("ğüşıöçĞÜŞİÖÇ", "gusıocGUSIOC")
    return re.sub(r"\s+", " ", (text or "").translate(table).lower()).strip()


def detect_category(text_norm: str, group: str = "genel") -> str:
    if group == "askeri":
        return "Askeri"
    for cat, keywords in CATEGORY_RULES.items():
        if any(kw in text_norm for kw in keywords):
            return cat
    return "Büro"


def detect_education(text_norm: str) -> str:
    if "lisans" in text_norm and "onlisans" not in text_norm:
        return "Lisans"
    if "onlisans" in text_norm or "2 yillik" in text_norm:
        return "Önlisans"
    if "ortaogretim" in text_norm or "lise" in text_norm or "p94" in text_norm:
        return "Ortaöğretim"
    return "Lisans"


def detect_min_score(text_norm: str) -> int:
    patterns = [
        r"(?:en az|minimum|taban)?\s*(\d{2}(?:[.,]\d+)?)\s*(?:kpss)?\s*puan",
        r"kpss\s*(?:p3|p93|p94)?\s*[:\-]?\s*(\d{2}(?:[.,]\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text_norm)
        if m:
            try:
                val = float(m.group(1).replace(",", "."))
                if 40 <= val <= 100:
                    return int(round(val))
            except ValueError:
                pass
    return 0


def detect_docs(text_norm: str) -> list[str]:
    found = []
    for doc_code, keywords in DOC_RULES.items():
        if any(kw in text_norm for kw in keywords):
            found.append(doc_code)
    return found


def fetch_source_items(source: dict) -> list[dict]:
    items = []
    group = source.get("group", "genel")
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen_links = set()
        for a in soup.find_all("a", href=True):
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            href = a["href"].strip()
            if len(title) < 15 or len(title) > 220:
                continue
            if href.startswith("#") or href.startswith("javascript:"):
                continue

            full_url = urljoin(source["url"], href)
            if full_url in seen_links:
                continue

            norm = normalize_tr(title)
            keywords = ["alim", "ilan", "memur", "personel", "sozlesmeli", "kadro", "tekniker", "hemsire", "sofor", "guvenlik", "ogretmen", "akademik"]
            if group == "askeri":
                keywords += ["temin", "duyuru", "uzman", "astsubay", "subay", "erbas", "er", "aday", "sinav", "basvuru"]

            if not any(k in norm for k in keywords):
                continue

            seen_links.add(full_url)
            items.append({
                "id": f"{normalize_tr(source['name'])[:8]}-{abs(hash(full_url)) % 1000000}",
                "source": source["name"],
                "group": group,
                "category": detect_category(norm, group),
                "education": detect_education(norm),
                "minScore": detect_min_score(norm),
                "requiredDocs": detect_docs(norm),
                "title": title,
                "institution": source["name"],
                "deadline": "Güncel Duyuru / Temin" if group == "askeri" else "Güncel İlan",
                "summary": f"{source['name']} üzerinden yakalanan güncel {'askeri temin/duyuru' if group == 'askeri' else 'alım/ilan'} kaydı.",
                "details": f"Bu kayıt {source['name']} kaynağından otomatik çekilmiştir. Güncel başvuru tarihleri, nitelik kodları ve özel şartlar için resmi bağlantıyı inceleyiniz.",
                "officialUrl": full_url,
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
            })
            if len(items) >= 25:
                break
    except Exception as exc:
        print(f"[UYARI] {source['name']} taranamadı ({source['url']}): {exc}")
    return items


def run_scraper(output_path: str = "ilanlar.json") -> None:
    existing = []
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except FileNotFoundError:
        existing = []

    by_url = {item["officialUrl"]: item for item in existing if item.get("officialUrl")}
    added_count = 0

    for src in TARGET_SOURCES:
        pulled = fetch_source_items(src)
        for item in pulled:
            if item["officialUrl"] not in by_url:
                by_url[item["officialUrl"]] = item
                added_count += 1

    merged = list(by_url.values())
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Tamamlandı. Yeni eklenen ilan: {added_count} | Toplam kayıt: {len(merged)}")


if __name__ == "__main__":
    run_scraper()
