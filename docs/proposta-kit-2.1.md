# Kit 2.1: le cuciture

Proposta dell'8 novembre 2026, scritta dopo la fusione di tre release sviluppate in parallelo da
sessioni diverse (1.6, 1.7, 1.8/1.8.1 → 1.9.0) e un'analisi a cinque lenti della repo, ognuna
affidata a un agente a contesto fresco e in sola lettura:

- **A, codice**: hook, script, mod e watchdog, con sonde in repo di prova (spazi nei percorsi, repo
  senza commit, worktree, 40k file) e il contratto degli hook verificato sulla documentazione;
- **B, prosa**: tutte le skill, gli agenti e le righe che gli hook iniettano, cercando contraddizioni
  fra file scritti da sessioni diverse e affermazioni su Claude Code non vere per la 2.1.319;
- **C, stato dell'arte**: changelog 2.1.314–2.1.319, pagine di documentazione cambiate, post
  Anthropic, harness nuovi o aggiornati, evidenze misurate, lo stack dei progetti;
- **D, test ed eval**: copertura misurata con un tracer, qualità delle asserzioni, eval mancanti, CI;
- **E, uso**: il kit percorso come lo percorre il proprietario, dall'installazione al nightly.

I cinque rapporti integrali sono in [analisi-2026-11-08/](analisi-2026-11-08/). Questo documento li
sintetizza in pacchetti, con un'opzione consigliata e il costo (S = meno di un'ora con test, M = un
pomeriggio, L = un giorno o più). Nulla di quanto segue è implementato: si decide prima.

## In breve

Il kit regge: i 17 file di test passano anche su Python 3.9, ogni hook rispetta il contratto della
documentazione, il costo sul percorso caldo è misurato e limitato (0,18 s per comando Bash su una
repo da 60k file), la cartella items e le card reggono scritture concorrenti. I difetti stanno **alle
cuciture** che il proprietario attraversa più spesso: un worktree, una seconda macchina o una
sessione cloud, un kit.json scritto a mano, tre release unite lo stesso giorno.

Quattro difetti fanno sbagliare il kit oggi, tutti verificati con una sonda e riverificati a mano:

1. **Il REPORT.md di un thread in worktree non viene mai archiviato.** `subagent_stop.py:282` cerca
   l'item nella `cwd` dell'hook, che per un thread con `isolation: "worktree"` (il default) è il
   worktree, dove `.claude/lead/` non esiste. `subagent_start.py:36` fa già la mappatura worktree →
   checkout principale per le lezioni; qui manca. Ogni thread lascia una cartella vuota e resta
   `working` per sempre nella lista. Anche l'evidenza del gate finisce nel worktree e muore con esso.
