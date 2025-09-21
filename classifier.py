import re, html, urllib.parse, unicodedata, math

# --- Strong patterns (higher weights) ---
RULES = [
    # XSS
    (re.compile(r"<\s*script\b", re.I), 4.0, "XSS:<script>"),
    (re.compile(r"\bon(?:error|load)\s*=", re.I), 3.0, "XSS:on* handler"),
    (re.compile(r"javascript\s*:", re.I), 2.5, "XSS:javascript:"),
    # SQLi
    (re.compile(r"\bunion\s+select\b", re.I), 4.5, "SQLi:UNION SELECT"),
    (re.compile(r"\bor\s+1\s*=\s*1\b", re.I), 3.5, "SQLi:OR 1=1"),
    (re.compile(r"--\s|;--", re.I), 2.5, "SQLi:comment"),
    (re.compile(r";\s*drop\b", re.I), 4.0, "SQLi:DROP"),
    (re.compile(r"\binformation_schema\b", re.I), 2.5, "SQLi:information_schema"),
    # SSRF
    (re.compile(r"\b169\.254\.169\.254\b"), 5.0, "SSRF:metadata IP"),
    (re.compile(r"/metadata/computeMetadata", re.I), 3.5, "SSRF:GCP metadata"),
    (re.compile(r"\bgopher://", re.I), 3.0, "SSRF:gopher"),
    (re.compile(r"\bfile://", re.I), 2.5, "SSRF:file-scheme"),
]

# --- Weak hints (lower weights) ---
HINTS = [
    (re.compile(r"\bselect\b.*\bfrom\b", re.I | re.S), 1.0, "SQLi:SELECT FROM"),
    (re.compile(r"\bdrop\s+table\b", re.I), 1.5, "SQLi:drop table"),
    (re.compile(r"\bload_file\s*\(", re.I), 1.5, "SQLi:load_file("),
    (re.compile(r"\bdata:\s*text/html", re.I), 1.5, "XSS:data:text/html"),
]

DB_TIMEOUT_TOKENS = [("DBConnectionTimeout", 1.0), ("timeout", 0.5)]

def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    # try URL decode repeatedly (defensive)
    prev = None
    while prev != s:
        prev = s
        try:
            s = urllib.parse.unquote(s)
        except Exception:
            break
    s = html.unescape(s)
    s = s.replace("\x00", "")
    s = re.sub(r"\s+", " ", s.strip())
    return s.lower()

def _signals(text: str) -> list[tuple[str, float]]:
    out = []
    # special char density
    specials = len(re.findall(r"[<>'\";(){}$]", text))
    if specials >= 8: out.append(("signal:special-char-burst", min(2.0, specials * 0.1)))
    # unbalanced quotes
    if text.count("'") % 2 == 1 or text.count('"') % 2 == 1:
        out.append(("signal:unbalanced-quotes", 0.8))
    # many schemes
    schemes = len(re.findall(r"\b(?:http|https|file|gopher|ftp)://", text))
    if schemes >= 3: out.append(("signal:multi-scheme", min(1.5, 0.4 * schemes)))
    return out

def _logistic(score: float, k=0.6, x0=5.0) -> float:
    # k: slope, x0: midpoint (where confidence ~0.5)
    return 1.0 / (1.0 + math.exp(-k * (score - x0)))

def classify(payload):
    # Accept str or dict-like with message/payload/meta
    if isinstance(payload, str):
        raw = payload[:8000]
    else:
        parts = [
            str(getattr(payload, "get", lambda *_: "")("message", "")),
            str(getattr(payload, "get", lambda *_: "")("payload", "")),
            str(getattr(payload, "get", lambda *_: "")("meta", "")),
        ]
        raw = " ".join(parts)[:8000]

    text = _normalize(raw)
    score = 0.0
    labels = set()
    evidence = []

    # Rules
    for rx, w, tag in RULES:
        if rx.search(text):
            score += w
            evidence.append((tag, w))
            if tag.startswith("XSS:"): labels.add("XSS")
            if tag.startswith("SQLi"): labels.add("SQLI")
            if tag.startswith("SSRF"): labels.add("SSRF")

    # Hints
    for rx, w, tag in HINTS:
        if rx.search(text):
            score += w
            evidence.append((tag, w))
            if tag.startswith("XSS:"): labels.add("XSS")
            if tag.startswith("SQLi"): labels.add("SQLI")

    # DB timeout heuristic
    for token, w in DB_TIMEOUT_TOKENS:
        if token.lower() in text:
            score += w
            evidence.append(("DB:timeout", w))
            labels.add("DB_TIMEOUT")

    # Generic signals
    for tag, w in _signals(text):
        score += w
        evidence.append((tag, w))

    # Cap and map to risk
    score = round(score, 2)
    confidence = round(_logistic(score), 3)  # 0..1, smooth, not arbitrary

    if score >= 7.0:
        risk = "HIGH"
    elif score >= 3.0:
        risk = "MEDIUM"
    elif score > 0:
        risk = "LOW"
    else:
        risk = "NONE"

    # Top 5 evidence items by weight
    evidence.sort(key=lambda t: t[1], reverse=True)
    ev = [f"{tag} (+{w})" for tag, w in evidence[:5]]

    return {
        "labels": sorted(labels),
        "risk": risk,
        "score": score,
        "confidence": confidence,
        "evidence": ev
    }
