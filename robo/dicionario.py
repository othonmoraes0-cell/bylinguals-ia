"""
Robô do Dicionário Bylinguals (09/10/2026).

Dois trabalhos, os dois grátis:

  base        Lê o Wiktionary inteiro já extraído (kaikki.org, wiktextract; licença CC BY-SA do Wiktionary), escolhe as
              palavras mais usadas do inglês (wordfreq), os phrasal verbs e os idioms, e manda ao Portal, em lotes, o que
              cada um tem de base: classes, fonética UK/US, sílabas, sentidos em inglês, sinônimos, relacionados, derivados,
              formas e traduções para o português.

  enriquecer  Pede ao Portal um lote (as sugestões de alunos e professores primeiro; depois os verbetes do mais usado ao
              menos usado) e escreve cada verbete no estilo Bylinguals com um modelo de linguagem aberto (llama.cpp), em
              português do Brasil: conceito, traduções, sentidos com exemplos, collocations, padrões, frases, alternativas,
              phrasal verbs, idioms, erro comum de brasileiro, áreas profissionais e intenções. Várias máquinas ao mesmo
              tempo: o Portal reserva cada verbete para uma só.

Nada é copiado de dicionário comercial. O Portal reconhece o robô pelo token OIDC do GitHub (sem senha).
"""

import gzip
import io
import json
import os
import re
import sys
import time
import urllib.parse

import requests

