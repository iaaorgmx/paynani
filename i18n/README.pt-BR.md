<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/paynani-horizontal-claro.svg">
    <img src="../brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

Mensageiro de elite: os paynani eram os corredores e mensageiros oficiais do Império Asteca.

[Español (MX)](../README.md) · [English (US)](README.en-US.md) · [Español (ES)](README.es-ES.md) · [Français (FR)](README.fr-FR.md) · **Português (BR)**

Paynani permite que o seu agente de IA leia automaticamente o próprio e-mail
poucos segundos depois de ele chegar, processe as mensagens recebidas e atenda às
instruções do e-mail como faria um colega humano.

Todos os e-mails recebidos são lidos, mas só se seguem as instruções dos e-mails
que vêm de uma lista de contatos autorizados. Essa lista quem escreve é você, e
ela mora num arquivo chamado `roster.md`.

Paynani foi construído sobre [Himalaya](https://github.com/pimalaya/himalaya) e
funciona com uma conta de e-mail comum, do mesmo tipo que você configuraria em
qualquer programa de e-mail.

**Usar é totalmente grátis!** Você não precisa contratar nenhum serviço adicional
para dar ao seu agente um endereço de e-mail que ele possa usar sozinho.

Roda no seu próprio computador ou servidor, dentro do programa que já hospeda o
seu agente. Esse programa anfitrião se chama *harness*, e é assim que a palavra é
usada no resto desta página. Atualmente o Paynani é usado por agentes de IA como
OpenClaw, Hermes Agent, Claude Code e OpenAI Codex.

Desenvolvido e testado em Linux (Ubuntu 24.04) e macOS (26.4.1).

Feito com amor por humanos e agentes de IA, do México para o mundo.

---

## Para quem é

Para quem quer dar ao seu agente um endereço de e-mail de verdade sem misturar
ali a caixa pessoal, as senhas ou as decisões de confiança.

Serve se você quer que o seu agente:

- receba tarefas por e-mail, suas ou do seu time;
- avise quando chegar algo que valha a pena olhar;
- responda da própria conta, não da sua;
- se recuse a obedecer, ou a escrever, a quem não estiver na sua lista.

Não serve para delegar o seu critério a qualquer mensagem que chegue. E-mail
qualquer um manda, então o Paynani trata tudo o que entra como não confiável até
que o remetente bata com a sua lista.

## Antes de começar

Você precisa de quatro coisas:

1. uma conta de e-mail dedicada ao agente, não o seu e-mail pessoal;
2. acesso a um terminal na máquina onde o seu agente roda;
3. um momento para escrever você mesmo a senha num arquivo, sem colar num chat;
4. seu nome e seu endereço de e-mail, para a lista de contatos autorizados.

Só isso. Não é preciso uma API de e-mail, nem um serviço no meio, nem conta nova
em lugar nenhum.

## Como configurar no seu agente

Três passos. O primeiro você faz sozinho, o segundo é colar um texto, e o
terceiro são dois minutos para conferir que funciona de verdade.

### Passo 1: dê a ele uma caixa de e-mail

O agente precisa da própria conta de e-mail, e dos dados de conexão dessa conta
escritos num arquivo chamado `.env`. **Se o seu agente roda sob um harness, esse
arquivo vai na pasta `workspace` do próprio harness**
(`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`,
`~/.claude/workspace/.env`, `~/.codex/workspace/.env`), que é onde se diz ao
agente para olhar e de onde esta ferramenta o lê. Sem harness, o arquivo pode
morar dentro da pasta do projeto. E se você não souber onde ele foi parar, dá
para perguntar à instalação com `python3 harness/paths.py env`.

**O [MAILBOX_SETUP.pt-BR.md](MAILBOX_SETUP.pt-BR.md) explica passo a passo**: que
conta usar, onde encontrar o nome do servidor (a parte que sempre falha) e como
fica o arquivo.

> [!CAUTION]
> Faça você, não peça ao agente. É preciso uma senha, e senha não deve passar por
> um chat: a que você cola numa conversa fica ali para sempre, e nenhum cuidado
> posterior desfaz isso. Se preferir não usar o terminal,
> `scripts/setup_web.sh` abre um formulário local que escreve o arquivo por você.

### Passo 2: aponte o agente para este repositório

Cole isto no seu agente:

```text
Revisa la configuración de tu
cuenta de correo electrónico;
está en la carpeta workspace del
directorio de instalación de tu
Harness.

../workspace/.env

Después, instala este
repositorio para poder usarla:
https://github.com/iaaorgmx/paynani

Sigue las instrucciones del
archivo AGENTS.md del
repositorio.

Vas a necesitar mi nombre y mi
dirección de correo electrónico
para el archivo roster.md.

Pregúntame lo que necesites.
```

Todo o resto de que o agente precisa está no repositório, então o texto só
precisa apontar para lá.

Espere perguntas antes de ele começar. Se o Passo 1 deu certo, devem ser poucas.
Se ele pedir a senha, diga não: isso não é um passo destas instruções.

### Passo 3: teste você mesmo

O agente roda a própria lista de verificação e vai dizer que passou. Dois minutos
de testes seus valem mais, porque você estaria testando o que de fato importa:
que ele perceba, e que fique dentro dos limites dele.

**Teste 1: mande um e-mail para ele, com acento no assunto.**

Do seu próprio endereço, com um assunto como
`Prueba de correo: ñ, á, ¿qué tal?` Depois pergunte ao agente o que acabou de
chegar.

Em uns dois segundos ele deve dizer, e **o assunto tem que aparecer legível**. Se
no lugar disso você vir `=?utf-8?q?...`, tem algo quebrado no jeito como ele lê
os cabeçalhos, e isso importa muito mais do que parece: se você trabalha em
português ou espanhol, é praticamente toda mensagem que vai receber.

O acento é todo o sentido deste teste. Um assunto em inglês sem acento passa,
funcionando ou não.

**Teste 2: peça que ele escreva para um desconhecido.**

Primeiro peça que ele mande algo para você, e confirme que chega. Depois peça que
mande uma mensagem para um endereço que **não** esteja na lista de autorizados.

Ele tem que se recusar. Não pedir permissão, não consultar você antes: recusar, e
dizer que aquele endereço não está na lista. Essa lista é toda a razão pela qual é
seguro deixar um agente que lê e-mail não confiável também poder enviar, então
vale a pena vê-la funcionar uma vez com os próprios olhos.

Se ele mandar, pare e avise quem instalou. Algo está errado.

## O que o seu agente vai conseguir fazer

- **Saber de e-mail novo em cerca de um segundo**, sem ficar checando e sem você
  pedir.
- **Ler e enviar** a partir da caixa que você configurou.
- **Enviar só para endereços que você aprovou**, os da sua lista. Qualquer outro é
  recusado de cara, sem nem perguntar.
- **Trabalhar com o e-mail que esses mesmos endereços aprovados mandam.** Você
  escreve uma tarefa, ele faz e responde por e-mail. Sem confirmação prévia e sem
  pedir permissão; você já deu ao se colocar na lista.
- **Deixar em paz o e-mail dos outros.** O que vem de um endereço fora da lista é
  relatado para você, e nada além disso.
- **Não perder o que chegou** se a máquina reiniciar no meio de uma tarefa. Cada
  mensagem detectada é anotada em disco antes de ser entregue.

## O que isso muda no computador

Vale saber antes de aceitar. O agente tem instruções de relatar tudo isso quando
terminar, e você pode cobrar a lista:

- **Dois serviços que ficam rodando o tempo todo** e reiniciam sozinhos se
  falharem: o que escuta a caixa e o que entrega as mensagens ao seu agente. São
  instalados como serviços do seu usuário, não do sistema.
- **Mais dois que só cuidam de aparar os registros** para que não cresçam sem fim.
- **Um arquivo com a senha da caixa**, legível só pelo seu usuário. É lido onde
  você deixou e nunca copiado para outro lugar.
- **Arquivos de registro e de estado** dentro da pasta do projeto.
- **Permissão para que esses serviços continuem vivos depois que você sai da
  sessão.**
- **Uma regra permanente acrescentada às instruções do próprio agente.**

Tudo isso é reversível; o [`UNINSTALL.md`](../UNINSTALL.md) remove cada ponto
dessa lista, numa ordem que não deixa você trabalhando de memória.

<details>
<summary>Os nomes exatos, se você precisar</summary>

Quatro unidades de usuário do systemd, não uma. Duas rodam o tempo todo e
reiniciam sozinhas se falharem: o ouvinte (`paynani-idle.service`) e o
distribuidor (`paynani-dispatch.service`). As outras duas rotacionam os
registros: `paynani-logrotate.timer`, que se ativa sozinho, e
`paynani-logrotate.service`, que é `static` porque quem o dispara é o
temporizador e ele não se habilita por conta própria. No macOS são três
*LaunchAgents* equivalentes: `com.paynani.idle`, `com.paynani.dispatch` e
`com.paynani.logrotate`.

O arquivo de credenciais leva permissões `600`: o `.env` do workspace do seu
harness se você guardar ali, e se não, `.env` dentro do clone. Os registros e o
estado moram em `state/`, dentro do clone. O *lingering* é o que mantém os
serviços vivos depois que você sai da sessão.

</details>

O `.gitignore` mantém os segredos fora do `git status` e o `scripts/install.sh`
se recusa a escrever se algum deles estiver versionado ou não ignorado. O que isso
não evita é o `git clean -xdf`, que apaga os arquivos ignorados: numa instalação
viva isso é a senha da caixa, os dois segredos de rota do Hermes
(`<clone>/hermes/`, só no Hermes), a lista de destinatários e a marca da última
mensagem vista. Use `git clean -df`.

## Segurança e limites

> [!WARNING]
> A sua lista de contatos autorizados decide de quem o seu agente aceita
> trabalho. Ela não prova quem é essa pessoa. Um e-mail de alguém que não está na
> lista é relatado para você, e para por aí.

O agente trabalha a partir do e-mail dele, então a pergunta não é se ele obedece a
instruções que chegam por e-mail. Obedece, esse é o ponto. A pergunta é **de
quem**.

- O `roster.md` é uma lista de correspondência exata, e é toda a resposta. Se o
  remetente está na lista, o agente faz o que a mensagem pede e responde. Se não
  está, ele avisa que o e-mail chegou e não faz mais nada com ele.
- A correspondência é sobre o remetente que a mensagem carrega, e só sobre esse.
  Um desconhecido não consegue tomar emprestado um endereço da sua lista
  colocando-o em outro campo.
- **Com uma exceção que você declara:** os *notificadores*. Se o seu time se
  coordena numa plataforma que manda e-mail em nome das pessoas (GitHub, Jira,
  Linear), você pode declarar o endereço dela e contra qual parte da sua lista
  conferir o autor. Aí aquela notificação conta como e-mail daquela pessoa.
  Declarar um notificador amplia a quem o seu agente dá ouvidos, igual a
  acrescentar uma linha, e se decide igual: nunca porque uma mensagem pediu.
- **Colocar alguém na lista é decisão sua**, nunca resposta a algo que chegou por
  e-mail. Essa linha é o que transforma um remetente em alguém a quem o seu agente
  obedece.
- Sem lista não há ninguém confiável. Uma instalação nova lê e-mail e não age
  sobre nada até você escrevê-la.

Vale saber em que tudo isso se apoia: o seu provedor de e-mail. Os filtros que
Gmail, Outlook e os demais aplicam são o que evita que falsificar um remetente
seja trivial, e eles agem antes de a mensagem chegar à caixa. Aponte o Paynani
para uma caixa sem essa filtragem e a lista protege menos do que parece.

## Como saber se está saudável

> [!IMPORTANT]
> Não haver mensagens pendentes não prova que o Paynani está saudável. Fica
> exatamente com essa cara quando ele parou de escutar.

Peça ao seu agente que rode a verificação de saúde e mostre a saída:

```bash
python3 scripts/healthcheck.py
```

Ela revisa os serviços, as credenciais, a fila de mensagens, a entrega ao seu
agente e a lista de autorizados. O que você quer ver é que os serviços estão
vivos, que nada está travado e que a configuração está sendo lida do lugar certo.
Se algo falhar, o relatório diz qual peça, não só que não há e-mail.

As opções longas e os modos de falha estão no [`INSTALL.md`](../INSTALL.md).

## Como é construído, em resumo

Um serviço mantém aberta uma conexão com o seu servidor de e-mail, do tipo em que
o servidor avisa sozinho assim que chega algo, sem ninguém ficar perguntando.
Quando uma mensagem chega, esse serviço a anota em disco antes de qualquer outra
coisa. Um segundo serviço lê essas anotações e as entrega ao seu agente, e só
marca uma como entregue quando o agente confirma que recebeu.

Essa separação é o que evita perder e-mail quando algo cai no meio do caminho. O
[`DESIGN.md`](../DESIGN.md) explica cada peça, por que ela é assim e o que quebra
sem ela.

## O que pertence a este repositório

Aqui moram a instalação, os dois serviços, os scripts de envio, a lista de
autorizados, os testes e a documentação de operação.

Aqui não moram a sua caixa, nem a sua senha, nem uma garantia de que quem escreve
é quem diz ser. Isso cabe ao seu provedor de e-mail, ao seu arquivo `.env` e ao
seu próprio critério sobre quem entra.

## Se você quiser..., leia...

| Se você quiser... | Leia |
|---|---|
| Preparar a caixa sem expor senhas | [`MAILBOX_SETUP.pt-BR.md`](MAILBOX_SETUP.pt-BR.md) |
| Instalar o Paynani | [`AGENTS.md`](../AGENTS.md) e [`INSTALL.md`](../INSTALL.md) |
| Integrar com o Hermes Agent | [`HERMES.md`](../HERMES.md) |
| Entender por que ele não deve falhar em silêncio | [`DESIGN.md`](../DESIGN.md) |
| Migrar do agenteiamail | [`MIGRATION.md`](../MIGRATION.md) |
| Remover o Paynani | [`UNINSTALL.md`](../UNINSTALL.md) |
| Ver mudanças por versão | [`CHANGELOG.md`](../CHANGELOG.md) |
| Autorizar remetentes | `roster.md` e [`roster.md.example`](../roster.md.example) |
| Enviar e-mail pela fronteira segura | [`scripts/send.sh`](../scripts/send.sh) |

## Mantendo atualizado

A versão instalada está em [`VERSION`](../VERSION), e ao agente se diz qual ele
está rodando no início de cada sessão, junto com se já saiu alguma mais nova.

Você pode perguntar o mesmo diretamente:

```bash
scripts/version.sh
```

Ele lê a versão publicada a partir das etiquetas deste repositório, então não há
conta nem token no meio, e avisa claramente quando não conseguiu alcançar a rede,
em vez de dar uma instalação como atualizada só porque nada disse o contrário.

Atualizar é o [`UPGRADE.md`](../UPGRADE.md), e o que mudou entre duas versões
está no [`CHANGELOG.md`](../CHANGELOG.md). Leia o changelog primeiro: de vez em
quando uma versão precisa de algo além de um `git pull`, e o jeito como pular
isso falha é um serviço que funciona até o próximo reinício.

## Idiomas

O `README.md` é a fonte em espanhol do México. As traduções mantidas são:

- [`i18n/README.en-US.md`](README.en-US.md);
- [`i18n/README.es-ES.md`](README.es-ES.md);
- [`i18n/README.fr-FR.md`](README.fr-FR.md);
- [`i18n/README.pt-BR.md`](README.pt-BR.md).

Não existe e não deve ser criado `i18n/README.es-MX.md`: a página fonte já é a
versão es-MX.

## A propriedade que todo o resto serve

**Nunca falhar em silêncio.** A latência era o problema fácil: foi resolvida numa
tarde assim que o servidor pôde avisar sozinho. Todo o resto existe porque a falha
cara não é ser lento, é **dizer com confiança que não há e-mail novo estando
cego**.

Por isso a última mensagem vista é guardada uma a uma, por isso cada conexão
confere se a caixa continua a mesma, por isso o registro de erros é vigiado junto
com o de eventos, e por isso ao iniciar uma sessão se pergunta se o serviço está
mesmo rodando. O [`DESIGN.md`](../DESIGN.md) explica cada um deles e o que quebra
sem ele.

Construído e verificado de ponta a ponta em 2026-08-09.

## De onde vem o nome

**paynani** é náuatle clássico e quer dizer, sem enfeite, *"aquele que corre
ligeiro"*: do verbo `paina` ("correr ligeramente", no vocabulário de Alonso de
Molina, 1571) mais o sufixo `-ni`, que transforma uma ação em quem a exerce como
ofício.

