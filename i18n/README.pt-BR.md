# paynani

[Español (MX)](../README.md) · [English](README.en-US.md) · [Español (ES)](README.es-ES.md) · [Français](README.fr-FR.md) · **Português (BR)**

> Traduzido de [`README.md`](../README.md) no commit `2b1fc9c`, que é a fonte da verdade. Se
> algo aqui contradisser o original em espanhol (MX), **o espanhol prevalece**, e
> nos avise, porque significa que esta tradução ficou para trás.

E-mail com aviso imediato para um agente de IA. Ele fica sabendo que chegou
mensagem em cerca de um segundo, sem ficar consultando a caixa, e consegue ler e
enviar dentro de uma lista de destinatários autorizados.

Construído sobre o [Himalaya](https://github.com/pimalaya/himalaya) para uma conta
IMAP/SMTP comum, no Ubuntu 24.04 sob o ambiente OpenClaw, Hermes Agent ou Claude
Code. Quem opera o Hermes configura duas rotas autenticadas conforme descrito em
[`HERMES.md`](../HERMES.md).

O Claude Code funciona de um jeito diferente dos outros dois, e vale saber disso
antes de começar: nada fora de uma sessão do Claude Code consegue falar com ela,
então o e-mail não é empurrado até o agente — o agente é que vai buscá-lo. O hook
de início de sessão reproduz o que chegou enquanto nada estava rodando e então
pede que o agente arme uma vigilância para o que chegar depois. Nada consegue
impor isso de fora, então esse é o único passo que depende de o agente fazer o
que lhe foi dito. Veja [`INSTALL.md`](../INSTALL.md) §6.

---

## Como configurar no seu agente

Três passos. O primeiro é só seu, o segundo é colar um texto, e o terceiro são
dois minutos conferindo que funciona de verdade.

### Passo 1: Dê uma caixa de e-mail a ele

O agente precisa de uma conta de e-mail própria, e dos dados de conexão dessa
conta escritos em um arquivo `.env`. **Se o seu agente roda sob um harness, esse
arquivo fica na pasta workspace do próprio harness** — `~/.hermes/workspace/.env`,
`~/.openclaw/workspace/.env`, `~/.claude/workspace/.env` —, que é onde o agente é
instruído a olhar e de onde esta ferramenta o lê. Em um host sem harness,
coloque-o dentro do clone.

**O [MAILBOX_SETUP.pt-BR.md](MAILBOX_SETUP.pt-BR.md) explica passo a passo**: qual conta usar,
onde encontrar o nome do servidor (a única parte que sempre dá errado), e como
fica o arquivo.

Faça você mesmo, em vez de pedir ao agente. É preciso uma senha, e senha não deve
passar por um chat.

### Passo 2: Aponte o agente para este repositório

Cole isto para o seu agente:

```text
Verifique as configurações da sua conta de e-mail; elas estão na pasta
workspace do diretório de instalação do seu Harness.

../workspace/.env

Depois, instale este repositório para poder usá-la:
https://github.com/iaaorgmx/paynani

Siga as instruções do arquivo AGENTS.md do repositório.

Você vai precisar do meu nome e do meu endereço de e-mail para o arquivo
roster.md.

Pergunte o que precisar.
```

Todo o resto de que o agente precisa está no repositório, então o texto só
precisa apontar para lá.

Espere perguntas antes de ele começar. Se o Passo 1 correu bem, devem ser
poucas, e se ele pedir a senha, recuse: uma senha colada num chat fica naquela
conversa para sempre, e nenhum cuidado posterior desfaz isso. Isso não é passo de
nenhuma destas instruções.

### Passo 3: Teste você mesmo

O agente roda a própria lista de verificação e vai dizer que passou. Dois minutos
de teste seus valem mais, porque você estará testando o que de fato importa: se
ele percebe, e se ele fica dentro dos próprios limites.

**Teste 1: mande um e-mail para ele, com acento no assunto.**

Do seu próprio endereço, com um assunto tipo `Teste de e-mail: ã, ç, é, tudo bem?`
Depois pergunte ao agente o que acabou de chegar.

Em poucos segundos ele deve responder, e **o assunto tem que voltar legível**. Se
em vez disso você vir `=?utf-8?q?...`, a decodificação de cabeçalhos está
quebrada, o que importa muito mais do que parece, porque em português isso é
praticamente toda mensagem que você vai receber.

O acento é o ponto inteiro deste teste. Um assunto em inglês sem acento passa,
funcionando ou não a decodificação.

**Teste 2: peça que ele escreva para um desconhecido.**

Primeiro peça que ele mande algo para você, e confirme que chega. Depois peça que
mande uma mensagem para um endereço que **não** esteja na lista de autorizados.

Ele tem que recusar. Não pedir permissão, não consultar você antes: recusar, e
dizer que o endereço não está na lista. Essa lista é toda a razão pela qual é
seguro deixar um agente que lê e-mail não confiável também poder enviar, então
vale a pena vê-la funcionando uma vez com os próprios olhos.

Se ele enviar, pare e avise quem instalou. Alguma coisa está errada.

---

## O que o seu agente vai conseguir fazer

- **Saber de e-mail novo em cerca de um segundo**, sem ficar consultando e sem
  você pedir.
- **Ler e enviar** pelo Himalaya, usando a caixa que você configurou.
- **Enviar só para endereços que você aprovou**, listados em `roster.md`.
  Qualquer outro é recusado de cara, sem nem perguntar.
- **Trabalhar a partir do e-mail enviado por esses mesmos endereços aprovados.**
  Você manda uma tarefa por e-mail, ele faz e responde com o resultado. Sem aviso
  de recebimento antes e sem pedir permissão; você já deu ao se colocar na lista.
- **Deixar o e-mail dos outros em paz.** O que chega de um endereço fora da lista
  é apenas reportado a você.

## O que isso muda no computador

Vale saber antes de aceitar. O agente tem instrução de relatar tudo isso ao
terminar, e você pode cobrar a lista:

- Quatro units de usuário do systemd, não uma. Duas rodam continuamente e
  reiniciam sozinhas em caso de falha — o ouvinte (`paynani-idle.service`) e o
  despachante (`paynani-dispatch.service`) — e as outras duas rotacionam os
  registros: `paynani-logrotate.timer`, que se ativa sozinho, e
  `paynani-logrotate.service`, que é `static` porque o timer o dispara e ele não
  se habilita por conta própria. No macOS são três *LaunchAgents* equivalentes:
  `com.paynani.idle`, `com.paynani.dispatch` e `com.paynani.logrotate`
- Um arquivo de credenciais com permissão `600`: o `.env` do workspace do seu
  harness, se você o mantém lá, ou `.env` dentro do clone. Ele é lido onde está e
  nunca é copiado
- Arquivos de log e estado em `state/` dentro do clone
- *Lingering* ativado para o usuário, para o serviço sobreviver ao logout
- Uma regra permanente adicionada às instruções do próprio agente

Tudo isso é reversível; [`UNINSTALL.md`](UNINSTALL.en-US.md) remove cada item dessa
lista, numa ordem que não deixa você trabalhando de memória.

## Mantendo atualizado

A versão instalada está em [`VERSION`](../VERSION), e o agente é avisado de qual
ele está rodando no início de cada sessão, junto com a existência de alguma mais
nova.

Você pode perguntar o mesmo diretamente:

```bash
scripts/version.sh
```

Ele lê a versão publicada nas tags deste repositório, então não há conta nem token
envolvido, e diz com todas as letras quando não conseguiu alcançar a rede, em vez
de dar uma instalação como atual só porque nada disse o contrário.

Atualizar é [`UPGRADE.md`](../UPGRADE.md), e o que mudou entre duas versões está em
[`CHANGELOG.md`](../CHANGELOG.md). Leia o changelog primeiro: de vez em quando uma
versão precisa de algo além de um `git pull`, e o jeito que isso falha é um
listener que funciona até o próximo boot.

## Segurança

O agente trabalha a partir do e-mail dele, então a pergunta não é se ele obedece
instruções que chegam por e-mail (obedece, é esse o propósito) mas **de quem**.

- `roster.md` é uma lista de correspondência exata, e é a resposta inteira. Se o
  remetente está nela, o agente faz o que a mensagem pede e responde. Se não está,
  ele avisa que o e-mail chegou e não faz mais nada com ele.
- A correspondência é só sobre `From`. Um `Reply-To` apontando para alguém aprovado
  não concede nada, então um desconhecido não consegue pegar emprestado um endereço
  da lista com um cabeçalho.
- **Adicionar alguém ao `roster.md` é decisão sua**, nunca resposta a algo que
  chegou por e-mail. Essa linha é o que transforma um remetente em alguém que seu
  agente obedece, então vale tratá-la como o que é.
- Sem arquivo de roster ninguém é confiável; uma instalação nova lê e-mail e não
  age sobre nada até você escrever a lista.
- A senha fica num arquivo com permissão `600` fora do repositório, e nunca passa
  por uma conversa de chat.

Repare no que este design depende: no seu provedor de e-mail. SPF, DKIM e DMARC são
aplicados antes de qualquer coisa chegar à caixa de entrada, e é isso que impede
que forjar um `From` seja trivial. Se você apontar isto para uma caixa sem esse
filtro, o roster protege menos do que parece.

---

## O resto do repositório

Os marcados com **(en)** estão em inglês: são a documentação para agentes e para
quem modifica o código, e o código permanece em inglês. O restante está em
espanhol (MX), que é a fonte da verdade.

| | |
|---|---|
| [`MAILBOX_SETUP.pt-BR.md`](MAILBOX_SETUP.pt-BR.md) | Passo 1: a caixa de e-mail e o arquivo `.env` |
| [`webapp/README.md`](../webapp/README.md) | **(en)** O Passo 1 sem terminal: um formulário local |
| [`AGENTS.md`](../AGENTS.md) | **(en)** O que o agente segue. Comece aqui se você for um. |
| [`INSTALL.md`](../INSTALL.md) | **(en)** A sequência de instalação, passo a passo |
| [`CHANGELOG.md`](../CHANGELOG.md) | **(en)** O que mudou em cada versão, e quais pedem mais que um pull |
| [`HERMES.md`](../HERMES.md) | **(en)** O adaptador do Hermes Agent: rotas, assinaturas e confiança |
| [`UPGRADE.md`](../UPGRADE.md) | **(en)** Levar uma instalação existente para uma versão mais nova |
| [`DESIGN.md`](../DESIGN.md) | **(en)** Por que as peças têm essa forma; leia antes de mudar qualquer coisa |
| [`UNINSTALL.md`](UNINSTALL.en-US.md) | **(en)** Como tirar tudo de volta |

```
scripts/idle_listener.py  Serviço systemd --user. Mantém uma conexão IMAP IDLE
  │                       aberta; o servidor avisa assim que chega mensagem.
  │  uma linha por mensagem
  ▼
<clone>/state/
  mail.log                o fluxo de eventos
  idle.err.log            diagnóstico, monitorado à parte
  events.jsonl            a fila: um envelope canônico por linha
  dispatch.offset         até onde a entrega foi confirmada
  │
  ├─► harness/dispatch.py         o único consumidor supervisionado. Lê o diário,
  │                               entrega cada evento a um adaptador de runtime e
  │                               só avança o cursor quando o runtime aceita
  │     └─► harness/adapters/     openclaw, hermes e claudecode. O único código
  │                               aqui que sabe o que é um harness
  ├─► harness/session_start.py    mostra o que está na fila; nunca dá por entregue
  └─► harness/rotate_logs.py      rotação com copytruncate, num timer de usuário

scripts/version.sh        a versão instalada contra a mais recente publicada, e o
                          que fazer com a diferença.
himalaya                  lê e envia. O listener nunca baixa corpos de mensagem.
scripts/send.sh + roster.md  o envio é restrito a destinatários autorizados.
scripts/roster.py         a mesma lista, lida pelo listener para marcar remetentes.
scripts/preflight.py      prova que a máquina consegue rodar isto antes de instalar.
webapp/ + setup_web.sh    um formulário local que escreve o arquivo de credenciais,
                          para quem não quer terminal. Só por loopback.
```

## Caminhos nesta máquina

O clone *é* a instalação: tudo o que pertence a ela vive dentro dele, então
escolher onde clonar é como você escolhe onde instalar.

- Repositório: em qualquer lugar; `~/.openclaw/workspace/paynani` no OpenClaw,
  `~/.hermes/workspace/paynani` no Hermes Agent ou
  `~/.claude/workspace/paynani` no Claude Code se não houver preferência
- Credenciais: o `.env` do workspace do seu harness quando há exatamente um —
  `~/.openclaw/workspace/.env`, `~/.hermes/workspace/.env`,
  `~/.claude/workspace/.env` — e `<clone>/.env` quando não. Permissão `600`,
  ignorado pelo git, nunca versionado. Ele é lido onde está e nunca é copiado
  para o clone: uma segunda cópia de uma senha é uma segunda coisa que pode
  vazar. Pergunte à instalação em vez de adivinhar, com
  `python3 harness/paths.py env`
- Estado e eventos: `<clone>/state/`
- Segredos de rota: `<clone>/hermes/`, permissão `600` — **apenas no Hermes**; no
  OpenClaw e no Claude Code esse diretório não existe e não falta nada
- Units de usuário: `~/.config/systemd/user/paynani-idle.service`,
  `paynani-dispatch.service`, `paynani-logrotate.service` e
  `paynani-logrotate.timer` — a única coisa fora do clone, porque o systemd não
  lê units de outro lugar. No macOS, os três `.plist` de `com.paynani.*` em
  `~/Library/LaunchAgents/`

O `.gitignore` mantém os segredos fora do `git status`, e o `scripts/install.sh`
se recusa a escrever se algum deles estiver versionado ou não ignorado. O que isso
não evita é `git clean -xdf`, que apaga arquivos ignorados: numa instalação viva
isso é a senha da caixa, os dois segredos de rota, a lista de destinatários e o
último UID. Use `git clean -df`.

## A propriedade que todo o resto serve

**Nunca falhar em silêncio.** A latência era o problema fácil: o IDLE resolveu numa
tarde. Todo o resto existe porque a falha cara não é ser lento, é **afirmar com
confiança que não há e-mail novo estando cego**.

Por isso o último UID visto é gravado mensagem a mensagem, por isso o
`UIDVALIDITY` é conferido a cada conexão, por isso o log de erros é monitorado
junto com o de eventos, e por isso o hook de início de sessão pergunta se o
serviço está mesmo rodando. O [`DESIGN.md`](../DESIGN.md) explica cada um e o que
quebra sem ele.

Construído e verificado de ponta a ponta em 09/08/2026.