SITE = os.environ.get("SITE_URL", "https://www.bylinguals.com.br").rstrip("/")
LLM = os.environ.get("LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
AGENTE = "BylingualsDicionario/1.0 (+https://www.bylinguals.com.br)"
INICIO = time.time()
LIMITE_DE_TEMPO = float(os.environ.get("LIMITE_HORAS", "5.3")) * 3600
DUMP = os.environ.get("KAIKKI_DUMP", "https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz")


def aviso(titulo, texto):
    t = str(texto).replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::notice title={titulo}::{t}", flush=True)


def token():
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=bylinguals-portal"
    r = requests.get(url, headers={"Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]}, timeout=30)
    r.raise_for_status()
    return r.json()["value"]


def portal(metodo, caminho, corpo=None, tentativas=4):
    for i in range(tentativas):
        try:
            r = requests.request(metodo, SITE + caminho, json=corpo, headers={"Authorization": "Bearer " + token(), "User-Agent": AGENTE}, timeout=300)
            if r.status_code >= 500 and i < tentativas - 1:
                time.sleep(15 * (i + 1))
                continue
            return r
        except requests.RequestException:
            if i == tentativas - 1:
                raise
            time.sleep(15 * (i + 1))


# ------------------------------------------------------------------------------------------------ base aberta

CLASSES = {
    "noun": "noun", "verb": "verb", "adj": "adjective", "adv": "adverb", "prep": "preposition", "conj": "conjunction",
    "pron": "pronoun", "det": "determiner", "intj": "interjection", "num": "number", "phrase": "phrase", "prep_phrase": "phrase",
    "particle": "particle", "article": "article", "contraction": "contraction", "proverb": "proverb", "affix": None,
    "suffix": None, "prefix": None, "name": None, "character": None, "symbol": None, "abbrev": "abbreviation",
}
RUINS = {"obsolete", "archaic", "dated", "rare", "nonstandard", "misspelling", "obsolete-form", "historical", "dialectal", "offensive", "vulgar", "slur", "derogatory"}
PARTICULAS = {"up", "down", "off", "on", "out", "in", "over", "away", "back", "through", "around", "round", "along", "about", "across", "after", "by", "for", "into", "with", "apart", "ahead", "forward", "together", "behind", "under", "upon", "onto", "without"}


def tags_de(x):
    return set(t.lower() for t in (x.get("tags") or []))


def sentido_bom(s):
    if s.get("form_of") or s.get("alt_of"):
        return False
    if tags_de(s) & RUINS:
        return False
    return bool(s.get("glosses"))


FRACAS = {"unstressed", "weak", "weak-form", "reduced", "clipping", "casual", "rapid"}


def ipa_de(sounds):
    """A pronúncia de dicionário: a forma forte primeiro ("my" é /maɪ/; /mɪ/ é a forma fraca, sem acento na frase)."""
    uk = us = livre = None
    def fraca(x):
        nota = " ".join(str(x.get(k) or "") for k in ("note", "raw_tags", "qualifier")).lower()
        return bool(tags_de(x) & FRACAS) or "weak" in nota or "unstressed" in nota

    for s in sorted(sounds or [], key=fraca):
        if fraca(s):
            continue
        ipa = s.get("ipa")
        if not ipa or not ipa.startswith(("/", "[")):
            continue
        t = tags_de(s)
        if not uk and (t & {"uk", "received-pronunciation", "british"}):
            uk = ipa
        elif not us and (t & {"us", "general-american", "america"}):
            us = ipa
        elif not livre and not t:
            livre = ipa
    return uk or livre, us or livre


def silabas_de(e):
    for h in e.get("hyphenations") or []:
        partes = h.get("parts") if isinstance(h, dict) else None
        if partes and len(partes) > 1:
            return "·".join(partes)
    h = e.get("hyphenation")
    if isinstance(h, list) and len(h) > 1:
        return "·".join(h)
    return None


def tonica(silabas, ipa):
    if not silabas or not ipa:
        return None
    limpo = ipa.strip("/[]")
    partes_ipa = [p for p in re.split(r"[.ˈˌ]", limpo) if p]
    n = len(silabas.split("·"))
    if len(partes_ipa) != n or "ˈ" not in limpo:
        return None
    antes = limpo[: limpo.index("ˈ")]
    return len([p for p in re.split(r"[.ˈˌ]", antes) if p])


def palavras_de(lista, n):
    saida = []
    for x in lista or []:
        w = (x.get("word") if isinstance(x, dict) else x) or ""
        w = w.strip()
        if w and len(w) <= 60 and w not in saida and not w.startswith("Thesaurus:"):
            saida.append(w)
        if len(saida) >= n:
            break
    return saida


def tipo_do(palavra, pos, e):
    if " " not in palavra:
        return "PALAVRA"
    partes = palavra.split(" ")
    if pos == "verb" and len(partes) in (2, 3) and partes[-1] in PARTICULAS:
        return "PHRASAL_VERB"
    tg = set()
    for s in e.get("senses") or []:
        tg |= tags_de(s)
    if "idiomatic" in tg or pos in ("phrase", "proverb"):
        return "IDIOM"
    return "EXPRESSAO"


def juntar(atual, e, palavra):
    """Junta as entradas da mesma palavra (classes e etimologias diferentes) num verbete só."""
    pos = e.get("pos") or ""
    classe = CLASSES.get(pos, pos or None)
    if classe and classe not in atual["classes"]:
        atual["classes"].append(classe)
    uk, us = ipa_de(e.get("sounds"))
    atual["ipaUk"] = atual.get("ipaUk") or uk
    atual["ipaUs"] = atual.get("ipaUs") or us
    atual["silabas"] = atual.get("silabas") or silabas_de(e)
    for s in e.get("senses") or []:
        if not sentido_bom(s) or len(atual["sentidosEn"]) >= 8:
            continue
        d = {"classe": classe, "definicao": "; ".join(s["glosses"])[:400]}
        ex = next((x.get("text") for x in s.get("examples") or [] if x.get("text") and len(x["text"]) < 280), None)
        if ex:
            d["exemplo"] = ex
        if not d["classe"]:
            del d["classe"]
        atual["sentidosEn"].append(d)
    for chave, fonte, n in (("sinonimos", "synonyms", 12), ("antonimos", "antonyms", 8), ("relacionados", "related", 16), ("derivados", "derived", 24)):
        extra = palavras_de(e.get(fonte), n)
        for s in e.get("senses") or []:
            extra += palavras_de(s.get(fonte), n)
        for w in extra:
            if w not in atual[chave] and w != palavra and len(atual[chave]) < n:
                atual[chave].append(w)
    for t in e.get("translations") or []:
        if (t.get("lang_code") or t.get("code")) == "pt" and t.get("word"):
            w = t["word"].strip()
            if w and w not in atual["traducoes"] and len(atual["traducoes"]) < 12:
                atual["traducoes"].append(w[:80])
    for f in e.get("forms") or []:
        w = (f.get("form") or "").strip()
        if w and w != palavra and " " not in w and w not in atual["formas"] and len(atual["formas"]) < 12 and not (tags_de(f) & {"table-tags", "inflection-template", "romanization"}):
            atual["formas"].append(w)
    if atual["tipo"] == "PALAVRA":
        atual["tipo"] = tipo_do(palavra, pos, e)


def novo(palavra):
    return {"lema": palavra, "tipo": "PALAVRA", "classes": [], "sentidosEn": [], "sinonimos": [], "antonimos": [], "relacionados": [], "derivados": [], "traducoes": [], "formas": []}


def limpar(v):
    v = {k: x for k, x in v.items() if x not in (None, [], "")}
    v.setdefault("classes", [])
    t = tonica(v.get("silabas"), v.get("ipaUs") or v.get("ipaUk"))
    if t is not None:
        v["tonica"] = t
    return v


def fazer_base(limite):
    from wordfreq import top_n_list, zipf_frequency

    palavras = top_n_list("en", int(limite * 2.2))
    rank = {w: i + 1 for i, w in enumerate(palavras)}
    comuns = set(palavras[:6000])
    print(f"Lista de frequência: {len(palavras)} palavras", flush=True)

    verbetes = {}
    lidas = 0
    with requests.get(DUMP, stream=True, timeout=120, headers={"User-Agent": AGENTE}) as r:
        r.raise_for_status()
        texto = io.TextIOWrapper(gzip.GzipFile(fileobj=r.raw), encoding="utf-8")
        for linha in texto:
            lidas += 1
            if lidas % 1_000_000 == 0:
                print(f"  {lidas:,} linhas lidas, {len(verbetes):,} verbetes", flush=True)
            if '"lang_code": "en"' not in linha and '"lang_code":"en"' not in linha:
                continue
            try:
                e = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if e.get("lang_code") != "en":
                continue
            palavra = (e.get("word") or "").strip()
            pos = e.get("pos") or ""
            if not palavra or len(palavra) > 60 or CLASSES.get(pos, "x") is None:
                continue
            if not any(sentido_bom(s) for s in e.get("senses") or []):
                continue
            minus = palavra.lower()
            if " " not in palavra:
                if palavra != minus and minus not in rank:
                    continue  # nomes próprios e siglas raras
                if minus not in rank or not re.fullmatch(r"[a-z][a-z'\-]*", minus):
                    continue
            else:
                partes = minus.split(" ")
                if len(partes) > 6 or not all(re.fullmatch(r"[a-z'\-,.!?]+", p) for p in partes):
                    continue
                if not any(p in comuns for p in partes):
                    continue
            # Uma entrada por palavra, sem diferença de maiúsculas ("may" e "May" juntos; vale a forma minúscula).
            v = verbetes.setdefault(minus, novo(palavra))
            if palavra == minus:
                v["lema"] = minus
            juntar(v, e, palavra)

    print(f"Fim da leitura: {lidas:,} linhas, {len(verbetes):,} candidatos", flush=True)
    # Ordem: frequência do wordfreq (expressões pela frequência estimada da expressão inteira).
    pontos = {}
    for w, v in verbetes.items():
        if " " in w:
            z = zipf_frequency(w, "en")
            if v["tipo"] == "EXPRESSAO" and z < 3.0:
                continue
            if v["tipo"] in ("IDIOM", "PHRASAL_VERB") and z < 1.5:
                continue
            pontos[w] = z
        else:
            pontos[w] = 9 - rank[w] / 10000
    escolhidos = sorted(pontos, key=lambda w: -pontos[w])
    simples = [w for w in escolhidos if " " not in w][:limite]
    compostos = [w for w in escolhidos if " " in w][: max(3000, limite // 4)]
    final = sorted(simples + compostos, key=lambda w: -pontos[w])
    aviso("Base", f"{len(simples)} palavras e {len(compostos)} expressões, phrasal verbs e idioms")

    lote = []
    enviados = criados = invalidos = 0
    for i, w in enumerate(final):
        v = limpar(verbetes[w])
        v["frequencia"] = i + 1
        lote.append(v)
        if len(lote) >= 100 or i == len(final) - 1:
            r = portal("POST", "/api/robo/dicionario/base", {"verbetes": lote})
            if r.status_code != 200:
                aviso("Base: erro", f"HTTP {r.status_code} {r.text[:300]}")
                sys.exit(1)
            d = r.json()
            enviados += len(lote)
            criados += d.get("criados", 0)
            invalidos += d.get("invalidos", 0)
            if (enviados // 100) % 20 == 0:
                print(f"  enviados {enviados}/{len(final)}", flush=True)
            lote = []
    aviso("Base enviada", f"{enviados} verbetes ({criados} novos, {invalidos} fora do formato)")


# ------------------------------------------------------------------------------------------------ verbete Bylinguals

AREAS = ["Negócios", "Finanças", "Contabilidade", "Vendas", "Marketing", "Recursos Humanos", "Tecnologia", "Direito", "Saúde", "Engenharia", "Indústria", "Logística", "Comércio exterior", "Agronegócio", "Educação", "Turismo e hotelaria", "Ciência", "Comunicação"]


def s(maxlen):
    return {"type": "string", "maxLength": maxlen}


ESQUEMA = {
    "type": "object",
    "properties": {
        "conceito": s(260),
        "traducoes": {"type": "array", "items": s(50), "minItems": 1, "maxItems": 6},
        "nivel": {"type": "string", "enum": ["A1", "A2", "B1", "B2", "C1", "C2"]},
        "registro": {"type": "string", "enum": ["formal", "neutro", "informal", "gíria", "técnico"]},
        "areas": {"type": "array", "items": {"type": "string", "enum": AREAS}, "maxItems": 3},
        "sentidos": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "object", "properties": {"classe": s(25), "definicao": s(160), "exemplo": s(150), "exemploPt": s(170)}, "required": ["classe", "definicao", "exemplo", "exemploPt"]}},
        "collocations": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {"expressao": s(50), "traducao": s(70)}, "required": ["expressao", "traducao"]}},
        "padroes": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {"padrao": s(60), "exemplo": s(150), "traducao": s(170)}, "required": ["padrao", "exemplo", "traducao"]}},
        "frases": {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {"en": s(150), "pt": s(170)}, "required": ["en", "pt"]}},
        "alternativas": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {"palavra": s(40), "diferenca": s(160)}, "required": ["palavra", "diferenca"]}},
        "relacionados": {"type": "array", "items": s(40), "maxItems": 8},
        "phrasalVerbs": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {"expressao": s(40), "significado": s(90)}, "required": ["expressao", "significado"]}},
        "idioms": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {"expressao": s(70), "significado": s(110)}, "required": ["expressao", "significado"]}},
        "erroComum": s(200),
        "intencoes": {"type": "array", "items": s(60), "maxItems": 4},
    },
    "required": ["conceito", "traducoes", "nivel", "registro", "areas", "sentidos", "collocations", "padroes", "frases", "alternativas", "relacionados", "phrasalVerbs", "idioms", "erroComum", "intencoes"],
}

