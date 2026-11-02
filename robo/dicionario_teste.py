"""
Teste do dicionário com fontes abertas (01/11/2026). NÃO escreve nada no Portal.

Para cada palavra da lista de teste, escreve o verbete de DUAS maneiras e guarda lado a lado:
  antigo  o jeito de hoje: o modelo escreve de memória, guiado só pela base do Wiktionary.
  novo    o modelo recebe os sentidos reais (WordNet de Princeton + Wiktionary) e frases reais com tradução humana
          (Tatoeba, CC BY 2.0 FR). O modelo ESCOLHE entre elas; os exemplos do verbete são copiados dessas frases por
          código, não reescritos pelo modelo.

Licenças a creditar se o novo jeito for adotado: Wiktionary (CC BY-SA), Tatoeba (CC BY 2.0 FR), WordNet (licença
própria de Princeton, permite uso comercial com a nota de direitos).
"""

import io
import json
import os
import re
import time
import zipfile

import requests

import dicionario as d

PALAVRAS = [
    # as três que o Othon viu com erro
    "whole", "following", "law",
    # trabalho do dia a dia
    "meeting", "deadline", "budget", "schedule", "project", "manage", "issue", "address", "deal", "claim", "lead", "drive",
    "figure", "file", "firm", "raise", "appeal", "bill", "check", "count", "cover", "case", "point", "order", "board",
    "sign", "charge", "run", "book", "light", "fine", "mean", "right", "close", "present", "bank", "plant", "party",
    "bear", "tie", "cut", "draw", "set", "stand", "turn", "play", "work", "time", "of",
    # mais abstratas e gramaticais
    "since", "though", "rather", "quite", "fair", "just", "still", "even", "enough", "either", "own", "such", "several",
    "another", "during", "against", "although", "whether", "unless", "regarding",
    # negócios
    "revenue", "invoice", "stakeholder", "negotiate", "supplier", "forecast", "profit", "client", "contract", "salary",
    "promote", "hire", "resign", "attend", "approve", "deliver", "improve", "suggest", "agree", "avoid",
    # quotidiano
    "weather", "travel", "dinner", "house", "money", "family", "friend", "water", "street", "morning",
]

CLASSE_WN = {"n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb"}


# ------------------------------------------------------------------------------------------------ fontes

def carregar_wordnet():
    """WordNet: baixado direto (o downloader do NLTK recusa proxy) e aberto num diretório privado."""
    pasta = os.path.expanduser("~/nltk_data/corpora")
    os.makedirs(pasta, exist_ok=True)
    if not os.path.isdir(os.path.join(pasta, "wordnet")):
        r = requests.get("https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip", timeout=120)
        r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(pasta)
    from nltk.corpus import wordnet as wn

    wn.ensure_loaded()
    return wn


def sentidos_wordnet(wn, palavra, maximo=5):
    """Os sentidos mais usados do WordNet para a palavra, do mais para o menos frequente."""
    achados = []
    for ordem, sy in enumerate(wn.synsets(palavra)):
        uso = sum(le.count() for le in sy.lemmas() if le.name().lower() == palavra.lower())
        achados.append((-uso, ordem, sy))
    achados.sort(key=lambda x: (x[0], x[1]))
    saida = []
    for _, _, sy in achados[:maximo]:
        saida.append({
            "classe": CLASSE_WN.get(sy.pos(), sy.pos()),
            "definicao_en": sy.definition(),
            "exemplos_en": sy.examples()[:2],
            "sinonimos": [le.name().replace("_", " ") for le in sy.lemmas() if le.name().lower() != palavra.lower()][:4],
        })
    return saida


def formas_de(p):
    return {p, p + "s", p + "es", p + "ed", p + "d", p + "ing", p[:-1] + "ies" if p.endswith("y") else p + "s", p[:-1] + "ied" if p.endswith("y") else p + "ed"}


