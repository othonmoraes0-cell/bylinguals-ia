"""
Piloto do Jornal do Club — versão 2 (09/10/2026): "The Bylinguals Daily", mini resumo de 6 a 8 frases, IA grátis.

Fontes (decisão do usuário): The New York Times e CNN Brasil como fonte principal, NASA (domínio público).
Direitos reservados: de jornal, o robô usa só o TÍTULO e o RESUMO que o próprio veículo publica no feed; nunca abre a matéria.
Para ter fatos suficientes para 6 a 8 frases sem inventar, junta os resumos de feed de outros veículos sobre o MESMO assunto
(BBC, Guardian, DW, NPR, g1) e um parágrafo de contexto da Wikipedia (quem é a pessoa, o que é o lugar). O texto é escrito do
zero pela IA, com a lista de fontes. Da NASA (domínio público) lê a matéria inteira.

Não mexe no Portal: grava o relatório no ramo "piloto-jornal".
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import trafilatura

API = os.environ.get("LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODELO = os.environ.get("MODELO_ROTULO", "modelo")
UA = {"User-Agent": "Mozilla/5.0 (Bylinguals robo; piloto do jornal)"}

PRINCIPAIS = [
    {"nome": "The New York Times", "secao": "World", "feed": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "quantas": 2},
    {"nome": "CNN Brasil", "secao": "Brazil", "feed": "https://www.cnnbrasil.com.br/feed/", "quantas": 2},
    {"nome": "The New York Times", "secao": "Science", "feed": "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "quantas": 1},
    {"nome": "The New York Times", "secao": "Sports", "feed": "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml", "quantas": 1},
]
APOIO = [
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    ("BBC", "https://feeds.bbci.co.uk/sport/rss.xml"),
    ("The Guardian", "https://www.theguardian.com/world/rss"),
    ("The Guardian", "https://www.theguardian.com/science/rss"),
    ("DW", "https://rss.dw.com/rdf/rss-en-all"),
    ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    ("CNN Brasil", "https://www.cnnbrasil.com.br/feed/"),
    ("g1", "https://g1.globo.com/rss/g1/"),
]
NASA = {"nome": "NASA", "feed": "https://www.nasa.gov/news-release/feed/"}

PARADAS = set(
    """the a an and or but of to in on at for with from by as is are was were be been has have had will would can could
    this that these those it its their his her they he she we you after before over under into about more most new says said
    after amid than also just what when where who why how which while there here not no yes may might one two three
    de da do das dos e o a os as em no na nos nas um uma para por com que se ao à é foi são será ser como mais sobre após""".split()
)


def baixar(url, limite=3_000_000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read(limite).decode("utf-8", "replace")


def limpar(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(t or ""))).strip()


def itens_do_feed(url, veiculo):
    try:
        raiz = ET.fromstring(baixar(url).encode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  feed falhou: {url}: {str(e)[:120]}")
        return []
    itens = []
    for it in raiz.iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        dados = {"titulo": "", "link": "", "resumo": ""}
        for f in it:
            t = f.tag.split("}")[-1]
            if t == "title":
                dados["titulo"] = limpar(f.text)
            elif t == "link":
                dados["link"] = (f.text or f.get("href") or "").strip()
            elif t in ("description", "summary") and not dados["resumo"]:
                dados["resumo"] = limpar(f.text)[:700]
        if dados["titulo"] and dados["link"]:
            itens.append({**dados, "veiculo": veiculo})
    print(f"  feed ok: {veiculo} {url} ({len(itens)})")
    return itens


def palavras_chave(texto):
    return {w for w in re.findall(r"[a-zà-ú0-9][a-zà-ú0-9'-]{3,}", texto.lower()) if w not in PARADAS}


def parecidas(principal, pool):
    chave = palavras_chave(principal["titulo"] + " " + principal["resumo"])
    nomes = set(re.findall(r"\b[A-ZÀ-Ú][a-zà-ú]{2,}", principal["titulo"] + " " + principal["resumo"]))
    saida = []
    for it in pool:
        if it["link"] == principal["link"]:
            continue
        outra = palavras_chave(it["titulo"] + " " + it["resumo"])
        comuns = chave & outra
        nomes_comuns = {n for n in nomes if n.lower() in (it["titulo"] + " " + it["resumo"]).lower()}
        if len(nomes_comuns) >= 2 and len(comuns) >= 3:
            saida.append((len(comuns) + 2 * len(nomes_comuns), it))
    saida.sort(key=lambda x: -x[0])
    vistos, final = set(), []
    for _, it in saida:
        if it["titulo"] in vistos:
            continue
        vistos.add(it["titulo"])
        final.append(it)
    return final[:4]


def contexto_wikipedia(texto):
    """Um parágrafo de contexto da Wikipedia sobre o nome principal da notícia (CC BY-SA: usamos só os fatos)."""
    nomes = re.findall(r"\b([A-ZÀ-Ú][a-zà-ú]+(?:\s[A-ZÀ-Ú][a-zà-ú]+)+)", texto)
    for nome in nomes[:4]:
        try:
            q = urllib.parse.quote(nome.replace(" ", "_"))
            dados = json.loads(baixar(f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}"))
            if dados.get("type") == "standard" and dados.get("extract"):
                return {"veiculo": "Wikipedia (contexto)", "titulo": dados.get("title", nome), "resumo": dados["extract"][:900], "link": dados.get("content_urls", {}).get("desktop", {}).get("page", "")}
        except Exception:  # noqa: BLE001
            continue
    return None


PROMPT_SISTEMA = (
    "You are a news editor at Bylinguals, an English school in Brazil. You write short news stories for adult Brazilian learners of English. "
    "Write ONLY in English. Use ONLY facts that appear in the FACTS below. Never add names, numbers, dates, places, quotes or facts that are not in the FACTS. "
    "Background facts may only come from the BACKGROUND section. Write in your own words: never copy a sentence from the FACTS. "
    "Neutral, factual tone. No opinions, no adjectives that judge. If sources disagree, say what each source reports."
)


def pedir(fatos, longo, tentativa_extra=""):
    n_every, n_real = (7, 9) if longo else (6, 8)
    usuario = (
        f"{fatos}\n\nWrite a JSON object with exactly these keys:\n"
        '- "section": one of Brazil, World, Science, Health, Sports, Business, Culture, Space & Earth\n'
        '- "headline_everyday": a short headline (max 10 words), simple English\n'
        f'- "everyday_sentences": a list of EXACTLY {n_every} sentences for CEFR A2 learners. Each sentence is complete (subject + verb), 8 to 14 words, common words, simple present or simple past. Together they tell the story: what happened, who, where, when, why it matters.\n'
        '- "headline_real": a headline (max 12 words)\n'
        f'- "real_sentences": a list of EXACTLY {n_real} sentences for CEFR B1 learners, natural English, 12 to 22 words each: the main facts first, then what each source adds, then context from BACKGROUND (if any).\n'
        '- "glossary": a list of EXACTLY 8 objects {"word": an English word or expression that appears in real_sentences, "pt": its meaning in Brazilian Portuguese}\n'
        "Everything must be in English except the \"pt\" values. If a FACT is in Portuguese, translate it into English. "
        f"Do not repeat the same fact twice. Return only the JSON.{tentativa_extra}"
    )
    corpo = {
        "messages": [{"role": "system", "content": PROMPT_SISTEMA}, {"role": "user", "content": usuario}],
        "temperature": 0.3,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(API, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=3000) as r:
        resp = json.load(r)
    conteudo = resp["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", conteudo, re.S)
    try:
        dados = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        dados = {}
    for chave, lista in (("everyday", "everyday_sentences"), ("real", "real_sentences")):
        if isinstance(dados.get(lista), list):
            dados[chave] = " ".join(str(x).strip() for x in dados[lista] if str(x).strip())
    return dados, time.time() - t0, resp.get("usage", {})


COMUNS = set(
    "The A An I It In On At Of And But Or So If As For To By With From This That These Those He She They We You His Her Their Our "
    "Its There Here When Where What Who Why How Today Yesterday Tomorrow Monday Tuesday Wednesday Thursday Friday Saturday Sunday "
    "January February March April May June July August September October November December "
    "Brazil Brazilian Brazilians English Portuguese People Many Some More Most Also Now Then After Before During Last Next "
    "First Second Third One Two Three New However Meanwhile According Earlier Later Other Others".split()
)
PORTUGUES = re.compile(r"\b(não|são|está|também|após|chuvas|pessoas|governo|então|foram|ainda)\b", re.I)


def conferir(dados, fatos):
    corpo = f"{dados.get('everyday', '')} {dados.get('real', '')}"
    fonte_min = fatos.lower()
    numeros_fonte = {re.sub(r"[,.]", "", n) for n in re.findall(r"\d[\d,.]*", fatos)}
    problemas = []
    for n in re.findall(r"\d[\d,.]*", corpo):
        limpo = re.sub(r"[,.]", "", n.rstrip(".,"))
        if limpo and limpo not in numeros_fonte:
            problemas.append(f"número {n} não está nas fontes")
    for nome in set(re.findall(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-zà-ú]+(?:\s[A-Z][a-zà-ú]+)*)", corpo, re.M)):
        for p in nome.split():
            if p not in COMUNS and p.lower() not in fonte_min:
                problemas.append(f"nome '{p}' não está nas fontes")
    defeitos = []
    if PORTUGUES.search(corpo):
        defeitos.append("texto em português")
    gl = [g for g in dados.get("glossary", []) if isinstance(g, dict) and g.get("word") and g.get("pt")]
    if len(gl) < 4:
        defeitos.append("glossário vazio ou curto")
    if not dados.get("everyday") or not dados.get("real"):
        defeitos.append("faltou uma versão")
    if len(dados.get("everyday_sentences") or []) < (6 if len(fatos) < 2500 else 7) - 1 or len(dados.get("real_sentences") or []) < 7:
        defeitos.append("frases de menos")
    return sorted(set(problemas)), defeitos


def frases(texto):
    fs = [f for f in re.split(r"(?<=[.!?])\s+", str(texto).strip()) if f]
    return len(fs), (sum(len(f.split()) for f in fs) / len(fs)) if fs else 0


def escrever(fatos, longo):
    gasto_total, uso_total, tentativas = 0, {}, 0
    extra = ""
    dados, problemas, defeitos = {}, [], []
    for tentativas in range(1, 4):
        dados, gasto, uso = pedir(fatos, longo, extra)
        gasto_total += gasto
        uso_total = uso
        problemas, defeitos = conferir(dados, fatos)
        if not problemas and not defeitos:
            break
        extra = "\nIMPORTANT: your last answer had problems: " + "; ".join(defeitos + problemas) + ". Fix them: English only, only facts from FACTS/BACKGROUND, the exact number of sentences, 8 glossary items."
        print(f"    tentativa {tentativas}: {defeitos + problemas}")
    return dados, problemas, defeitos, round(gasto_total), uso_total, tentativas


def main():
    pool = []
    for veiculo, url in APOIO:
        pool += itens_do_feed(url, veiculo)
    historias = []
    for p in PRINCIPAIS:
        itens = itens_do_feed(p["feed"], p["nome"])
        pegas = 0
        for it in itens:
            if pegas >= p["quantas"]:
                break
            if len(it["resumo"].split()) < 8 or "/opinion/" in it["link"]:
                continue
            apoio = parecidas(it, pool)
            historias.append({"principal": it, "apoio": apoio, "secao": p["secao"]})
            pegas += 1
    # NASA: matéria inteira (domínio público).
    for it in itens_do_feed(NASA["feed"], "NASA")[:5]:
        try:
            texto = trafilatura.extract(baixar(it["link"])) or ""
        except Exception:  # noqa: BLE001
            continue
        if len(texto.split()) >= 200:
            historias.append({"principal": {**it, "resumo": " ".join(texto.split()[:900])}, "apoio": [], "secao": "Space & Earth", "nasa": True})
            break

    linhas = [f"# Piloto do Jornal v2 (The Bylinguals Daily): {MODELO}", ""]
    resultados = []
    for h in historias:
        pr = h["principal"]
        fontes = [pr] + h["apoio"]
        texto_base = " ".join(f"{f['titulo']} {f['resumo']}" for f in fontes)
        fundo = None if h.get("nasa") else contexto_wikipedia(pr["titulo"] + " " + pr["resumo"])
        fatos = "FACTS:\n" + "\n".join(f"- {f['veiculo']}: {f['titulo']}. {f['resumo']}" for f in fontes)
        if fundo:
            fatos += f"\n\nBACKGROUND (Wikipedia, {fundo['titulo']}): {fundo['resumo']}"
        print(f"Escrevendo: {pr['titulo']} ({len(h['apoio'])} de apoio, contexto: {bool(fundo)})")
        try:
            dados, problemas, defeitos, gasto, uso, tentativas = escrever(fatos, bool(h.get("nasa")))
        except Exception as erro:  # noqa: BLE001
            print(f"  falhou: {erro}")
            continue
        n1, m1 = frases(dados.get("everyday", ""))
        n2, m2 = frases(dados.get("real", ""))
        resultados.append({"historia": h, "fundo": fundo, "saida": dados, "problemas": problemas, "defeitos": defeitos, "segundos": gasto, "tentativas": tentativas})
        print(f"  {gasto} s em {tentativas} tentativa(s) · problemas: {problemas} · defeitos: {defeitos}")
        linhas += [
            f"## [{h['secao']}] {pr['titulo']}",
            f"Fonte principal: {pr['veiculo']} · {pr['link']}",
            "Fontes de apoio (só título e resumo do feed): " + ("; ".join(f"{a['veiculo']}: {a['titulo']}" for a in h["apoio"]) or "nenhuma"),
            f"Contexto: {fundo['titulo'] + ' (Wikipedia)' if fundo else 'nenhum'}",
            f"Tempo: {gasto} s · tentativas: {tentativas} · tokens: {uso}",
            f"Conferência: {'nenhum problema' if not problemas and not defeitos else '; '.join(defeitos + problemas)}",
            "",
            f"### Everyday English: {dados.get('headline_everyday', '')}",
            f"_{len(str(dados.get('everyday', '')).split())} palavras, {n1} frases, média {m1:.1f} palavras por frase_",
            "",
            str(dados.get("everyday", "")),
            "",
            f"### Real Conversations: {dados.get('headline_real', '')}",
            f"_{len(str(dados.get('real', '')).split())} palavras, {n2} frases, média {m2:.1f} palavras por frase_",
            "",
            str(dados.get("real", "")),
            "",
            "**Glossário:** " + "; ".join(f"{g.get('word')} = {g.get('pt')}" for g in dados.get("glossary", []) if isinstance(g, dict)),
            "",

            "<details><summary>Os fatos que a IA recebeu</summary>",
            "",
            fatos[:3000],
            "",
            "</details>",
            "",
        ]
    os.makedirs("piloto", exist_ok=True)
    with open("piloto/resultado.md", "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    with open("piloto/resultado.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=1, default=str)
    resumo = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo:
        with open(resumo, "a", encoding="utf-8") as f:
            f.write("\n".join(linhas))
    print(f"Feito: {len(resultados)} notícias")
    return 0 if resultados else 1


if __name__ == "__main__":
    sys.exit(main())