SISTEMA = """Você é lexicógrafo da Bylinguals, escola de inglês para profissionais brasileiros de empresas (reuniões, e-mails, apresentações, negociações, clientes, relatórios, entrevistas, viagens a trabalho).
Escreva o verbete do Dicionário Bylinguals para a entrada pedida. Responda só com o JSON pedido.

Regras (verbete CURTO e direto, foco no mundo das empresas):
- Português do Brasil nas explicações. Frases curtas. Nada de enrolação.
- Exemplos e frases em inglês do ambiente de trabalho (reunião, e-mail, cliente, projeto, prazo, equipe), naturais e atuais, com tradução. Se a palavra quase não aparece no trabalho, use um exemplo do dia a dia de um adulto.
- Escreva com as suas palavras. Nunca copie definições de dicionários publicados.
- conceito: 1 ou 2 frases curtas.
- traducoes: SÓ palavras em PORTUGUÊS, as mais usadas, da mais comum para a menos comum. Nunca repita a palavra em inglês.
- sentidos: só os sentidos reais e importantes (até 3), guiados pelos sentidos da base; nunca invente sentido. Definição curta + 1 exemplo.
- Todo exemplo em inglês tem que ser gramaticalmente correto e usar a entrada exatamente no sentido descrito. A tradução fica só no campo de tradução, nunca entre parênteses no exemplo.
- collocations: as combinações mais frequentes no trabalho, com tradução.
- padroes: estruturas de uso desta palavra em notação de professor (verbo + -ing, adjetivo + preposição etc.), com exemplo. Só padrões que usam a própria entrada.
- frases: frases prontas úteis no trabalho.
- alternativas: palavras em INGLÊS parecidas com a entrada, e a diferença em uma frase em português. Vazio se não houver.
- phrasalVerbs e idioms: só os reais e usados hoje, de preferência no trabalho. Vazio se não houver.
- erroComum: o erro típico de brasileiros (falso cognato, preposição, tradução literal, pronúncia), em uma frase. Vazio se não houver.
- areas: só se for termo de uma área profissional; senão vazio.
- nivel: o nível CEFR em que se aprende a palavra.
- intencoes: o que a pessoa quer dizer ao usar a palavra, em português, bem curto (um verbo no infinitivo + complemento).
- relacionados: palavras do mesmo campo, em inglês."""