def carregar_tatoeba(palavras):
    """Frases reais inglês→português (Tatoeba, via ManyThings). Guarda só as que contêm alguma das palavras de teste."""
    r = requests.get("https://www.manythings.org/anki/por-eng.zip", timeout=300, headers={"User-Agent": d.AGENTE})
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nome = next(n for n in z.namelist() if n.endswith(".txt"))
    formas = {}
    for p in palavras:
        for f in formas_de(p):
            formas.setdefault(f, set()).add(p)
    por_palavra = {p: [] for p in palavras}
    total = 0
    for linha in z.read(nome).decode("utf-8").splitlines():
        partes = linha.split("\t")
        if len(partes) < 2:
            continue
        en, pt = partes[0].strip(), partes[1].strip()
        total += 1
        toks = re.findall(r"[a-z']+", en.lower())
        if not 4 <= len(toks) <= 14:
            continue
        for tk in set(toks):
            for p in formas.get(tk, ()):
                por_palavra[p].append((en, pt, tk == p))
    d.aviso("Tatoeba", f"{total} pares lidos")
    return por_palavra


def melhores_frases(candidatas, quantas=6):
    """As frases mais curtas e naturais; a forma exata da palavra ganha das flexionadas. Sem repetir."""
    vistos, saida = set(), []
    for en, pt, exata in sorted(candidatas, key=lambda x: (not x[2], abs(len(x[0].split()) - 8), x[0])):
        if en.lower() in vistos or "?" in en and len(saida) >= 2:
            continue
        vistos.add(en.lower())
        saida.append({"en": en, "pt": pt})
        if len(saida) >= quantas:
            break
    return saida


# ------------------------------------------------------------------------------------------------ o jeito novo

ESQUEMA_NOVO = json.loads(json.dumps(d.ESQUEMA))
_sent = ESQUEMA_NOVO["properties"]["sentidos"]["items"]
_sent["properties"]["frase"] = {"type": "integer", "minimum": -1, "maximum": 5}
_sent["required"] = ["classe", "definicao", "frase"]
_sent["properties"].pop("exemplo", None)
_sent["properties"].pop("exemploPt", None)
ESQUEMA_NOVO["properties"].pop("frases", None)
ESQUEMA_NOVO["properties"]["frasesExtras"] = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 5}, "maxItems": 3}
ESQUEMA_NOVO["required"] = [c for c in ESQUEMA_NOVO["required"] if c != "frases"] + ["frasesExtras"]

SISTEMA_NOVO = d.SISTEMA + """

FONTES REAIS (esta versão): você recebe, no JSON, os sentidos de dicionários abertos ("sentidos_reais") e frases reais com
tradução humana ("frases_reais", numeradas de 0 em diante).
- sentidos: escolha até 3 DOS sentidos_reais, os mais úteis, e escreva a definição curta em português a partir da definição
  em inglês dele. Não invente sentido que não esteja nas fontes e não misture a entrada com outra palavra parecida
  (por exemplo, "wholeheartedly" não é um sentido de "whole"). Dois sentidos não podem dizer a mesma coisa.
- frase: em cada sentido, o NÚMERO da frase_real que usa a entrada exatamente naquele sentido. Se nenhuma servir, -1.
  Não escreva exemplo: o exemplo será copiado da frase escolhida.
- frasesExtras: até 3 números de outras frases_reais boas para o aluno (sem repetir as já escolhidas nos sentidos).
- padroes: só estruturas gramaticais reais da entrada (preposição, verbo + -ing, etc.). Se não houver, deixe vazio. Nunca
  escreva padrões genéricos como "noun + -s".
- Todo o resto segue as regras acima."""


def pedir_novo(lema, base, sentidos_reais, frases_reais):
    dados = {
        "entrada": lema,
        "classes": (base or {}).get("classes") or [],
        "traducoes_na_base": ((base or {}).get("traducoes") or [])[:10],
        "sentidos_reais": sentidos_reais,
        "frases_reais": [{"n": i, "en": f["en"]} for i, f in enumerate(frases_reais)],
    }
    corpo = {
        "messages": [{"role": "system", "content": SISTEMA_NOVO}, {"role": "user", "content": json.dumps(dados, ensure_ascii=False)}],
        "temperature": 0.2,
        "max_tokens": 1400,
        "response_format": {"type": "json_object", "schema": ESQUEMA_NOVO},
    }
    r = requests.post(d.LLM, json=corpo, timeout=1800)
    r.raise_for_status()
    v = json.loads(r.json()["choices"][0]["message"]["content"])
    v["frases"] = []
    usadas = set()
    for sd in v.get("sentidos") or []:
        i = sd.pop("frase", -1)
        if isinstance(i, int) and 0 <= i < len(frases_reais) and i not in usadas:
            sd["exemplo"], sd["exemploPt"] = frases_reais[i]["en"], frases_reais[i]["pt"]
            usadas.add(i)
    for i in v.pop("frasesExtras", []) or []:
        if isinstance(i, int) and 0 <= i < len(frases_reais) and i not in usadas:
            v["frases"].append(dict(frases_reais[i]))
            usadas.add(i)
    return d.conferir(lema, d.arrumar(v), (base or {}).get("formas") or [], base)


