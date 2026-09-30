import html, re, unicodedata
from bs4 import BeautifulSoup
VERSION = "unicode-porter-stopwords-v1"
TOKENIZER = "porter unicode61 remove_diacritics 2"
STOPWORDS = frozenset("""a an and are as at be been being but by can could did do does doing for from had has have having he her here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not of on once only or other our ours ourselves out over own same she should so some such than that the their theirs them themselves then there these they this those through to too under until up very was we were what when where which while who whom why will with would you your yours yourself yourselves also via using used use may might must shall each both few further about above after again against all am any because before below between during off ought since thus within without however therefore whose whom upon per et al eg ie""".split())
def normalize(text):
    text = html.unescape(str(text or ""))
    if re.search(r"</?(?:p|div|span|a|br|b|i|em|strong|sub|sup|script|style)\b", text, re.I):
        soup = BeautifulSoup(text, "html.parser")
        for element in soup(["script", "style"]): element.decompose()
        text = soup.get_text(" ")
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"https?://\S+|www\.\S+|[\w.+-]+@[\w.-]+\.[a-z]+", " ", text)
    text = re.sub(r"\\(?:begin|end)\{[^}]*\}|\\[a-z]+\*?", " ", text)
    text = re.sub(r"\[\s*\d+(?:[\s,–-]+\d+)*\s*\]", " ", text)
    tokens = re.findall(r"[^\W_]+", text, re.UNICODE)
    return " ".join(t for t in tokens if t not in STOPWORDS and len(t) > 1)