def pedir_verbete(lema, tipo, base, contexto=None):
    b = base or {}
    dados = {
        "entrada": lema,
        "tipo": {"PALAVRA": "palavra", "PHRASAL_VERB": "phrasal verb", "IDIOM": "idiom", "EXPRESSAO": "expressão"}.get(tipo, "palavra"),
        "classes": b.get("classes") or [],
        "sentidos_na_base_em_ingles": [x.get("definicao") for x in (b.get("sentidosEn") or [])][:6],
        "traducoes_na_base": (b.get("traducoes") or [])[:10],
        "sinonimos_na_base": (b.get("sinonimos") or [])[:8],
    }
    if contexto:
        dados["onde_o_aluno_viu"] = contexto
    corpo = {
        "messages": [{"role": "system", "content": SISTEMA}, {"role": "user", "content": json.dumps(dados, ensure_ascii=False)}],
        "temperature": 0.3,
        "max_tokens": 1400,
        "response_format": {"type": "json_object", "schema": ESQUEMA},
    }
    r = requests.post(LLM, json=corpo, timeout=1800)
    r.raise_for_status()
    texto = r.json()["choices"][0]["message"]["content"]
    v = json.loads(texto)
    return conferir(lema, arrumar(v))


EXEMPLOS_DO_ENUNCIADO = {"suggest + -ing", "be good at + noun", "cobrar um prazo", "pedir desculpas"}


