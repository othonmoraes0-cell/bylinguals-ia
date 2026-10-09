"""
Robô de IA do Portal Bylinguals.

Pega tarefas na fila do Portal (legenda de vídeo ou sincronia de audiobook), ouve o áudio com o Whisper (faster-whisper,
no processador da máquina do GitHub) e devolve as falas com o tempo. Para de pegar tarefa nova depois de ~5 h, para
caber no limite de 6 h de uma execução do GitHub Actions; o que sobrar fica para a próxima rodada.
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


def fazer(t):
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


def teste(url):
    """Modo de teste (Run workflow com um link): transcreve 3 minutos e mostra, sem falar com o Portal."""
    with tempfile.TemporaryDirectory() as pasta:
        wav = os.path.join(pasta, "audio.wav")
        comeco = time.time()
        extrair_audio(url, {"ini": 0, "fim": 180}, wav)
        m = modelo("base.en")
        segmentos, info = m.transcribe(wav, language="en", beam_size=1, vad_filter=True, condition_on_previous_text=False)
        for s in segmentos:
            print(f"[{s.start:7.2f} → {s.end:7.2f}] {s.text.strip()}", flush=True)
        print(f"Teste: {info.duration:.0f} s de áudio em {time.time() - comeco:.0f} s.", flush=True)


def main():
    if os.environ.get("URL_DE_TESTE"):
        teste(os.environ["URL_DE_TESTE"])
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
            portal("POST", f"/api/robo/tarefas/{t['id']}/resultado", {"erro": str(e)[:1900]})
    print(f"Fim: {feitas} tarefa(s) feita(s).", flush=True)


if __name__ == "__main__":
    main()
