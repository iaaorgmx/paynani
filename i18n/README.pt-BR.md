<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/paynani-horizontal-claro.svg">
    <img src="../brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

[Español (MX)](../README.md) · [English (US)](README.en-US.md) · [Español (ES)](README.es-ES.md) · [Français (FR)](README.fr-FR.md) · **Português (BR)**

Paynani é uma ponte de e-mail para agentes de IA.

Ele dá ao seu agente uma caixa de e-mail própria, detecta mensagens novas em
segundos e entrega cada evento por uma rota supervisionada, sem perder mensagens
em silêncio e sem transformar qualquer e-mail em instrução autorizada.

Com Paynani, seu agente pode:

- saber quando chega e-mail novo;
- ler e responder a partir da própria caixa;
- agir apenas quando o remetente corresponde ao seu `roster.md`.

Paynani não substitui seu critério nem autentica magicamente quem escreve: ele
separa aviso de e-mail, autorização operacional e entrega ao runtime para que a
falha não seja silenciosa.

## Para quem é

Paynani é para pessoas que querem dar e-mail real a um agente de IA sem misturar
sua caixa pessoal, suas senhas nem suas decisões de confiança em uma conversa de
chat.

Use quando quiser que um agente:

- receba tarefas por e-mail;
- avise quando algo importante chegar;
- responda a partir da própria conta;
- recuse trabalho ou envios que não estejam em uma lista explícita de pessoas e
  notificadores autorizados.

Não serve para delegar critério humano a toda mensagem que chega. E-mail é entrada
não confiável; `roster.md` define quem pode criar trabalho.

## Antes de começar

Você precisa de três coisas:

1. uma caixa dedicada para o agente, não seu e-mail pessoal;
2. uma forma segura de escrever as credenciais em `.env`, sem colá-las no chat;
3. uma lista `roster.md` com as pessoas ou notificadores que podem criar trabalho.

> [!CAUTION]
> Nunca cole senhas de e-mail em um chat. Use `MAILBOX_SETUP.md` ou o formulário
> `scripts/setup_web.sh` para que o agente não veja segredos.

> [!WARNING]
> `roster.md` autoriza trabalho; não prova identidade criptográfica. E-mail não
> listado pode ser avisado, mas não deve virar tarefa.

> [!IMPORTANT]
> Uma fila vazia não prova que Paynani está saudável. `scripts/healthcheck.py`
> verifica listener, dispatcher, credenciais, runtime e cursor.

## Configure em três passos

O primeiro passo é seu, o segundo é colar uma instrução e o terceiro são dois
testes humanos. Os detalhes operacionais para o agente ficam em [`AGENTS.md`](../AGENTS.md),
[`INSTALL.md`](../INSTALL.md) e [`HERMES.md`](../HERMES.md).

### 1. Dê uma caixa de e-mail a ele

Crie uma conta de e-mail para o agente e escreva os dados de conexão dela em um
arquivo `.env`. Se seu agente roda sob um harness, esse `.env` fica no workspace
do harness (`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`,
`~/.claude/workspace/.env` ou `~/.codex/workspace/.env`). Em um host sem harness,
ele pode ficar dentro do clone.

[`MAILBOX_SETUP.pt-BR.md`](MAILBOX_SETUP.pt-BR.md) explica qual conta usar, onde
encontrar o servidor IMAP/SMTP e como escrever o arquivo sem expor a senha ao
agente.

Faça este passo você mesmo. Se o agente pedir a senha no chat, recuse.

### 2. Cole a instrução para o seu agente

Cole isto para o agente e delegue a instalação com limites claros:

```text
Verifique as configurações da
sua conta de e-mail; elas estão
na pasta workspace do diretório
de instalação do seu Harness.

../workspace/.env

Depois, instale este repositório
para poder usá-la:
https://github.com/iaaorgmx/paynani

Siga as instruções do arquivo
AGENTS.md do repositório.

Você vai precisar do meu nome e
do meu endereço de e-mail para o
arquivo roster.md.

Pergunte o que precisar.
```

O agente deve instalar a partir do repositório, pedir só os dados humanos que
faltarem e recusar receber segredos pelo chat.

### 3. Faça dois testes humanos

O agente executa sua própria verificação, mas estes dois testes validam o que você
precisa ver.

**Teste de acentos.** Envie um e-mail a partir do seu endereço autorizado com um
assunto como `Teste de e-mail: ã, ç, é, tudo bem?` e pergunte o que acabou de
chegar. Ele deve detectar a mensagem em segundos e mostrar o assunto legível, não
como `=?utf-8?q?...`.

**Teste de recusa.** Primeiro peça que ele mande um e-mail para você e confirme
que chega. Depois peça que escreva para um endereço que não está em `roster.md`.
Ele deve recusar de forma direta e dizer que o endereço não está autorizado.

