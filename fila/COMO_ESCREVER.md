# Como escrever verbetes do Dicionário Bylinguals (para o Claude)

Fluxo: `exportar` reserva lemas e grava `fila/pendentes.json` -> Claude escreve `fila/verbetes/lote-NNN.json` -> ensaio
(`SO_CONFERIR=1`) -> corrige o que `fila/rejeitados.json` apontar -> `importar` manda ao Portal.

## O que está em `fila/pendentes.json`

```json
{ "reservadoEm": "...", "expiraEm": "...", "minutos": 360,
  "verbetes": [ { "id": "cm...", "lema": "deadline", "tipo": "PALAVRA|PHRASAL_VERB|IDIOM|EXPRESSAO",
                  "base": { "classes": ["noun"], "ipaUk": "...", "ipaUs": "...", "traducoes": ["prazo"], "sentidosEn": [{"classe":"noun","definicao":"...","exemplo":"..."}],
                            "sinonimos": [], "formas": ["deadlines"], "frequencia": 1234 } } ],
  "sugestoes": [ { "id": "...", "termo": "...", "contexto": "..." } ] }
```

A reserva vale `minutos` (360 = 6 h). Passou disso, o Portal devolve os lemas à fila e outra máquina pode pegá-los.
Cada lema gasta uma de 3 tentativas do Portal; reservar de novo os mesmos muitas vezes os tira da fila.

## Arquivo de entrega

`fila/verbetes/lote-001.json` = uma lista JSON, um objeto por lema reservado:

```json
[ { "id": "<id do pendentes.json>", "verbete": { ...verbete... } },
  { "id": "<outro id>", "verbete": null } ]
```

- `verbete: null` (ou omitido) = não escrevi este; solta a reserva no Portal.
- Para sugestões (`sugestoes` do pendentes) acrescente `"sugestao": true`.
- Para corrigir um rejeitado, escreva um arquivo de nome MAIOR (`lote-002-correcao.json`) com o mesmo `id`: para cada id vale o arquivo de nome maior.
- Ids já aceitos ficam em `fila/importados.json` e não são reenviados (`FORCAR=1` ignora).

## Esquema do verbete (o mesmo do Portal, `verbeteSchema`)

| campo | tipo | regra do Portal (recusa se violar) | padrão da casa |
|---|---|---|---|
| `conceito` | texto | obrigatório, até 700 | 1-2 frases curtas, até ~260, começa com maiúscula, min. 15 letras |
| `traducoes` | lista de texto | 1 a 10, cada uma até 80 | só PORTUGUÊS, a mais comum primeiro; nunca a palavra em inglês; até 6 |
| `nivel` | A1..C2 | opcional | nível CEFR em que se aprende a palavra |
| `registro` | `formal` `neutro` `informal` `gíria` `técnico` | opcional | `neutro` para o comum; palavra com frequência zipf >= 4 vira `neutro` por força da conferência |
| `areas` | lista | até 4, só estes valores: Negócios, Finanças, Contabilidade, Vendas, Marketing, Recursos Humanos, Tecnologia, Direito, Saúde, Engenharia, Indústria, Logística, Comércio exterior, Agronegócio, Educação, Turismo e hotelaria, Ciência, Comunicação | só se for termo de área profissional; até 3; senão `[]` |
| `sentidos` | lista | 1 a 8; cada: `classe` (<=30), `definicao` (obrig., <=400), `exemplo` (<=300), `exemploPt` (<=300) | até 3 sentidos reais, guiados por `base.sentidosEn`; definição curta em português + 1 exemplo + tradução; nunca invente sentido |
| `collocations` | lista | até 16 de `{expressao (<=80), traducao (<=120)}` | até 6, as mais frequentes no trabalho |
| `padroes` | lista | até 8 de `{padrao (<=100), exemplo, traducao}` | até 3, notação de professor ("verbo + -ing", "adjetivo + preposição") que USA a entrada |
| `frases` | lista | até 10 de `{en, pt}` (obrig., <=300) | até 4, frases prontas úteis no trabalho |
| `alternativas` | lista | até 8 de `{palavra, diferenca}` | até 3; `palavra` em INGLÊS parecida; `diferenca` em português, uma frase |
| `relacionados` | lista de texto | até 16, cada <=60 | até 8 palavras soltas em inglês do mesmo campo, sem repetir as collocations |
| `phrasalVerbs` | lista | até 12 de `{expressao (<=60), significado (<=200)}` | até 5, só os reais e atuais; `[]` se não houver |
| `idioms` | lista | até 10 de `{expressao (<=100), significado (<=250)}` | até 3; `[]` se não houver |
| `erroComum` | texto | opcional, até 500 | em português, UMA frase curta inteira terminada em ponto, com o certo e o errado (falso cognato, preposição, tradução literal, pronúncia); omita se não houver erro típico |
| `intencoes` | lista de texto | até 8, cada <=80 | até 4, em português, verbo no infinitivo + complemento ("cobrar um prazo") |

Todos os textos são aparados (`trim`) e não podem ser vazios. Campos fora desta tabela são ignorados pelo Portal (o importador avisa).
Coloque todas as chaves; use `[]` onde não houver conteúdo (o importador tira os vazios).

## Estilo da casa (extraído do prompt do robô antigo)

A Bylinguals é escola de inglês para profissionais brasileiros de empresas (reuniões, e-mails, apresentações, negociações,
clientes, relatórios, entrevistas, viagens a trabalho). Verbete CURTO e direto, foco no mundo das empresas.