def lingua(texto):
    """'en', 'pt' ou None, pela frequência das palavras em cada língua (wordfreq)."""
    try:
        from wordfreq import zipf_frequency
    except ImportError:
        return None
    palavras = re.findall(r"[a-zà-ÿ']+", texto.lower())
    if not palavras:
        return None
    en = sum(zipf_frequency(w, "en") for w in palavras) / len(palavras)
    pt = sum(zipf_frequency(w, "pt") for w in palavras) / len(palavras)
    if abs(en - pt) < 0.8:
        return None
    return "en" if en > pt else "pt"


def conferir(lema, v):
    """Conferência automática antes de gravar (piloto de 09/10/2026). Devolve o verbete limpo ou levanta erro."""
    minus = lema.lower().strip()
    v["traducoes"] = [t for t in v.get("traducoes") or [] if t.strip() and t.strip().lower() != minus and lingua(t) != "en"]
    if not v["traducoes"]:
        raise ValueError("sem tradução em português")
    v["alternativas"] = [a for a in v.get("alternativas") or [] if a.get("palavra", "").strip().lower() != minus and lingua(a.get("palavra", "")) != "pt"]
    v["padroes"] = [p for p in v.get("padroes") or [] if p.get("padrao", "").strip().lower() not in EXEMPLOS_DO_ENUNCIADO]
    v["intencoes"] = [i for i in v.get("intencoes") or [] if i.strip().lower() not in EXEMPLOS_DO_ENUNCIADO]
    v["relacionados"] = [r for r in v.get("relacionados") or [] if r.strip().lower() != minus and lingua(r) != "pt"]
    for chave in ("sentidos", "padroes"):
        for x in v.get(chave) or []:
            ex = x.get("exemplo") or ""
            # Tradução entre parênteses dentro do exemplo em inglês: tira.
            x["exemplo"] = re.sub(r"\s*\([^)]*\)\s*$", "", ex).strip() or ex
    if not v.get("sentidos"):
        raise ValueError("sem sentidos")
    return v


