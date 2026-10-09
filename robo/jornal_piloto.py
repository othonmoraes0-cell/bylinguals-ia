"""
Piloto do Jornal do Club (09/10/2026): dá para escrever notícias em inglês, em 2 níveis, com IA grátis?

Roda só no GitHub Actions (repositório público, minutos grátis), com um modelo aberto no processador (llama.cpp).
Não mexe no Portal: lê notícias de fontes abertas (licença CC BY ou domínio público), escreve as versões e grava um
relatório (Markdown + JSON) como artefato da execução, para a equipe ler e decidir.

Conferência automática do "não inventar": todo número e todo nome próprio do texto escrito precisa aparecer na fonte.
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

import trafilatura

API = os.environ.get("LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODELO = os.environ.get("MODELO_ROTULO", "modelo")
QUANTAS = int(os.environ.get("QUANTAS", "4"))
UA = {"User-Agent": "Mozilla/5.0 (Bylinguals robo; piloto do jornal)"}

FONTES = [
    {"nome": "Agência Brasil (EN)", "licenca": "CC BY (Agência Brasil/EBC)", "feeds": ["https://agenciabrasil.ebc.com.br/en/rss/ultimasnoticias/feed.xml", "https://agenciabrasil.ebc.com.br/en/rss/geral/feed.xml"], "pagina": "https://agenciabrasil.ebc.com.br/en", "padrao": r'href="(/en/[a-z-]+/noticia/\d{4}-\d{2}/[^"]+)"'},
    {"nome": "Global Voices", "licenca": "CC BY 3.0 (Global Voices)", "feeds": ["https://globalvoices.org/feed/"]},
    {"nome": "NASA", "licenca": "Domínio público (NASA)", "feeds": ["https://www.nasa.gov/news-release/feed/"]},
    {"nome": "VOA Learning English", "licenca": "Domínio público (VOA), exceto AP/Reuters/AFP", "feeds": ["https://learningenglish.voanews.com/api/zkm-qem$-o", "https://learningenglish.voanews.com/api/"]},
]


def baixar(url, limite=3_000_000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read(limite).decode("utf-8", "replace")


def itens_do_feed(xml_texto):
    itens = []
    try:
        raiz = ET.fromstring(xml_texto.encode("utf-8"))
    except ET.ParseError:
        return itens
    for it in raiz.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        titulo = link = ""
        for f in it:
            t = f.tag.split("}")[-1]
            if t == "title":
                titulo = (f.text or "").strip()
            elif t == "link":
                link = (f.text or f.get("href") or "").strip()
        if titulo and link:
            itens.append({"titulo": html.unescape(titulo), "link": link})
    return itens


def candidatos(fonte):
    for url in fonte.get("feeds", []):
        try:
            itens = itens_do_feed(baixar(url))
            if itens:
                print(f"  feed ok: {url} ({len(itens)} itens)")
                return itens
            print(f"  feed vazio: {url}")
        except Exception as e:  # noqa: BLE001
            print(f"  feed falhou: {url}: {e}")
    if fonte.get("pagina"):
        try:
            pag = baixar(fonte["pagina"])
            links = list(dict.fromkeys(re.findall(fonte["padrao"], pag)))
            print(f"  página: {len(links)} links")
            return [{"titulo": "", "link": "https://agenciabrasil.ebc.com.br" + l} for l in links]
        except Exception as e:  # noqa: BLE001
            print(f"  página falhou: {e}")
    return []


def texto_da_materia(link):
    bruto = baixar(link)
    texto = trafilatura.extract(bruto, include_comments=False, include_tables=False) or ""
    meta = trafilatura.extract_metadata(bruto)
    titulo = (meta.title if meta else "") or ""
    return titulo, texto.strip()


PROMPT_SISTEMA = (
    "You are a news editor at Bylinguals, an English school in Brazil. You rewrite news for adult Brazilian learners of English. "
    "Use ONLY facts that are stated in the SOURCE. Never add names, numbers, dates, places, quotes or facts that are not in the SOURCE. "
    "If something is unclear, leave it out. Neutral, factual tone. No opinions."
)


def pedir(fonte_nome, texto):
    palavras = texto.split()
    corte = " ".join(palavras[:1100])
    usuario = (
        f"SOURCE (from {fonte_nome}):\n\"\"\"\n{corte}\n\"\"\"\n\n"
        "Write a JSON object with exactly these keys:\n"
        '- "section": one of Brazil, World, Science & Tech, Sports, Business, Culture, Health, Environment\n'
        '- "headline_everyday": a short headline (max 10 words), simple English\n'
        '- "everyday": the news in 110 to 160 words, CEFR A2 level: short sentences (max 15 words), common words, simple present and simple past\n'
        '- "headline_real": a headline (max 12 words)\n'
        '- "real": the news in 180 to 250 words, CEFR B1 level, natural English, with the main facts and context from the SOURCE\n'
        '- "glossary": a list of 8 objects {"word": English word or expression used in "real", "pt": short meaning in Brazilian Portuguese}\n'
        "Return only the JSON."
    )
    corpo = {
        "messages": [{"role": "system", "content": PROMPT_SISTEMA}, {"role": "user", "content": usuario}],
        "temperature": 0.3,
        "max_tokens": 1300,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(API, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=3000) as r:
        resp = json.load(r)
    gasto = time.time() - t0
    conteudo = resp["choices"][0]["message"]["content"]
    uso = resp.get("usage", {})
    m = re.search(r"\{.*\}", conteudo, re.S)
    dados = json.loads(m.group(0)) if m else {}
    return dados, gasto, uso, conteudo


COMUNS = set(
    "The A An I It In On At Of And But Or So If As For To By With From This That These Those He She They We You His Her Their Our "
    "Its There Here When Where What Who Why How Today Yesterday Tomorrow Monday Tuesday Wednesday Thursday Friday Saturday Sunday "
    "Brazil Brazilian Brazilians English Portuguese Everyday Real People Many Some More Most Also Now Then After Before During Last Next "
    "First Second Third One Two Three New".split()
)


def conferir(saida, fonte):
    fonte_min = fonte.lower()
    numeros_fonte = {re.sub(r"[,.]", "", n) for n in re.findall(r"\d[\d,.]*", fonte)}
    problemas = []
    for n in re.findall(r"\d[\d,.]*", saida):
        limpo = re.sub(r"[,.]", "", n.rstrip(".,"))
        if limpo and limpo not in numeros_fonte:
            problemas.append(f"número {n} não está na fonte")
    for nome in set(re.findall(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-zà-ú]+(?:\s[A-Z][a-zà-ú]+)*)", saida, re.M)):
        partes = [p for p in nome.split() if p not in COMUNS]
        for p in partes:
            if p.lower() not in fonte_min:
                problemas.append(f"nome '{p}' não está na fonte")
    return sorted(set(problemas))


def frases(texto):
    fs = [f for f in re.split(r"(?<=[.!?])\s+", texto.strip()) if f]
    return len(fs), (sum(len(f.split()) for f in fs) / len(fs)) if fs else 0


def main():
    escolhidas = []
    for fonte in FONTES:
        print(f"Fonte: {fonte['nome']}")
        for c in candidatos(fonte)[:6]:
            try:
                titulo, texto = texto_da_materia(c["link"])
            except Exception as e:  # noqa: BLE001
                print(f"  matéria falhou: {c['link']}: {e}")
                continue
            if len(texto.split()) < 180:
                print(f"  curta demais ({len(texto.split())} palavras): {c['link']}")
                continue
            escolhidas.append({"fonte": fonte["nome"], "licenca": fonte["licenca"], "link": c["link"], "titulo": c["titulo"] or titulo, "texto": texto})
            print(f"  escolhida: {c['titulo'] or titulo} ({len(texto.split())} palavras)")
            break
        if len(escolhidas) >= QUANTAS:
            break

    linhas = [f"# Piloto do Jornal: {MODELO}", ""]
    resultados = []
    for e in escolhidas:
        print(f"Escrevendo: {e['titulo']}")
        try:
            dados, gasto, uso, bruto = pedir(e["fonte"], e["texto"])
        except Exception as erro:  # noqa: BLE001
            print(f"  falhou: {erro}")
            linhas += [f"## {e['titulo']}", f"Falhou: {erro}", ""]
            continue
        saida = " ".join(str(dados.get(k, "")) for k in ("headline_everyday", "everyday", "headline_real", "real"))
        problemas = conferir(saida, e["texto"] + " " + e["titulo"])
        n1, m1 = frases(str(dados.get("everyday", "")))
        n2, m2 = frases(str(dados.get("real", "")))
        r = {**e, "texto": e["texto"][:1500], "saida": dados, "segundos": round(gasto), "uso": uso, "problemas": problemas, "bruto": bruto if not dados else ""}
        resultados.append(r)
        print(f"  {round(gasto)} s · problemas: {len(problemas)}")
        linhas += [
            f"## {e['titulo']}",
            f"Fonte: {e['fonte']} · {e['licenca']} · {e['link']}",
            f"Tempo: {round(gasto)} s · tokens: {uso}",
            f"Conferência (números e nomes que não estão na fonte): {'nenhum problema' if not problemas else '; '.join(problemas)}",
            "",
            f"**Seção:** {dados.get('section', '?')}",
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
            "<details><summary>Começo da fonte</summary>",
            "",
            e["texto"][:1200],
            "",
            "</details>",
            "",
        ]
    os.makedirs("piloto", exist_ok=True)
    with open("piloto/resultado.md", "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    with open("piloto/resultado.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=1)
    resumo = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo:
        with open(resumo, "a", encoding="utf-8") as f:
            f.write("\n".join(linhas))
    print(f"Feito: {len(resultados)} matérias")
    return 0 if resultados else 1


if __name__ == "__main__":
    sys.exit(main())
