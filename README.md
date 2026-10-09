# bylinguals-ia

Robô de IA do Portal Bylinguals (Bylinguals Club). Roda de graça no GitHub Actions deste repositório público.

**O que faz:** a cada ~15 minutos pergunta ao Portal se há trabalho na fila e, se houver:

- **Legenda de filme ou série** — ouve o vídeo com o [Whisper](https://github.com/SYSTRAN/faster-whisper) e devolve as falas em inglês com o tempo de cada uma.
- **Sincronia de audiobook** — ouve o capítulo (LibriVox ou áudio da escola) e devolve as falas; o Portal marca onde cada parágrafo do livro começa.

**O que NÃO tem aqui:** nenhum dado de aluno, nenhum texto de livro, nenhuma senha. O robô se identifica no Portal com o
token OIDC que o próprio GitHub assina para cada execução (o Portal só aceita tokens deste repositório). Os vídeos e
áudios são baixados só durante a execução e apagados com a máquina.

**Para rodar na hora:** aba *Actions* → *Robô de IA* → *Run workflow*.

**Endereço do Portal:** variável do repositório `SITE_URL` (padrão `https://www.bylinguals.com.br`).