Se qualquer teste falhar, pare e revise a instalação antes de usar a caixa para
trabalho real.

## O que seu agente pode fazer

Com Paynani configurado, seu agente pode:

- receber avisos de e-mail novo sem que você peça para verificar a caixa;
- ler mensagens a partir da própria conta;
- responder ou enviar e-mail com `scripts/send.sh` e o backend SMTP configurado;
- transformar em trabalho as mensagens que correspondem a `roster.md`;
- avisar sobre e-mail não autorizado sem obedecê-lo;
- conservar eventos em um journal para que uma reinicialização não apague trabalho pendente.

## Segurança e limites

Paynani separa três coisas que costumam ser confundidas:

| Coisa | O que significa |
|---|---|
| E-mail recebido | Há uma mensagem na caixa. |
| Correspondência em `roster.md` | Esse remetente ou notificador está autorizado a criar trabalho. |
| Identidade autenticada | Paynani não promete isso sozinho. Depende do provedor e de validações externas. |

Paynani é responsável por:

- entregar eventos de e-mail por uma rota observável;
- manter um cursor para não pular mensagens aceitas pelo runtime;
- separar notificação de autorização;
- recusar destinatários fora do roster a partir da fronteira segura de envio;
- expor verificações de saúde para instalação e operação.

Paynani não é responsável por:

- decidir se o conteúdo de um e-mail é verdadeiro;
- autenticar criptograficamente uma pessoa;
- proteger uma senha colada em um chat;
- substituir os controles de segurança do provedor de e-mail;
- transformar e-mail não listado em instrução operacional.

## Como saber se está saudável

Ver que não há mensagens pendentes não basta. Para verificar o sistema, execute:

```bash
python3 scripts/healthcheck.py
```

Essa verificação revisa credenciais, listener, dispatcher, runtime, journal e
cursor. Se precisar investigar uma instalação quebrada, siga [`INSTALL.md`](../INSTALL.md)
e [`HERMES.md`](../HERMES.md) antes de tocar em credenciais ou serviços.

## Como é construído, em resumo

```text
Caixa IMAP
   ↓
idle listener
   ↓ escreve evento durável
state/events.jsonl
   ↓ cursor
dispatcher
   ↓ adapter
Hermes / OpenClaw / Claude Code / Codex
```

O listener escuta a caixa e escreve eventos duráveis. O journal conserva o que
chegou. O dispatcher entrega cada evento e avança o cursor só quando o runtime o
aceita. O adapter traduz essa entrega para o harness que você usa.

[`DESIGN.md`](../DESIGN.md) explica por que Paynani é construído assim e quais
falhas busca evitar.

## O que pertence a este repositório

Este repositório contém a instalação, o listener, o dispatcher, os scripts de
envio, a configuração do roster, testes e documentação de operação.

Ele não contém sua caixa de e-mail, suas senhas nem uma garantia de identidade de
terceiros. Essas peças pertencem ao provedor de e-mail, ao seu `.env` local e às
suas próprias regras de confiança.

## Se você quer..., leia...

| Se você quer... | Leia |
|---|---|
| Preparar a caixa sem expor senhas | [`MAILBOX_SETUP.pt-BR.md`](MAILBOX_SETUP.pt-BR.md) |
| Instalar Paynani | [`AGENTS.md`](../AGENTS.md) e [`INSTALL.md`](../INSTALL.md) |
| Integrar com Hermes Agent | [`HERMES.md`](../HERMES.md) |
| Entender por que ele não deve falhar em silêncio | [`DESIGN.md`](../DESIGN.md) |
| Migrar de agenteiamail | [`MIGRATION.md`](../MIGRATION.md) |
| Ver mudanças por versão | [`CHANGELOG.md`](../CHANGELOG.md) |
| Autorizar remetentes | `roster.md` e [`roster.md.example`](../roster.md.example) |
| Enviar e-mail a partir da fronteira segura | [`scripts/send.sh`](../scripts/send.sh) |

## Idiomas e manutenção

`README.md` é a fonte em espanhol do México. As traduções mantidas são:

- [`i18n/README.en-US.md`](README.en-US.md);
- [`i18n/README.es-ES.md`](README.es-ES.md);
- [`i18n/README.fr-FR.md`](README.fr-FR.md);
- [`i18n/README.pt-BR.md`](README.pt-BR.md).

Não existe `i18n/README.es-MX.md` e ele não deve ser criado: o README raiz já é a
versão es-MX.

## De onde vem o nome

Os paynani eram corredores e mensageiros oficiais do Império Asteca. Este projeto
toma o nome dessa função: levar mensagens rapidamente, por uma rota clara, sem
perdê-las em silêncio.

Feito com amor por humanos e agentes de IA, do México para o mundo.