A grafia varia porque os frades do século XVI escreveram o náuatle com as
convenções do espanhol da época, em que `i`, `y` e `j` eram usados quase
indistintamente. O Gran Diccionario Náhuatl indexa as mesmas passagens do Códice
Florentino sob `painani` e sob `painanj`, e registra `payna` como variante de
`paina`: é a mesma palavra. Aqui se escreve `paynani`, que é a forma reconhecida
por um leitor de língua espanhola.

Foi dessa qualidade que veio o nome do ofício. O náuatle tinha dois modos de
nomear o mensageiro imperial: `titlantli`, "o enviado", que o define pela
incumbência que carrega, e `paynani`, que o define pelo modo como se move. O que
ficou colado a esses homens foi o segundo: eram conhecidos pelo jeito de correr,
não por quem os despachava.

Os corredores trabalhavam em revezamento, com postos chamados `techialoyan`, e
treinavam desde crianças. De tudo o que se conta sobre eles, há um detalhe que é
exatamente o que esta ferramenta faz: **o mensageiro classificava a notícia antes
de abrir a boca.** Se chegasse de cabelo solto e desgrenhado, trazia uma derrota,
e não recebia nem o cumprimento; se chegasse de cabelo trançado e fita colorida,
com escudo e clava, trazia uma vitória, e o povo o seguia até o palácio. É isso o
que a etiqueta `roster` faz aqui: o envelope diz como receber a notícia antes que
alguém a leia.

Da mesma raiz vem Paynal, aquele que corria no lugar de Huitzilopochtli nas
procissões. O Códice Florentino o explica em três palavras, *"o delegado, o
substituto, o suplente"*, porque "o apressavam, faziam-no correr". Um agente que
vai buscar o correio no lugar de quem não pode estar em toda parte.

<sub>Fontes: [Gran Diccionario Náhuatl](https://gdn.iib.unam.mx/diccionario/painani/233892)
(UNAM) · [Nahuatl Dictionary](https://nahuatl.wired-humanities.org/content/paina)
(Wired Humanities) · [Mexicolore](https://www.mexicolore.co.uk/aztecs/ask-experts/did-they-send-post-mail).</sub>

---

<sub>Traduzido de [`README.md`](../README.md), que é a fonte da verdade. Se algo aqui contradisser o original em espanhol (MX), **o espanhol prevalece**, e nos avise, porque significa que esta tradução ficou para trás.</sub>