- Português do Brasil nas explicações. Frases curtas. Nada de enrolação.
- Exemplos e frases em inglês do ambiente de trabalho (reunião, e-mail, cliente, projeto, prazo, equipe), naturais e atuais, com tradução. Se a palavra quase não aparece no trabalho, exemplo do dia a dia de um adulto.
- Com as suas palavras. Nunca copie definições de dicionários publicados.
- `conceito`: diga o que a palavra significa de verdade (não "marcador sintático").
- TODO exemplo, frase e collocation tem que CONTER a palavra da entrada (ou uma forma dela: plural, -s, -ed, -ing, forma irregular listada em `base.formas`), ser gramaticalmente correto e usá-la no sentido descrito. Não confunda com palavra parecida ("time" não é "team").
- O campo em inglês tem SÓ inglês: a tradução vai no campo de tradução, nunca entre parênteses nem como segunda frase.
- Phrasal verbs e idioms: só os reais e usados hoje, de preferência no trabalho.
- `registro` "neutro" para a maioria; "formal", "informal" ou "gíria" só quando a palavra é marcada assim no uso real; "técnico" só para termo de área.

## O que `conferir`/`arrumar` recusam (o importador recusa o verbete inteiro e diz o motivo em `fila/rejeitados.json`)

Hard (verbete recusado por inteiro):
- Formato inválido segundo a tabela acima (tamanho, enum, campo obrigatório vazio, `areas` fora da lista).
- `sem tradução em português`: todas as `traducoes` são iguais à entrada ou detectadas como inglês (wordfreq).
- `conceito curto demais`: menos de 15 letras.
- `sem sentidos` / `nenhum sentido com exemplo que use a palavra`: depois da limpeza, nenhum sentido tem `exemplo` que contenha a entrada.

Estrito (o robô antigo apagava em silêncio; o importador recusa para você reescrever; `ESTRITO=0` aceita o verbete já limpo):
- `erroComum` que não é frase inteira (mínimo 25 letras, termina em `.` `!` `?`) ou está em inglês.
- Tradução (`traducoes`) igual à entrada ou em inglês.
- `collocations[].expressao`, `frases[].en` ou `padroes[].exemplo` que não contêm a entrada (ou forma).
- `padroes` que repetem exemplos do enunciado ("suggest + -ing", "be good at + noun", "cobrar um prazo", "pedir desculpas"); `intencoes` idem.
- `alternativas[].palavra` igual à entrada ou em português; `relacionados` iguais à entrada ou em português.
- `sentidos[].exemplo` sem a entrada, ou com tradução colada (parênteses no fim / segunda frase em português): corte automático.
- Sentidos 2 e 3 cuja definição/`exemploPt` não tem relação com o campo das traduções/conceito/`base.traducoes` (compara os 4 primeiros caracteres das palavras): removidos. O 1º sentido sempre fica.
- Só avisos (não recusam): `registro` trocado para `neutro` (palavra comum), conceito/erroComum acima do tamanho da casa, campos desconhecidos.

Como a detecção de língua é estatística (wordfreq), termos curtos e nomes técnicos podem ser lidos errado: se um item correto for recusado, reescreva-o com uma palavra de apoio.

## Comandos

```
# ensaio local (sem rede, não posta nada; precisa de fila/pendentes.json):
SO_CONFERIR=1 python robo/dicionario.py importar     # lê fila/verbetes/*.json, grava fila/rejeitados.json

# reservar 300 lemas (Actions):
gh workflow run dicionario.yml -R othonmoraes0-cell/bylinguals-ia --ref <branch> -f modo=exportar -f teto=300

# mandar um lote (Actions) / só ensaiar no Actions:
gh workflow run dicionario.yml -R othonmoraes0-cell/bylinguals-ia --ref <branch> -f modo=importar
gh workflow run dicionario.yml -R othonmoraes0-cell/bylinguals-ia --ref <branch> -f modo=importar -f so_conferir=1
```

## Verbete modelo completo (passa na conferência; lema "deadline", base com `traducoes: ["prazo"]`)

```json
{
  "conceito": "Data ou hora limite para entregar uma tarefa, um relatório ou um projeto.",
  "traducoes": ["prazo", "data limite"],
  "nivel": "B1",
  "registro": "neutro",
  "areas": ["Negócios"],
  "sentidos": [
    {
      "classe": "noun",
      "definicao": "Data ou hora limite para terminar algo.",
      "exemplo": "The deadline for the report is Friday at noon.",
      "exemploPt": "O prazo do relatório é sexta-feira ao meio-dia."
    }
  ],
  "collocations": [
    { "expressao": "meet a deadline", "traducao": "cumprir um prazo" },
    { "expressao": "miss the deadline", "traducao": "perder o prazo" },
    { "expressao": "tight deadline", "traducao": "prazo apertado" }
  ],
  "padroes": [
    { "padrao": "deadline for + noun", "exemplo": "The deadline for the proposal is tomorrow.", "traducao": "O prazo da proposta é amanhã." }
  ],
  "frases": [
    { "en": "We missed the deadline by two days.", "pt": "Perdemos o prazo por dois dias." },
    { "en": "Can we extend the deadline?", "pt": "Podemos estender o prazo?" }
  ],
  "alternativas": [
    { "palavra": "due date", "diferenca": "Due date é a data marcada; deadline é o limite que não pode ser ultrapassado." }
  ],
  "relacionados": ["schedule", "milestone", "extension"],
  "phrasalVerbs": [],
  "idioms": [
    { "expressao": "beat the deadline", "significado": "Terminar antes do prazo." }
  ],
  "erroComum": "Brasileiros escrevem 'dead line' separado; o certo é 'deadline', uma palavra só.",
  "intencoes": ["cobrar um prazo da equipe", "pedir mais tempo para entregar"]
}
```