def arrumar(v):
    """Tira campos vazios (o esquema pede todos; o Portal aceita sem os vazios)."""
    if not (v.get("erroComum") or "").strip():
        v.pop("erroComum", None)
    for k in ("collocations", "padroes", "frases", "alternativas", "relacionados", "phrasalVerbs", "idioms", "intencoes", "areas"):
        v[k] = [x for x in v.get(k) or [] if (x.strip() if isinstance(x, str) else all(str(y).strip() for y in x.values()))]
    v["traducoes"] = [t for t in v.get("traducoes") or [] if t.strip()] or ["—"]
    v["sentidos"] = [x for x in v.get("sentidos") or [] if x.get("definicao", "").strip()]
    for x in v["sentidos"]:
        for k in list(x):
            if not str(x[k]).strip():
                del x[k]
    return v


def base_da_palavra(termo):
    """Para uma sugestão: a página da palavra no kaikki (Wiktionary extraído)."""
    w = termo.strip()
    if not w:
        return None
    a = w[0]
    ab = w[:2]
    url = f"https://kaikki.org/dictionary/English/meaning/{urllib.parse.quote(a)}/{urllib.parse.quote(ab)}/{urllib.parse.quote(w)}.jsonl"
    for tentativa in (w, w.lower()):
        if tentativa != w:
            url = f"https://kaikki.org/dictionary/English/meaning/{urllib.parse.quote(tentativa[0])}/{urllib.parse.quote(tentativa[:2])}/{urllib.parse.quote(tentativa)}.jsonl"
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": AGENTE})
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        v = novo(tentativa)
        for linha in r.text.splitlines():
            try:
                e = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if e.get("lang_code", "en") == "en":
                juntar(v, e, tentativa)
        if v["sentidosEn"] or v["traducoes"]:
            return limpar(v)
    return None