# ------------------------------------------------------------------------------------------------ defeitos automáticos

def defeitos(v, lema):
    """Lista de defeitos que dá para achar sem ler: o que o Othon viu nos verbetes 'whole', 'law' e 'following'."""
    if not v:
        return ["não saiu verbete"]
    f = []
    sentidos = v.get("sentidos") or []
    exemplos = [x.get("exemplo", "") for x in sentidos] + [fr.get("en", "") for fr in v.get("frases") or []]
    for e in exemplos:
        if "(" in e:
            f.append("exemplo com parênteses/tradução dentro")
        if e and d.lingua(e) == "pt":
            f.append("exemplo em português no campo inglês")
        if e and not e.rstrip().endswith((".", "!", "?", '"')):
            f.append("exemplo cortado")
    defs = [re.sub(r"\W+", " ", (x.get("definicao") or "").lower()).strip() for x in sentidos]
    for i in range(len(defs)):
        for j in range(i + 1, len(defs)):
            a, b = set(defs[i].split()), set(defs[j].split())
            if a and b and len(a & b) / len(a | b) >= 0.5:
                f.append("dois sentidos dizem a mesma coisa")
    if any(re.search(r"\+\s*-s\b", p.get("padrao", "")) for p in v.get("padroes") or []):
        f.append("padrão genérico '+ -s'")
    if any(not x.get("exemplo") for x in sentidos):
        f.append("sentido sem exemplo")
    return sorted(set(f))


# ------------------------------------------------------------------------------------------------ rodada

def fazer_teste(maquina, maquinas):
    todas = list(dict.fromkeys(PALAVRAS))
    minhas = todas[int(maquina) - 1 :: int(maquinas)]
    if os.environ.get('LIMITE_PALAVRAS', '25000').isdigit() and int(os.environ['LIMITE_PALAVRAS']) < 100:
        minhas = minhas[: int(os.environ['LIMITE_PALAVRAS'])]
    wn = carregar_wordnet()
    tatoeba = carregar_tatoeba(todas)
    saida = open(f"teste-{maquina}.jsonl", "w", encoding="utf-8")
    for palavra in minhas:
        if time.time() - d.INICIO > d.LIMITE_DE_TEMPO:
            break
        reg = {"palavra": palavra}
        try:
            base = d.base_da_palavra(palavra)
            reg["tem_base"] = bool(base)
            sentidos = sentidos_wordnet(wn, palavra)
            if base:
                for x in (base.get("sentidosEn") or [])[:3]:
                    sentidos.append({"classe": "", "definicao_en": x.get("definicao"), "exemplos_en": [], "sinonimos": []})
            frases = melhores_frases(tatoeba.get(palavra, []))
            reg["n_sentidos_reais"], reg["n_frases_reais"] = len(sentidos), len(frases)
        except Exception as e:  # noqa: BLE001
            reg["erro_fontes"] = str(e)[:200]
            saida.write(json.dumps(reg, ensure_ascii=False) + "\n")
            continue
        for chave, fazer in (("antigo", lambda: d.pedir_verbete(palavra, "PALAVRA", base)), ("novo", lambda: pedir_novo(palavra, base, sentidos, frases))):
            t0 = time.time()
            try:
                reg[chave] = fazer()
            except Exception as e:  # noqa: BLE001
                reg[chave] = None
                reg[f"erro_{chave}"] = str(e)[:200]
                print(f"ERRO {chave} {palavra}: {type(e).__name__}: {str(e)[:300]}", flush=True)
            reg[f"segundos_{chave}"] = round(time.time() - t0)
            reg[f"defeitos_{chave}"] = defeitos(reg[chave], palavra)
        saida.write(json.dumps(reg, ensure_ascii=False) + "\n")
        saida.flush()
        print(f"  {palavra}: antigo {reg.get('defeitos_antigo')} · novo {reg.get('defeitos_novo')}", flush=True)
    saida.close()
