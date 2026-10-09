"""
Robô de IA do Portal Bylinguals.

Pega tarefas na fila do Portal e faz no processador da máquina do GitHub, de graça:
 - legenda de vídeo e sincronia de audiobook: ouve o áudio com o Whisper (faster-whisper) e devolve as falas com o tempo;
 - guia de palavras (livro ou vídeo): traduz cada palavra e a frase onde ela aparece (inglês → português do Brasil,
   modelo aberto OPUS-MT da Universidade de Helsinque).
Para de pegar tarefa nova depois de ~5 h, para caber no limite de 6 h de uma execução do GitHub Actions; o que sobrar
fica para a próxima rodada.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

import requests
from faster_whisper import WhisperModel

SITE = os.environ.get("SITE_URL", "https://www.bylinguals.com.br").rstrip("/")
INICIO = time.time()
LIMITE_PARA_COMECAR = 5 * 3600
AGENTE = "BylingualsRobo/1.0 (+https://github.com/othonmoraes0-cell/bylinguals-ia)"


def token():
    """Token OIDC novo a cada chamada (vale poucos minutos)."""
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=bylinguals-portal"
    r = requests.get(url, headers={"Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]}, timeout=30)
    r.raise_for_status()
    return r.json()["value"]


def portal(metodo, caminho, corpo=None, tentativas=3):
    for i in range(tentativas):
        try:
            r = requests.request(metodo, SITE + caminho, json=corpo, headers={"Authorization": "Bearer " + token(), "User-Agent": AGENTE}, timeout=180)
            if r.status_code >= 500 and i < tentativas - 1:
                time.sleep(10 * (i + 1))
                continue
            return r
        except requests.RequestException:
            if i == tentativas - 1:
                raise
            time.sleep(10 * (i + 1))


MODELOS = {}


def modelo(nome):
    if nome not in MODELOS:
        print(f"Carregando o Whisper {nome}…", flush=True)
        MODELOS[nome] = WhisperModel(nome, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    return MODELOS[nome]


def extrair_audio(url, trecho, destino):
    """Baixa só o áudio, já em 16 kHz mono (o que o Whisper usa). Com trecho, só aquele pedaço."""
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-user_agent", AGENTE, "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "30"]
    if trecho:
        cmd += ["-ss", str(trecho["ini"]), "-to", str(trecho["fim"])]
    cmd += ["-i", url, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", destino]
    subprocess.run(cmd, check=True, timeout=3 * 3600)


def transcrever(id_tarefa, nome_modelo, arquivo, deslocamento):
    m = modelo(nome_modelo)
    segmentos, info = m.transcribe(
        arquivo,
        language="en",
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    falas = []
    ultimo_aviso = time.time()
    for s in segmentos:
        texto = " ".join(s.text.split()).strip()
        if texto and s.end > s.start:
            falas.append({"ini": round(s.start + deslocamento, 2), "fim": round(s.end + deslocamento, 2), "texto": texto[:600]})
        if time.time() - ultimo_aviso > 60 and info.duration:
            ultimo_aviso = time.time()
            fracao = min(0.99, s.end / info.duration)
            print(f"  {fracao:.0%} ({len(falas)} falas)", flush=True)
            try:
                portal("POST", f"/api/robo/tarefas/{id_tarefa}/progresso", {"fracao": fracao}, tentativas=1)
            except Exception:
                pass
    return falas, info.duration


def aviso(texto):
    """Aparece no resumo da execução no GitHub (fácil de conferir sem abrir o registro)."""
    print(f"::notice title=Robô::{texto[:900]}", flush=True)


# ---------------------------------------------------------------- tradução (guia de palavras)

MODELO_DE_TRADUCAO = "Helsinki-NLP/opus-mt-tc-big-en-pt"
TRADUTOR = {}


def tradutor():
    """Instala (só na primeira vez que aparece um guia) e carrega o tradutor inglês → português."""
    if "m" not in TRADUTOR:
        try:
            import transformers  # noqa: F401
        except ImportError:
            print("Instalando o tradutor…", flush=True)
            pasta = os.path.dirname(os.path.abspath(__file__))
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "torch==2.5.1", "--index-url", "https://download.pytorch.org/whl/cpu"], check=True)
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", os.path.join(pasta, "requirements-traducao.txt")], check=True)
        import torch
        from transformers import MarianMTModel, MarianTokenizer

        torch.set_num_threads(os.cpu_count() or 4)
        print(f"Carregando o tradutor {MODELO_DE_TRADUCAO}…", flush=True)
        tok = MarianTokenizer.from_pretrained(MODELO_DE_TRADUCAO)
        mod = MarianMTModel.from_pretrained(MODELO_DE_TRADUCAO).eval()
        vocab = tok.get_vocab()
        # Modelo com vários destinos: >>pob<< é o português do Brasil; >>por<< o europeu.
        prefixo = next((p for p in (">>pob<<", ">>por<<", ">>pt_br<<", ">>pt<<") if p in vocab), "")
        TRADUTOR.update(m=mod, tok=tok, prefixo=prefixo, torch=torch)
    return TRADUTOR


def traduzir(textos, lote=16, maximo=256, ao_progredir=None):
    t = tradutor()
    saida = []
    for i in range(0, len(textos), lote):
        pedaco = [(t["prefixo"] + " " + x).strip() for x in textos[i : i + lote]]
        entrada = t["tok"](pedaco, return_tensors="pt", padding=True, truncation=True, max_length=maximo)
        with t["torch"].inference_mode():
            gerado = t["m"].generate(**entrada, num_beams=2, max_new_tokens=maximo)
        saida += [x.strip() for x in t["tok"].batch_decode(gerado, skip_special_tokens=True)]
        if ao_progredir:
            ao_progredir(len(saida))
    return saida


def traducao_da_palavra(palavra, traducao):
    """Deixa a tradução com cara de verbete: sem ponto final e em minúscula quando a palavra também é."""
    traducao = traducao.strip().strip("\"'“”").rstrip(".!?;:,").strip()
    if palavra[:1].islower() and traducao[:1].isupper() and not traducao[1:2].isupper():
        traducao = traducao[:1].lower() + traducao[1:]
    return traducao


def fazer_guia(t):
    palavras = t.get("palavras") or []
    print(f"Tarefa {t['id']}: {t['tipo']} — {len(palavras)} palavras", flush=True)
    if not palavras:
        raise RuntimeError("Não veio nenhuma palavra para o guia.")
    comeco = time.time()
    frases = list(dict.fromkeys(p["frase"] for p in palavras if p.get("frase")))
    total = len(palavras) + len(frases)
    marca = {"em": time.time()}

    def progresso(feitas_antes):
        def f(n):
            if time.time() - marca["em"] > 45:
                marca["em"] = time.time()
                fracao = min(0.99, (feitas_antes + n) / total)
                print(f"  {fracao:.0%}", flush=True)
                try:
                    portal("POST", f"/api/robo/tarefas/{t['id']}/progresso", {"fracao": fracao}, tentativas=1)
                except Exception:
                    pass

        return f

    termos = traduzir([p["palavra"] for p in palavras], lote=32, maximo=24, ao_progredir=progresso(0))
    print(f"  {len(termos)} palavras traduzidas em {time.time() - comeco:.0f} s", flush=True)
    frases_pt = dict(zip(frases, traduzir(frases, ao_progredir=progresso(len(palavras)))))
    print(f"  {len(frases)} frases traduzidas em {time.time() - comeco:.0f} s", flush=True)
    traducoes = []
    for p, tr in zip(palavras, termos):
        tr = traducao_da_palavra(p["palavra"], tr)[:200]
        if not tr:
            continue
        item = {"termo": p["palavra"][:60], "capitulo": int(p.get("capitulo") or 0), "traducao": tr}
        if p.get("frase") and frases_pt.get(p["frase"]):
            item["frase"] = frases_pt[p["frase"]][:1200]
        traducoes.append(item)
    r = portal("POST", f"/api/robo/tarefas/{t['id']}/resultado", {"traducoes": traducoes})
    print(f"  Portal: HTTP {r.status_code} {r.text[:300]}", flush=True)
    aviso(f"{t['tipo']} {t['id']}: {len(traducoes)} traduções em {time.time() - comeco:.0f} s → Portal HTTP {r.status_code} {r.text[:200]}")


def teste_traducao(texto):
    """Modo de teste (Run workflow com palavras): traduz e mostra, sem falar com o Portal."""
    comeco = time.time()
    itens = [x.strip() for x in texto.split("|") if x.strip()]
    saida = traduzir(itens)
    pares = [f"{a} → {traducao_da_palavra(a, b) if ' ' not in a else b}" for a, b in zip(itens, saida)]
    for x in pares:
        print(x, flush=True)
    print(f"::notice title=Teste do tradutor::({TRADUTOR.get('prefixo') or 'sem prefixo'}; {time.time() - comeco:.0f} s) " + " ; ".join(pares)[:3500], flush=True)


# ---------------------------------------------------------------- tarefas


def fazer(t):
    if t.get("tipo", "").startswith("GUIA_"):
        fazer_guia(t)
        return
    print(f"Tarefa {t['id']}: {t['tipo']} — {t.get('descricao', '')}", flush=True)
    with tempfile.TemporaryDirectory() as pasta:
        wav = os.path.join(pasta, "audio.wav")
        comeco = time.time()
        extrair_audio(t["url"], t.get("trecho"), wav)
        print(f"  áudio pronto em {time.time() - comeco:.0f} s", flush=True)
        deslocamento = (t.get("trecho") or {}).get("ini", 0)
        falas, duracao = transcrever(t["id"], t.get("modelo", "base.en"), wav, deslocamento)
        print(f"  {len(falas)} falas em {time.time() - comeco:.0f} s", flush=True)
        if not falas:
            raise RuntimeError("Não ouvi fala em inglês neste áudio.")
        total = (duracao or 0) + deslocamento
        r = portal("POST", f"/api/robo/tarefas/{t['id']}/resultado", {"falas": falas[:30000], "duracao": round(total, 1)})
        print(f"  Portal: HTTP {r.status_code} {r.text[:300]}", flush=True)
        aviso(f"{t['tipo']} {t['id']}: {len(falas)} falas em {time.time() - comeco:.0f} s → Portal HTTP {r.status_code} {r.text[:200]}")


def teste(url):
    """Modo de teste (Run workflow com um link): transcreve 3 minutos e mostra, sem falar com o Portal."""
    with tempfile.TemporaryDirectory() as pasta:
        wav = os.path.join(pasta, "audio.wav")
        comeco = time.time()
        extrair_audio(url, {"ini": 0, "fim": 180}, wav)
        m = modelo("base.en")
        segmentos, info = m.transcribe(wav, language="en", beam_size=1, vad_filter=True, condition_on_previous_text=False)
        linhas = []
        for s in segmentos:
            linhas.append(s.text.strip())
            print(f"[{s.start:7.2f} → {s.end:7.2f}] {s.text.strip()}", flush=True)
        resumo = f"{len(linhas)} falas; {info.duration:.0f} s de áudio em {time.time() - comeco:.0f} s. Começo: {' '.join(linhas[:3])[:300]}"
        print(f"::notice title=Teste do robô::{resumo}", flush=True)


def main():
    if os.environ.get("URL_DE_TESTE"):
        teste(os.environ["URL_DE_TESTE"])
        return
    if os.environ.get("TRADUCAO_DE_TESTE"):
        teste_traducao(os.environ["TRADUCAO_DE_TESTE"])
        return
    feitas = 0
    while time.time() - INICIO < LIMITE_PARA_COMECAR:
        r = portal("POST", "/api/robo/tarefas/proxima")
        if r.status_code != 200:
            print(f"O Portal recusou: HTTP {r.status_code} {r.text[:300]}", flush=True)
            sys.exit(1)
        d = r.json()
        if d.get("vazio"):
            break
        t = d["tarefa"]
        try:
            fazer(t)
            feitas += 1
        except Exception as e:  # uma tarefa que falha não derruba o robô
            print(f"  ERRO: {e}", flush=True)
            aviso(f"ERRO em {t.get('tipo')} {t.get('id')}: {e}")
            portal("POST", f"/api/robo/tarefas/{t['id']}/resultado", {"erro": str(e)[:1900]})
    print(f"Fim: {feitas} tarefa(s) feita(s).", flush=True)


if __name__ == "__main__":
    main()
