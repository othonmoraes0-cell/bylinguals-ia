# bylinguals-ia

Robô de IA do Portal Bylinguals (Bylinguals Club). Roda de graça no GitHub Actions deste repositório público.

**O que faz:** a cada ~15 minutos pergunta ao Portal se há trabalho na fila e, se houver:

- **Legenda de filme ou série** — ouve o vídeo com o [Whisper](https://github.com/SYSTRAN/faster-whisper) e devolve as falas em inglês com o tempo de cada uma.
- **Sincronia de audiobook** — ouve o capítulo (LibriVox ou áudio da escola) e devolve as falas; o Portal marca onde cada parágrafo do livro começa.
- **Guia de palavras** (livro ou vídeo) — traduz cada palavra escolhida pelo Portal e a frase onde ela aparece pela primeira vez, do inglês para o português do Brasil, com o modelo aberto [OPUS-MT](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-pt).

**O que NÃO tem aqui:** nenhum dado de aluno, nenhum texto de livro guardado (as palavras do guia e suas frases passam
pela máquina só durante a execução e não vão para o registro), nenhuma senha. O robô se identifica no Portal com o
token OIDC que o próprio GitHub assina para cada execução (o Portal só aceita tokens deste repositório). Os vídeos e
áudios são baixados só durante a execução e apagados com a máquina.

**Para rodar na hora:** aba *Actions* → *Robô de IA* → *Run workflow*. Os dois campos de teste (um link de áudio, ou
palavras separadas por `|`) só testam o robô e não mexem no Portal.

**Endereço do Portal:** variável do repositório `SITE_URL` (padrão `https://www.bylinguals.com.br`).