def fazer_enriquecer(maquina, so_sugestoes=False):
    if str(maquina) == "1":
        teste = {w: lingua(w) for w in ("agora", "currently", "do que", "meeting", "reunião", "at the moment", "neste momento")}
        aviso("Conferência de língua", json.dumps(teste, ensure_ascii=False))
    feitos = erros = sugestoes = 0
    tempos = []
    # Piloto: TETO verbetes no total da rodada, divididos entre as máquinas.
    teto_total = int(os.environ.get("TETO", "0") or 0)
    maquinas = max(1, int(os.environ.get("MAQUINAS", "1") or 1))
    teto = -(-teto_total // maquinas) if teto_total > 0 else 0
    while time.time() - INICIO < LIMITE_DE_TEMPO:
        falta = teto - feitos if teto else 4
        if teto and falta <= 0:
            print(f"Chegou ao teto desta máquina ({teto}).", flush=True)
            break
        r = portal("POST", "/api/robo/dicionario/lote", {"quantos": 0 if so_sugestoes else min(4, falta), "minutos": 90})
        if r.status_code != 200:
            aviso("Lote: erro", f"HTTP {r.status_code} {r.text[:300]}")
            break
        lote = r.json()
        if not lote.get("sugestoes") and not lote.get("verbetes"):
            print("Nada mais na fila.", flush=True)
            break
        for sg in lote.get("sugestoes") or []:
            try:
                base = base_da_palavra(sg["termo"])
                lema = (base or {}).get("lema") or sg["termo"].strip()
                tipo = (base or {}).get("tipo") or ("EXPRESSAO" if " " in lema else "PALAVRA")
                v = pedir_verbete(lema, tipo, base, sg.get("contexto"))
                corpo = {"id": sg["id"], "verbete": v}
                if base:
                    corpo["base"] = base
                rr = portal("POST", "/api/robo/dicionario/sugestao", corpo)
                print(f"  sugestão '{sg['termo']}' → HTTP {rr.status_code}", flush=True)
                sugestoes += 1
            except Exception as e:  # noqa: BLE001
                portal("POST", "/api/robo/dicionario/sugestao", {"id": sg["id"], "erro": f"O robô não conseguiu: {str(e)[:200]}"})
                erros += 1
        for vb in lote.get("verbetes") or []:
            if time.time() - INICIO > LIMITE_DE_TEMPO:
                portal("POST", "/api/robo/dicionario/verbete", {"id": vb["id"]})
                continue
            t0 = time.time()
            try:
                v = pedir_verbete(vb["lema"], vb.get("tipo"), vb.get("base"))
                rr = portal("POST", "/api/robo/dicionario/verbete", {"id": vb["id"], "verbete": v})
                ok = rr.status_code == 200
                if not ok:
                    print(f"  {vb['lema']}: HTTP {rr.status_code} {rr.text[:300]}", flush=True)
                    erros += 1
                else:
                    feitos += 1
                tempos.append(time.time() - t0)
                print(f"  {vb['lema']}: {'ok' if ok else 'erro'} em {time.time() - t0:.0f} s", flush=True)
            except Exception as e:  # noqa: BLE001
                erros += 1
                print(f"  {vb['lema']}: falhou ({e})", flush=True)
                portal("POST", "/api/robo/dicionario/verbete", {"id": vb["id"]})
    media = sum(tempos) / len(tempos) if tempos else 0
    aviso(f"Máquina {maquina}", f"{feitos} verbetes escritos, {sugestoes} sugestões preparadas, {erros} erros; média {media:.0f} s por verbete")


# ------------------------------------------------------------------------------------------------ tradução da base

MODELO_DE_TRADUCAO = "Helsinki-NLP/opus-mt-tc-big-en-pt"


def carregar_tradutor():
    import torch
    from transformers import MarianMTModel, MarianTokenizer

    torch.set_num_threads(os.cpu_count() or 4)
    tok = MarianTokenizer.from_pretrained(MODELO_DE_TRADUCAO)
    mod = MarianMTModel.from_pretrained(MODELO_DE_TRADUCAO).eval()
    vocab = tok.get_vocab()
    prefixo = next((p for p in (">>pob<<", ">>por<<", ">>pt_br<<", ">>pt<<") if p in vocab), "")
    return torch, tok, mod, prefixo


def limpar_definicao(t):
    # Definições do Wiktionary juntam sentidos com "; " e às vezes trazem "[…]".
    t = re.sub(r"\[…\]|\[\.\.\.\]", "…", t)
    return t.strip()


def fazer_traducao_da_base(maquina, maquinas):
    """Traduz para o português os sentidos (e os exemplos curtos) da base aberta, do mais usado ao menos usado."""
    torch, tok, mod, prefixo = carregar_tradutor()

    def traduzir(textos):
        saida = []
        for i in range(0, len(textos), 24):
            pedaco = [(prefixo + " " + x).strip() for x in textos[i : i + 24]]
            entrada = tok(pedaco, return_tensors="pt", padding=True, truncation=True, max_length=200)
            with torch.inference_mode():
                gerado = mod.generate(**entrada, num_beams=1, max_new_tokens=220)
            saida += [x.strip() for x in tok.batch_decode(gerado, skip_special_tokens=True)]
        return saida

    feitos = 0
    t0 = time.time()
    while time.time() - INICIO < LIMITE_DE_TEMPO:
        r = portal("POST", "/api/robo/dicionario/para-traduzir", {"quantos": 120, "maquina": int(maquina), "maquinas": int(maquinas)})
        if r.status_code != 200:
            aviso("Tradução: erro", f"HTTP {r.status_code} {r.text[:300]}")
            break
        itens = r.json().get("itens") or []
        if not itens:
            print("Nada mais para traduzir.", flush=True)
            break
        textos, onde = [], []
        for n, it in enumerate(itens):
            for k, sdef in enumerate(it["sentidos"]):
                textos.append(limpar_definicao(sdef["definicao"])[:600])
                onde.append((n, k, "definicao"))
                ex = sdef.get("exemplo")
                if ex and len(ex) <= 220:
                    textos.append(ex)
                    onde.append((n, k, "exemplo"))
        traduzidos = traduzir(textos) if textos else []
        resultado = [{"id": it["id"], "sentidos": [{"definicao": ""} for _ in it["sentidos"]]} for it in itens]
        for (n, k, campo), tr in zip(onde, traduzidos):
            resultado[n]["sentidos"][k][campo] = tr[:780]
        for it in resultado:
            it["sentidos"] = [x if x.get("definicao") else {"definicao": "—"} for x in it["sentidos"]]
        rr = portal("POST", "/api/robo/dicionario/traducao", {"itens": resultado})
        if rr.status_code != 200:
            aviso("Tradução: erro ao gravar", f"HTTP {rr.status_code} {rr.text[:300]}")
            break
        feitos += len(itens)
        print(f"  {feitos} verbetes traduzidos ({len(textos)} trechos neste lote), {time.time() - t0:.0f} s", flush=True)
    aviso(f"Tradução da base · máquina {maquina}", f"{feitos} verbetes traduzidos em {time.time() - t0:.0f} s")


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "enriquecer"
    if modo == "refazer":
        # Volta para a fila os verbetes escritos pelo robô antes de agora (os revisados pela escola não mudam).
        r = portal("POST", "/api/robo/dicionario/refazer", {"antesDe": os.environ.get("REFAZER_ANTES_DE") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        aviso("Refazer", f"HTTP {r.status_code} {r.text[:300]}")
        sys.exit(0 if r.status_code == 200 else 1)
    if modo == "traduzir":
        fazer_traducao_da_base(os.environ.get("MAQUINA", "1"), os.environ.get("MAQUINAS", "1"))
        sys.exit(0)
    if modo == "base":
        fazer_base(int(os.environ.get("LIMITE_PALAVRAS", "25000")))
    elif modo == "sugestoes":
        fazer_enriquecer(os.environ.get("MAQUINA", "1"), so_sugestoes=True)
    else:
        fazer_enriquecer(os.environ.get("MAQUINA", "1"))