2. **Quando il REPORT.md viene archiviato, contiene la frase di chiusura e non il report.**
   `subagent_stop.py:287-293` preferisce `last_assistant_message` al testo consegnato con
   SubagentHandback; la documentazione degli hook dice il contrario ("the closing text, not the
   delivered report"). Sonda: REPORT.md = "Report delivered to the coordinator.", LOG "no status
   line". Il percorso del verifier è corretto perché controlla prima `VERDICT:`.
3. **Il filtro anti-segreti scarta lezioni e card che citano un percorso con cifre.**
   `kitlib.looks_secret` (`kitlib.py:96-107`) tratta ogni sequenza di 32+ caratteri di
   `[A-Za-z0-9+/_=-]` con una lettera e una cifra come un token: `supabase/migrations/20260101120000_profiles_rls.sql`,
   `src/api/v2/handlers/user_profile.py`, uno sha256. Un FAIL del verifier sulle RLS non è mai
   diventato lezione; una card di classe A sulle migration è stata saltata in silenzio.
4. **Fresh eyes nasconde l'item a `next`.** `fresh-eyes.md:27` fa loggare `checked`; `items.py`
   legge l'ultima riga del LOG come stato, quindi `list --status queued` non restituisce più l'item e
   `next` passa alle card. Introdotto da me in 1.6.

E tre cose da sapere che non sono bug del kit ma cambi d'ambiente:

- **Claude Code 2.1.319 ha cambiato `/loop` a passo libero**: un turno che finisce senza
  ripianificare chiude il loop, senza più la sveglia di ripiego. Il template `init/loop.md` dice
  "stop appena non c'è nulla da fare": oggi un loop che tende una PR aperta si spegne al primo giro
  tranquillo.
- **I nomi dei thread richiedono agent teams**, che il kit non attiva (sperimentale). Il tool Agent
  non ha un parametro `name`; il lead dice "named after the item id" e "SendMessage to its agent
  name". La maniglia reale è l'ID che la chiamata restituisce, e sopravvive a un riavvio.
- **Nelle sessioni cloud il kit non c'è**: in questo container non è installato, `~/.claude` è
  effimero, e `CLAUDE_CODE_ENTRYPOINT=remote_mobile` fa credere a `lessons.headless()` che nessuno sia
  alla tastiera (niente riga di review, niente passata del modello, `promote` rifiuta).

## 1. Correzioni: kit 1.9.1

Difetti verificati, nessuna scelta di design. Un solo PR, ognuno con il suo test. Costo complessivo:
una mezza giornata.

| # | Difetto | Dove | Correzione | Fonte |
|---|---|---|---|---|
| 1 | REPORT.md e evidenza del gate nel worktree, non nel checkout principale | `subagent_stop.py:282`, `gate.py` | usare `subagent_start.main_checkout(cwd)` come radice degli item; il record del gate nel checkout principale | E1 |
| 2 | frase di chiusura archiviata al posto del report | `subagent_stop.py:287-293` | `report = handed or report` per l'implementer; un test con hand-back più frase di chiusura | A1 |
| 3 | `looks_secret` scarta percorsi con cifre | `kitlib.py:96-107` | un token con `/` o `.ext` o `parola_parola` è un percorso, non un segreto; i cinque esempi come test | A2, E3 |
| 4 | fresh-eyes logga `checked` | `lead/fresh-eyes.md:27` | `log <id> queued "fresh eyes: …"` | B1 |
| 5 | "Merge it solo su parola dell'utente" contro `merge: agent` | `lead/SKILL.md:76` | riscrivere il punto: vale per `user` e `ask`; il paragrafo sulla policy copre il resto | B2 |
| 6 | `EXPECT: 90m` letto dal prompt della chiamata Agent, non da BRIEF.md | `lead/SKILL.md:88`, `kit.tsx:397` | dire che va nel prompt | B3 |
| 7 | nomi dei thread (agent teams) | `lead/SKILL.md:65-66, 80-81`, `reference.md`, CATALOG riga 96 | usare l'agent ID: colonna `agent <id>`, `$I log <id> working "agent <agentId>"`; l'ID salvato nel LOG dagli hook (`subagent_start/stop` lo ricevono) così il lead riprende per ID anche dopo compattazione e riavvio | B4, C9 |
| 8 | report di uno scout in due posti | `lead/SKILL.md:68-69` | uno scout è un `kit:implementer` creato con `--kind scout` (il flag esiste e nessuno lo usa); il report finisce in REPORT.md come gli altri; via `.claude/lead/reports/` | B5 |
| 9 | `/loop` a passo libero si spegne (2.1.319) | `init/loop.md:14-29`, `go/SKILL.md:55-56` | "se la PR è ancora aperta, ripianifica il prossimo controllo; fermati solo a merge o chiusura" | C1 |
| 10 | `loop.md` committa il percorso assoluto del kit | `init/SKILL.md:63-67`, `init/loop.md` | far eseguire al loop il comando `verify` del progetto (già in allowlist) e citare `gate.py` solo se il kit è installato | E6 |
| 11 | snapshot `bash-snapshot` condiviso fra thread paralleli; preso anche senza `protect`/`onEdit` | `guard.py:1106-1137`, `bash_edits.py:39-45` | chiave `session.agent_id`; snapshot solo se la configurazione lo usa (toglie 0,1-0,2 s a ogni Bash nei progetti senza) | A3 |
| 12 | regola attribuzione nega `gh pr view … \| grep "generated with claude"` | `guard.py:767, 802-805` | limitarla ai sottocomandi che scrivono e ai valori di `-b/-t/-m`, come già per `git` | A4 |
| 13 | regola segreti nega `ssh -i ~/.ssh/key`, `kubectl --kubeconfig` | `guard.py:899-920` | lo strumento proprietario dello store è esente (ssh, kubectl, aws, gh, docker, gcloud, gpg) | A5 |
| 14 | la nudge "report mancante" scatta anche senza kit.json | `subagent_stop.py:276-285` | spostare il controllo della configurazione prima | A6 |
| 15 | `stacks.md` promette un guard che chiede prima di `supabase db push`, `vercel --prod`, `wrangler deploy`: non esiste (scelta tua) | `init/stacks.md:43-44` | togliere la frase | E7 |
| 16 | test del mod instabile: 1.920 tick in 4,2-5,0 s contro un cap di 5 s, fallito 5 volte su 16 | `kit.test.tsx:321-341` | kit.json di test con `watchdog` ridotto (40 tick) | D4 |
| 17 | due default per `checkTimeout` (540 e 1800), `verifyTimeout` letto e mai documentato | `stop_check.py:73`, `gate.py:128`, reference | un `GATE_TIMEOUTS` in kitlib; una riga nella reference | A8, B11, E12 |
| 18 | `dirty_snapshot` cerca `" -> "` in output `-z` (ramo morto, nome vecchio tagliato) | `kitlib.py:198-205` | saltare la voce dopo `R`/`C` | A7 |
| 19 | `items.py done` cancella un archivio precedente con lo stesso id | `items.py:189-191` | suffisso `-2` invece di `rmtree` | D §4.2 |
| 20 | riferimenti pendenti: "README §4", i vecchi nomi delle skill llm senza il prefisso `kit-llm:` nel CATALOG, "e2e skill" per `verify`, `MERGE:` assente nell'esempio di board, `kit:` nel prefisso della status line che il codice non scrive, "weekly sweep" contro 14 giorni, `agentsAsk: 15` nell'esempio (su una giornata in loop inizierebbe a chiedere al 16° subagente) | intake, CATALOG, init, README, reference | correzioni di una riga ciascuna | B6, B7, B9, E12 |
| 21 | la reference chiama `effort: medium` "floor" (è un livello fisso: anche una sessione a `low` fa thread a `medium`) e attribuisce a 2.1.302 un default di `-p` che vale solo su provider terzi, telemetria spenta o installazione nuova | `reference.md:209-210, 450-451` | due frasi | B10 |

## 2. Cuciture silenziose: robustezza e attrito

Cambi piccoli che tolgono un silenzio o una digitazione. Ognuno S; insieme un pomeriggio.

- **kit.json senza controllo.** `{}` vale "non aderito" per ogni hook tranne il guard; `chek`/`verfy`
  non stampano nulla, neppure "kit harness active". Proposta: SessionStart stampa sempre la riga di
  attivazione quando il file esiste e aggiunge "unknown key `chek` (did you mean `check`?)" da un
  insieme di chiavi note (livello alto, `lead`, `guard`, `watchdog`, `learn`, `llm`); `{}` conta come
  aderito ovunque. (E4, D6)
- **Item in coda invisibili.** `/kit:handoff lead` e `/kit:scout take` scrivono la cartella e basta:
  niente riga di board, niente conteggio nella status line; il lead li prende solo con `next`.
  Proposta: SessionStart e la riga di contesto del loop aggiungono "N queued item(s) on disk" quando
  ce ne sono. (E8)
- **Status line e notifiche legate al formato esatto della riga.** Una board scritta come tabella
  Markdown, `Review` maiuscolo o una riga `needs-you` senza `NEEDS YOU:` contano zero. Proposta:
  togliere i `|` esterni, saltare intestazione e separatore, cercare uno stato noto in qualunque
  cella, contare anche le righe `needs-you`. (E9)
- **Doppia notifica.** Il mod notifica a ogni tick in cui `ready`/`needs` crescono, il lead manda
  una PushNotification per lo stesso evento, il watchdog al terzo colpo. Proposta: il mod tace se
  `activity.get('main')` è nell'ultimo minuto; il lead non manda PushNotification quando il mod è
  caricato. (E10)
- **I dinieghi del guard diventano lezioni.** Una sonda ha prodotto sette candidati ("The kit guard
  blocks this (wait)…"), consegnati a ogni thread dentro il budget delle lezioni: regole che un hook
  già applica. Proposta: tenere l'evento per le statistiche, non la lezione. (E11)
- **Allowlist dei permessi.** `permission.py` lascia passare `gate.py`, `lessons.py`,
  `compact_logs.py` ma non `items.py` e `proposals.py`: in modalità default ogni azione di board è
  un prompt. (E13)
- **`${CLAUDE_SKILL_DIR}` anche nel lead.** Handoff, scout e learn definiscono gli script con
  `${CLAUDE_SKILL_DIR}/../../hooks/scripts/…`; il lead manda a `claude plugin marketplace list --json`
  a ogni sessione. (B8)
- **Git indurito negli hook.** Le chiamate `git status`/`diff`/`ls-files`/`rev-parse` degli hook
  girano con la configurazione della repo: un `core.hooksPath` o `core.fsmonitor` locale eseguirebbe
  codice ogni volta che un hook gira. Proposta: `-c core.hooksPath=/dev/null -c core.fsmonitor=false
  -c core.pager=cat -c core.sshCommand=false` in `kitlib.git_out` e negli altri punti. Da
  trio-agent-loop r31b; nessun cambio di comportamento per una repo onesta. (C2)
- **Deduplicazione in kitlib.** `git()`, `ensure_excluded`, `slug`, `index_lines`, `is_ai`,
  `temp_roots`, `config_dir` esistono in due copie; `lessons.repo()` lancia tre git per cinque volte
  a ogni SessionStart (una cache per processo toglie ~10 sottoprocessi). Parametri mai passati:
  `gate.status(branch, head_ref, exclude)`, `list_items(archived)`, `render(header)`. (A10)

## 3. Cloud

Usi sessioni cloud ogni giorno (questa lo è) e il kit lì non esiste. Tre pezzi, in ordine:

1. **Rilevamento "nessuno alla tastiera"** (S): `lessons.headless()` tratta ogni entrypoint fuori
   da `cli`/`claude-vscode`/`claude-desktop*` come non presidiato. `CLAUDE_CODE_SESSION_ATTENDED=1`
   dice il contrario e va rispettato; `CLAUDE_CODE_REMOTE=true` dovrebbe saltare l'offerta delle
   impostazioni di macchina (inutile in un container). (E2)
2. **Ricetta cloud nel README** (S): nello script di setup dell'ambiente, `claude plugin marketplace
   add <checkout>` e `claude plugin install kit@claude-kit`, poi `machine_setup.py --apply` non
   interattivo; dire cosa funziona (gate, guard, board, thread) e cosa no.
3. **Il libro mastro delle lezioni muore con il container** (decisione). Opzioni: (a) dirlo nel
   README: i thread cloud non imparano e non ricevono lezioni; (b) puntare il ledger a un percorso
   versionato per i progetti dove lo vuoi (`lessons.dir` in kit.json), accettando che le lezioni
   finiscano in git. Consiglio (a) oggi, (b) solo se il nightly in cloud ti serve davvero.

## 4. Test, eval e CI

Copertura misurata: 85,8 % delle righe degli script, ma tre entry point di hook non vengono mai
eseguiti da un test (`protect.py` 37 %, `on_edit.py` 46 %, `session_end.py` 4,5 %), e il contratto
`subagent_stop.py --missing` fra mod e script è simulato da entrambe le parti. Nessuna CI: la
replica dei controlli sugli ultimi dieci merge li trova tutti verdi tranne il test instabile; sul
primo commit di kit 1.4 avrebbe trovato un overflow del budget di `subagent_start` dipendente dalla
lunghezza del percorso, che fu corretto lo stesso giorno a mano. (D)

- **CI minima** (S): `.github/workflows/checks.yml` con due job, Python 3.9 e 3.13 (budget e
  self-check) e `claude plugin validate` + `claude plugin test` con la CLI fissata a 2.1.319
  (girano senza credenziali). Circa 4,5 minuti fatturati per run; la repo è privata, 2.000 minuti
  gratuiti al mese bastano per dieci merge ogni due settimane. Un terzo job manuale o settimanale
  per le eval, con la chiave API e un tetto di spesa, se lo vuoi. Più `tests/run.sh` per lanciare
  tutto a mano con un comando.
- **Test mancanti** (S ciascuno): entry point di `protect.py` e `on_edit.py` (payload Write/Edit/
  NotebookEdit, percorso fuori repo, kit.json rotto), `session_end.py` (cinque eventi → distiller
  avviato), `--missing` sui transcript già costruiti, `gate.py --timeout`/HEAD staccato/repo senza
  commit, `run_shell` in timeout, i sottocomandi CLI che le skill fanno eseguire (`items.py
  report|verdict`, `proposals.py show`, `lessons.py list|add|news|stats|promote`, `auto_mode_sync.py
  --preview|--show`).
- **Asserzioni deboli** (S): `kit.test.tsx:212` accetta zero o una notifica; `test_bash_edits.py:86`
  e `test_proposals.py:82` accettano entrambi i rami; `test_lessons.py` monkeypatcha senza
  ripristinare; data locale contro UTC fra `lessons.py` e `items.py`.
- **Eval** (M, e crediti quando girano): otto casi coprono otto flussi; nessuno copre ask mode in
  sola lettura, `/kit:handoff`, `/kit:scout`, le righe DECISION e il gate dell'implementer,
  fresh-eyes, l'uso di `items.py` dal lead, l'effort per thread. Sei casi sono già scritti nel
  formato documentato (D §5.3) più cinque grader da aggiungere a `lead-dispatches-threads` senza
  run in più. La suite com'è non gira senza sapere i flag: va scritto il comando
  (`--scaffold --trust-plugin --allow-tools Bash Write Edit`) e `runs: 3` sui due casi del lead.

## 5. Stato dell'arte: cosa assorbire

Dal changelog 2.1.314–2.1.319, dalle pagine di documentazione e dalle fonti del periodo (C).

**Cambi di Claude Code che toccano il kit**

| Cambio | Versione | Effetto sul kit | Proposta | Costo |
|---|---|---|---|---|
| `/loop` a passo libero termina senza sveglia di ripiego | 2.1.319 | `loop.md` si spegne al primo giro tranquillo | correzione 9 sopra | S |
| i subagenti in background spostano un comando shell in background dopo 3 minuti | 2.1.318 | un `verify` lungo torna come notifica di completamento; un thread può leggerla come risultato | una frase in `implementer.md`; un'eval con un gate di 4 minuti | S |
| `permissions.blockWritesOutsideWorkingDirectories` | 2.1.314 | rompe i thread su un'altra repo e toglie `EnterWorktree`/`ExitWorktree` | dirlo in `/kit-safety` e nel README: non per i progetti kit | S |
| `permissions.denyInsteadOfPrompting`: un prompt di permesso diventa un diniego e il turno continua | 2.1.319 | l'opzione "stasera non presidio": oggi un thread fermo su un prompt lo nota solo il watchdog dopo 2 minuti | offrirla in `/kit-safety` per una sera, spenta di default (decisione) | S |
| SendMessage raggiunge un thread mentre un comando gira (il comando passa in background) | 2.1.317 | un `FAIL scope=local` arriva subito | una riga nel lead e nella reference | S |
| i subagenti su un modello diverso usano l'effort di quel modello; `CLAUDE_CODE_SUBAGENT_EFFORT` | 2.1.317, 2.1.316 | niente per gli agenti kit (il frontmatter vince); utile per gli agenti tuoi e per Explore/Plan | una riga nella reference accanto a `CLAUDE_CODE_EFFORT_LEVEL` | S |
| `claude -p` esce 1 quando l'auto mode non ha potuto verificare, all'avvio fallito, a transcript perso; `credential_expires_at` nel JSON | 2.1.314–2.1.319, 2.1.318 | `overnight.py` oggi brucia tre iterazioni "no change" prima di fermarsi | leggere il codice d'uscita e fermarsi subito con il motivo; rifiutare un run che supera la scadenza del login; documentare l'interazione con `DISABLE_TELEMETRY` | S |
| controllo prima che uno strumento mandi in rete l'email dell'account | 2.1.317 | prompt su `git push`/`gh` nei thread se l'email git coincide con quella claude.ai | una riga in `/kit:init` sul campo `author` (noreply) | S |
| i nomi dei subagenti sopravvivono a un riavvio solo dalla compattazione in poi; `/tasks` riapre i finiti | docs, 2.1.319 | il lead deve avere l'ID | correzione 7 sopra | S |
| cap di 10.000 caratteri sull'output di un hook | 2.1.314 | la board reiniettata è a 8.000: dentro | nulla | — |
| eval: `max: 0` per uno strumento che non deve essere chiamato | 2.1.319 | i grader "no-edit" delle nuove eval | usarlo | — |

**Meccanismi da altri harness** (valutati sul codice, non sui README; i prodotti che sostituiscono il
lead sono esclusi)

| Meccanismo | Da | Proposta | Costo |
|---|---|---|---|
| effort che sale su un fallimento verificato, non sulla taglia del brief | arXiv 2610.34491 (partire basso e salire dopo un fallimento verificato eguaglia o batte l'effort massimo fisso a costo minore); pagina effort Anthropic | il lead tiene `low`/`medium` dal brief; su un `FAIL` non `scope=local` o un `BLOCKED` ridispaccia lo stesso item un livello sopra, mai oltre `high` senza chiedere; il livello finisce nel LOG | S |
| il verifier nomina l'albero giudicato | trio r34 (`evaluated:` con gli sha), House Party Protocol | la riga `VERDICT:` porta il commit o l'hash di `gate.py status`; `subagent_stop.py` lo logga e marca stantio un verdetto su un albero cambiato (log, non blocco) | S |
| regole guard da `/kit:learn` validate e prima `ask`, poi `deny` | Hivelore ("silenziosa sul codice attuale, scatta sull'errore"; warn prima di block) | la regex proposta deve matchare il comando catturato nel ledger e non i comandi recenti ammessi; nasce in `askCommands`, promossa a `denyCommands` al secondo avvistamento | M |
| commit di un'iterazione fallita salvati su `overnight/salvage-<n>` invece che scartati | trio r33 | opzione di `overnight.py`; il lead pulisce i rami dopo il merge | M |
| blocchi `json decision` in REPORT.md (`kind`, `question`, `choice`, `alternatives[{option, rejected_because}]`, `evidence_refs`) | trio r36 | validatore stdlib in `items.py`, formato solo offerto all'implementer, A/B con `claude plugin eval` prima di renderlo atteso | M |
| hook PreToolUse su `Agent` che rifiuta una chiamata `kit:implementer` senza `effort` o uno scout sopra `low` | claude-workflow-kit | renderebbe deterministica la regola sull'effort; da valutare dopo lo sweep | S |

**Evidenze del periodo** che confermano o correggono assunzioni del kit:

- Anthropic, "The components of agent memory" (6 nov): regole di scrittura esplicite ("registra
  solo i fallimenti") riducono il guadagno della memoria di 0,234 su Opus 5; contesto iniettato
  piccolo; un file per item, mai una tabella condivisa (41/57 fatti sopravvissuti contro 57/57).
  Il kit fa già così; non aggiungere regole "registra solo X" al prompt di memoria del verifier.
- arXiv 2611.04367 (3 nov): la formulazione condizionale ("quando X, fai Y") è la meno seguita
  nei context file. Una lezione condizionale va trasformata in hook o regola guard, non in frase:
  una regola per `/kit:learn` (S).
- arXiv 2610.34577 (25 ott): fra 17 design di verifica, il reviewer a contesto fresco ha il
  miglior rapporto accuratezza/costo e i promemoria dopo le modifiche un guadagno modesto; le
  istruzioni di verifica in prosa restano la leva debole. Conferma `kit:verifier` e `on_edit`.
- arXiv 2611.07166 (4 nov): il miglior modello completa il 18,5 % dei passi in catene di 5–15
  passi dipendenti. Il gate fra un passo e l'altro di `kit:overnight` è la risposta; il numero dice
  che le catene lunghe falliscono ancora più spesso di quanto riescano.
- arXiv 2610.35297: su 114k PR Java il gap di copertura dei test degli agenti non c'è sulle PR di
  feature, c'è su quelle di soli test. Il gate di diff-coverage di `stacks.md` resta giustificato
  su Python; su Java è meno urgente.

**Stack** (righe da una frase in `stacks.md`, `evidence-by-surface.md`, CATALOG): Next.js 16.4.5
del 3 novembre è una security release con sette avvisi (una card A "dependency security release"
per lo scout; `npm audit` nel `check`); Supabase CLI 4.0 porta `supabase stack`, un database locale
per worktree, ciò che i thread paralleli vogliono; il Supabase MCP 0.16 abilita i notebook di
default (tenere `read_only=true&features=`); cloudflare/skills ha tre skill nuove sullo sviluppo
locale; il Logging MCP di GCP è GA e lavora su un solo progetto per connessione; il tool `gh` dal
2.103 ha token OAuth a scadenza, da non mettere in cache negli script.

**Non proposto**, con il motivo: agent teams (sperimentale, senza worktree); il tool Workflow per il
lead (consenso per run; `/batch` è il fan-out nativo più vicino per le card A meccaniche, da provare
in `/kit:scout`); OpenCodeReview (benchmark del venditore; `/code-review` basta); agent-orchestrator,
zeroshot, workkit (prodotti o licenze non OSI); didwork (verifica hostata); channels (anteprima,
Bun). Un'idea sola da agent-orchestrator vale una riga nel lead: prima di mostrare la board,
rinfrescare `review`/`landing` da `gh pr view --json state,mergeable,statusCheckRollup` invece di
fidarsi dell'ultimo evento.

## 6. Prosa: una passata di consolidamento

Separata dalle correzioni perché è lavoro di lettura e non cambia comportamenti. (B12–B14)

- La stessa guida in tre o quattro posti: CLAUDE.local.md + `@AGENTS.md` + `.worktreeinclude` in
  README, init e lead; attribuzione e auto-mode in README, reference (tre sezioni), init e nel
  testo del SessionStart; la lista degli hook nel README ripete la reference quasi per intero.
  Una casa per ciascuna, un link dalle altre.
- Istruzioni che duplicano un hook: "aggiungi `/.claude/lead/` a exclude" (lo fa `items.py`),
  "non aspettare in foreground" (lo fa il guard e i subagenti partono in background di default).
- Leggibilità nelle skill più usate: la lista del brief nel lead è una catena di 15 righe con
  parentetiche annidate; il passo 3 dell'implementer è una frase di dieci righe; il passo 7 di
  `go` mette quattro meccanismi in un paragrafo; `git -C <repo> worktree add … <repo>-<id>` crea
  il worktree dentro `<repo>` se il percorso non è assoluto; il verifier scrive `origin/main` nella
  stessa frase in cui dice "dal branch base".

Costo M. Dopo, il budget del lead (150 righe) avrà spazio per le righe nuove di questa proposta.

## 7. Da decidere

1. **Correzioni (sezione 1)**: tutte in un PR 1.9.1, con test. Le uniche che toccano il guard sono
   due falsi positivi di regole già presenti (12, 13): si tolgono i falsi positivi, non si aggiungono
   regole.
2. **Cuciture (sezione 2)**: tutte, o quali. Consiglio tutte: sono S e tolgono silenzi.
3. **Cloud (sezione 3)**: 1 e 2 subito; per il ledger, (a) dirlo o (b) versionarlo.
4. **CI e test (sezione 4)**: la CI minima e i test mancanti subito; le eval nuove scritte ora e
   fatte girare quando vuoi spendere i crediti (una stima: 3–6 dollari a passata con `--runs 1`).
5. **Stato dell'arte (sezione 5)**: le righe S delle due tabelle subito; da scegliere
   `denyInsteadOfPrompting` come opzione serale, l'escalation dell'effort su fallimento, la
   validazione delle regole guard da `/kit:learn` (M), il salvage dell'overnight (M), i blocchi
   decision (M, dopo A/B).
6. **Prosa (sezione 6)**: un PR a parte, dopo le correzioni.

Ordine proposto: 1 → 2+3 → 4 → 5 → 6, ognuno un PR piccolo con la sua evidenza, mergiato da te.

## Fonti

Rapporti integrali, con sonde e numeri: [analisi-2026-11-08/A-code.md](analisi-2026-11-08/A-code.md),
[B-prose.md](analisi-2026-11-08/B-prose.md), [C-sota.md](analisi-2026-11-08/C-sota.md),
[D-tests.md](analisi-2026-11-08/D-tests.md), [E-ux.md](analisi-2026-11-08/E-ux.md). Le fonti
esterne (changelog, pagine di documentazione, articoli, repository con commit e data) sono citate
dentro C con URL e data; le pagine non raggiungibili dalla rete di questa sessione sono marcate.
